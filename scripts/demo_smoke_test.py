#!/usr/bin/env python3
"""
Smoke test script: registers a tenant, uploads an object via the proxy, and verifies replication job completion.
"""
import argparse
import hashlib
import json
import os
import time

import requests
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials


def register_tenant(api_base: str, admin_key: str, customer_id: str, access_key: str, secret_key: str):
    resp = requests.post(
        f"{api_base}/proxy/credentials",
        json={
            "customer_id": customer_id,
            "access_key": access_key,
            "secret_key": secret_key,
        },
        headers={"X-Admin-Key": admin_key},
        timeout=10,
    )
    resp.raise_for_status()


def register_bucket(api_base: str, admin_key: str, customer_id: str, logical_name: str, backend_ids):
    resp = requests.post(
        f"{api_base}/proxy/buckets",
        json={
            "customer_id": customer_id,
            "region_id": "demo",
            "logical_name": logical_name,
            "backend_ids": backend_ids,
        },
        headers={"X-Admin-Key": admin_key},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["backend_mapping"]


def sign_request(method: str, url: str, body: bytes, access_key: str, secret_key: str):
    headers = {
        "host": url.split("//", 1)[1].split("/", 1)[0],
        "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
        "x-amz-date": "20240101T000000Z",
    }
    req = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(Credentials(access_key, secret_key), "s3", "us-east-1").add_auth(req)
    return dict(req.headers.items())


def upload_via_proxy(proxy_base: str, logical_bucket: str, key: str, data: bytes, access_key: str, secret_key: str):
    url = f"{proxy_base}/s3/{logical_bucket}/{key}"
    headers = sign_request("PUT", url, data, access_key, secret_key)
    resp = requests.put(url, headers=headers, data=data, timeout=10)
    resp.raise_for_status()


def create_replication_job(api_base: str, admin_key: str, object_id: int, target_backend: str):
    resp = requests.post(
        f"{api_base}/proxy/jobs",
        json={"object_id": object_id, "target_backend": target_backend},
        headers={"X-Admin-Key": admin_key},
        timeout=10,
    )
    resp.raise_for_status()


def wait_for_jobs(api_base: str, admin_key: str, timeout_s: int = 30):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        resp = requests.get(
            f"{api_base}/proxy/jobs",
            params={"status": "pending"},
            headers={"X-Admin-Key": admin_key},
            timeout=10,
        )
        resp.raise_for_status()
        if not resp.json()["jobs"]:
            return True
        time.sleep(2)
    return False


def main():
    parser = argparse.ArgumentParser(description="Run smoke test against running proxy.")
    parser.add_argument("--api-base", default="http://localhost:8000")
    parser.add_argument("--proxy-base", default="http://localhost:8000")
    parser.add_argument("--admin-key", default=os.getenv("ADMIN_API_KEY", "demo-admin"))
    parser.add_argument("--source-backend", default="primary")
    parser.add_argument("--target-backend", default="secondary")
    parser.add_argument("--customer-id", default="demo-tenant")
    parser.add_argument("--logical-bucket", default="demo-bucket")
    parser.add_argument("--object-key", default="demo.txt")
    parser.add_argument("--access-key", default="DEMOACCESS")
    parser.add_argument("--secret-key", default="DEMOSECRET")
    args = parser.parse_args()

    print("Registering tenant credentials...")
    register_tenant(args.api_base, args.admin_key, args.customer_id, args.access_key, args.secret_key)

    print("Registering bucket mappings...")
    backend_mapping = register_bucket(
        args.api_base,
        args.admin_key,
        args.customer_id,
        args.logical_bucket,
        [args.source_backend, args.target_backend],
    )

    print("Creating discovery entry for source backend...")
    meta_resp = requests.post(
        f"{args.api_base}/proxy/objects",
        json={
            "customer_id": args.customer_id,
            "logical_name": args.logical_bucket,
            "backend_id": args.source_backend,
            "object_key": args.object_key,
            "size": len(args.object_key),
            "etag": "demo-etag",
            "targets": [args.target_backend],
        },
        headers={"X-Admin-Key": args.admin_key},
        timeout=10,
    )
    meta_resp.raise_for_status()
    object_id = meta_resp.json()["id"]

    print("Uploading object via SigV4 proxy...")
    upload_via_proxy(
        args.proxy_base,
        args.logical_bucket,
        args.object_key,
        args.object_key.encode("utf-8"),
        args.access_key,
        args.secret_key,
    )

    print("Waiting for replication worker to drain jobs...")
    ok = wait_for_jobs(args.api_base, args.admin_key)
    if not ok:
        raise SystemExit("Replication jobs did not complete in time")

    print("Smoke test completed successfully.")


if __name__ == "__main__":
    main()

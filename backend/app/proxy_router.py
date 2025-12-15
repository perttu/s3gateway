"""
SigV4-compatible proxy router that fronts S3-compatible backends.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict
import sqlite3

from botocore.awsrequest import AWSRequest
from botocore.auth import SigV4Auth
from botocore.credentials import Credentials
from fastapi import APIRouter, Request, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse

from .db import get_db, fetch_tenant_by_access_key, fetch_bucket_mapping
from . import backend_clients

router = APIRouter(tags=["s3-proxy"])

@dataclass
class SigV4Components:
    access_key: str
    region: str
    signed_headers: str
    signature: str


def parse_authorization_header(header: str) -> SigV4Components:
    if not header or not header.startswith("AWS4-HMAC-SHA256"):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    _, remainder = header.split(" ", 1)
    params = {}
    for part in remainder.split(","):
        if "=" in part:
            key, value = part.strip().split("=", 1)
            params[key] = value
    credential = params.get("Credential")
    signed_headers = params.get("SignedHeaders")
    signature = params.get("Signature")
    if not credential or not signed_headers or not signature:
        raise HTTPException(status_code=401, detail="Invalid SigV4 header")
    cred_parts = credential.split("/")
    if len(cred_parts) < 4:
        raise HTTPException(status_code=401, detail="Invalid Credential scope")
    access_key = cred_parts[0]
    region = cred_parts[2]
    return SigV4Components(
        access_key=access_key,
        region=region,
        signed_headers=signed_headers,
        signature=signature,
    )


def verify_signature(request: Request, body: bytes, components: SigV4Components, secret_key: str):
    signed_names = [name.strip() for name in components.signed_headers.split(";") if name.strip()]
    lower_headers = {k.lower(): v for k, v in request.headers.items()}
    filtered_headers = {}
    for name in signed_names:
        value = lower_headers.get(name)
        if value is not None:
            filtered_headers[name] = value
    aws_request = AWSRequest(method=request.method, url=str(request.url), data=body, headers=filtered_headers)
    credentials = Credentials(components.access_key, secret_key)
    SigV4Auth(credentials, "s3", components.region).add_auth(aws_request)
    generated = aws_request.headers.get("Authorization")
    if not generated:
        raise HTTPException(status_code=401, detail="Unable to verify signature")
    generated_sig = generated.split("Signature=")[-1]
    if generated_sig != components.signature:
        raise HTTPException(status_code=401, detail="Signature mismatch")


def resolve_backend_bucket(
    conn: sqlite3.Connection, customer_id: str, logical_name: str, backend_id: str
) -> str:
    row = fetch_bucket_mapping(conn, customer_id, logical_name, backend_id)
    if not row:
        raise HTTPException(status_code=404, detail="Bucket mapping not found for backend")
    return row["backend_bucket"]


@router.api_route(
    "/s3/{logical_name}/{object_path:path}",
    methods=["GET", "PUT", "DELETE", "HEAD"],
)
async def proxy_request(
    logical_name: str,
    object_path: str,
    request: Request,
    conn: sqlite3.Connection = Depends(get_db),
):
    body = await request.body()
    auth_header = request.headers.get("authorization")
    components = parse_authorization_header(auth_header)
    credential = fetch_tenant_by_access_key(conn, components.access_key)
    if not credential:
        raise HTTPException(status_code=403, detail="Unknown access key")
    verify_signature(request, body, components, credential["secret_key"])

    backend_id = request.query_params.get("backend_id") or backend_clients.DEFAULT_BACKEND_ID
    backend_bucket = resolve_backend_bucket(conn, credential["customer_id"], logical_name, backend_id)
    client = backend_clients.get_client(backend_id)
    key = object_path or ""

    if request.method == "GET":
        response = client.get_object(Bucket=backend_bucket, Key=key)
        return StreamingResponse(
            response["Body"],
            media_type=response.get("ContentType", "application/octet-stream"),
            headers={"ETag": response.get("ETag", "")},
        )
    if request.method == "PUT":
        client.put_object(
            Bucket=backend_bucket,
            Key=key,
            Body=body,
            ContentType=request.headers.get("content-type"),
        )
        return {"status": "uploaded", "backend": backend_id}
    if request.method == "DELETE":
        client.delete_object(Bucket=backend_bucket, Key=key)
        return {"status": "deleted", "backend": backend_id}
    if request.method == "HEAD":
        response = client.head_object(Bucket=backend_bucket, Key=key)
        return Response(status_code=200, headers={"ETag": response.get("ETag", "")})

    raise HTTPException(status_code=405, detail="Method not supported")

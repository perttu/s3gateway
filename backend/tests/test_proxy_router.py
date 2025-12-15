import datetime
import hashlib
import io

import pytest
import httpx
import anyio
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest
from botocore.credentials import Credentials

from main import app
from app import db as db_module


def sign_request(method: str, url: str, body: bytes, access_key: str, secret_key: str):
    payload_hash = hashlib.sha256(body).hexdigest()
    headers = {
        "host": "testserver",
        "x-amz-date": datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ"),
        "x-amz-content-sha256": payload_hash,
    }
    aws_request = AWSRequest(method=method, url=url, data=body, headers=headers)
    SigV4Auth(Credentials(access_key, secret_key), "s3", "us-east-1").add_auth(aws_request)
    return dict(aws_request.headers.items())


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("PROXY_DB_INIT_DISABLED", "1")
    monkeypatch.setenv("PROXY_ROUTER_ENDPOINT", "http://backend.example.com")
    monkeypatch.setenv("PROXY_ROUTER_ACCESS_KEY", "backend-access")
    monkeypatch.setenv("PROXY_ROUTER_SECRET_KEY", "backend-secret")
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin")
    monkeypatch.setenv("TENANT_SECRET_PASSPHRASE", "unit-test-passphrase")
    transport = httpx.ASGITransport(app=app)
    async_client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    db_module.init_db()
    yield async_client
    anyio.run(async_client.aclose)
    monkeypatch.delenv("PROXY_DB_INIT_DISABLED", raising=False)
    monkeypatch.delenv("PROXY_ROUTER_ENDPOINT", raising=False)
    monkeypatch.delenv("PROXY_ROUTER_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PROXY_ROUTER_SECRET_KEY", raising=False)


class StubClient:
    def __init__(self):
        self.storage = {}

    def get_object(self, Bucket, Key):
        data = self.storage.get((Bucket, Key), b"")
        return {"Body": io.BytesIO(data), "ContentType": "text/plain", "ETag": '"etag"'}

    def put_object(self, Bucket, Key, Body, ContentType=None):
        self.storage[(Bucket, Key)] = Body

    def delete_object(self, Bucket, Key):
        self.storage.pop((Bucket, Key), None)

    def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self.storage:
            raise Exception("missing")
        return {"ETag": '"etag"'}


@pytest.fixture()
def stub_backend(monkeypatch):
    client = StubClient()
    monkeypatch.setattr("app.backend_clients.get_client", lambda backend_id: client)
    return client


async def setup_proxy_state(client: httpx.AsyncClient):
    resp = await client.post(
        "/proxy/credentials",
        json={"customer_id": "tenant-1", "access_key": "AKIA123", "secret_key": "secret123"},
        headers={"X-Admin-Key": "test-admin"},
    )
    assert resp.status_code == 200, resp.text
    resp = await client.post(
        "/proxy/buckets",
        json={
            "customer_id": "tenant-1",
            "region_id": "fi",
            "logical_name": "docs",
            "backend_ids": ["primary"],
        },
        headers={"X-Admin-Key": "test-admin"},
    )
    assert resp.status_code == 200, resp.text


def test_proxy_put_and_get(client, stub_backend):
    async def scenario():
        await setup_proxy_state(client)
        base = str(client.base_url)
        if not base.endswith("/"):
            base += "/"
        url = base + "s3/docs/report.txt"
        headers = sign_request("PUT", url, b"hello", "AKIA123", "secret123")
        resp = await client.put("/s3/docs/report.txt", content=b"hello", headers=headers)
        assert resp.status_code == 200
        assert stub_backend.storage

        headers_get = sign_request("GET", url, b"", "AKIA123", "secret123")
        resp_get = await client.get("/s3/docs/report.txt", headers=headers_get)
        assert resp_get.status_code == 200
        assert resp_get.content == b"hello"

    anyio.run(scenario)


def test_proxy_missing_credentials(client):
    async def scenario():
        base = str(client.base_url)
        if not base.endswith("/"):
            base += "/"
        url = base + "s3/docs/report.txt"
        headers = sign_request("GET", url, b"", "UNKNOWN", "secret")
        resp = await client.get("/s3/docs/report.txt", headers=headers)
        assert resp.status_code == 403

    anyio.run(scenario)

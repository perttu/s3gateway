"""
Shared helpers for creating boto3 clients targeting S3-compatible backends.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict

import boto3
from fastapi import HTTPException


def parse_mapping(value: str | None) -> Dict[str, str]:
    mapping: Dict[str, str] = {}
    if not value:
        return mapping
    for part in value.split(","):
        if "=" in part:
            key, endpoint = part.split("=", 1)
            mapping[key.strip()] = endpoint.strip()
    return mapping


DEFAULT_BACKEND_ID = os.getenv("S3_BACKEND_DEFAULT_ID") or os.getenv(
    "PROXY_ROUTER_DEFAULT_BACKEND_ID", "primary"
)

ENDPOINTS = parse_mapping(
    os.getenv("S3_BACKEND_ENDPOINTS") or os.getenv("PROXY_ROUTER_ENDPOINTS")
)
if not ENDPOINTS:
    default_endpoint = os.getenv("S3_BACKEND_ENDPOINT") or os.getenv("PROXY_ROUTER_ENDPOINT")
    if default_endpoint:
        ENDPOINTS[DEFAULT_BACKEND_ID] = default_endpoint

REGION = os.getenv("S3_BACKEND_REGION") or os.getenv("PROXY_ROUTER_REGION", "us-east-1")

ACCESS_KEY = os.getenv("S3_BACKEND_ACCESS_KEY") or os.getenv("PROXY_ROUTER_ACCESS_KEY")
SECRET_KEY = os.getenv("S3_BACKEND_SECRET_KEY") or os.getenv("PROXY_ROUTER_SECRET_KEY")


@lru_cache(maxsize=16)
def get_client(backend_id: str):
    endpoint = ENDPOINTS.get(backend_id)
    if not endpoint:
        raise HTTPException(status_code=500, detail=f"S3 endpoint for backend {backend_id} not configured")
    if not ACCESS_KEY or not SECRET_KEY:
        raise HTTPException(status_code=500, detail="S3 backend credentials not configured")
    return boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name=REGION,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
    )

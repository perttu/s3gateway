"""
Admin auth dependency for securing proxy metadata endpoints.
"""
import os
from fastapi import Header, HTTPException


def require_admin(x_admin_key: str = Header(default=None)) -> None:
    admin_key = os.getenv("ADMIN_API_KEY")
    if not admin_key:
        raise HTTPException(
            status_code=500,
            detail="ADMIN_API_KEY must be set to call admin endpoints",
        )
    if x_admin_key != admin_key:
        raise HTTPException(status_code=401, detail="Invalid admin key")

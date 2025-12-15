"""
Bucket hashing helpers shared by the discovery API and future S3 proxy layer.

The functions below mirror the deterministic behaviour implemented in the legacy
``s3gateway`` proof-of-concept, but without any database or SQLAlchemy coupling.
They can be reused by FastAPI routes, background workers, or CLI tooling when
mapping logical bucket names to backend-specific physical buckets.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Dict, Iterable


DEFAULT_PREFIX = "s3gw"
DEFAULT_HASH_LENGTH = 16


@dataclass(frozen=True)
class BucketHashInput:
    """Configuration required to produce deterministic backend bucket names."""

    customer_id: str
    region_id: str
    logical_name: str
    backend_id: str
    collision_counter: int = 0


def generate_backend_bucket_name(
    bucket_input: BucketHashInput,
    *,
    prefix: str = DEFAULT_PREFIX,
    hash_length: int = DEFAULT_HASH_LENGTH,
) -> str:
    """
    Produce a deterministic, S3-compliant bucket name for the given inputs.

    Args:
        bucket_input: Structured input (customer/logical/back-end identifiers).
        prefix: Optional bucket prefix (defaults to "s3gw").
        hash_length: Number of hex characters to include from the SHA-256 digest.

    Returns:
        A lowercase bucket name such as ``s3gw-deadbeef-frontier``.
    """

    hash_input = (
        f"{bucket_input.customer_id}:{bucket_input.region_id}:"
        f"{bucket_input.logical_name}:{bucket_input.backend_id}:"
        f"{bucket_input.collision_counter}"
    )
    digest = hashlib.sha256(hash_input.encode("utf-8")).hexdigest()
    hash_part = digest[:hash_length]

    backend_suffix = bucket_input.backend_id.lower().replace("_", "-")[:8] or "backend"
    bucket_name = f"{prefix}-{hash_part}-{backend_suffix}".lower()

    # Keep overall length <= 63 characters per S3 requirements.
    if len(bucket_name) > 63:
        bucket_name = f"{prefix}-{digest[:20]}-{backend_suffix[:8]}"
    return bucket_name


def map_backends(
    *,
    customer_id: str,
    region_id: str,
    logical_name: str,
    backend_ids: Iterable[str],
) -> Dict[str, str]:
    """
    Create a mapping of ``backend_id -> backend_bucket_name``.

    Args:
        customer_id: Unique customer/tenant identifier.
        region_id: Placement region or residency scope.
        logical_name: User-facing bucket name.
        backend_ids: Iterable of backend identifiers.

    Returns:
        Dict mapping each backend_id to a hashed bucket name.
    """

    mapping: Dict[str, str] = {}
    for backend_id in backend_ids:
        input_data = BucketHashInput(
            customer_id=customer_id,
            region_id=region_id,
            logical_name=logical_name,
            backend_id=backend_id,
        )
        mapping[backend_id] = generate_backend_bucket_name(input_data)
    return mapping

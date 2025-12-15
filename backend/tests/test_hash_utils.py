import pytest

from app import hash_utils


def test_generate_backend_bucket_name_deterministic():
    inputs = hash_utils.BucketHashInput(
        customer_id="cust-123",
        region_id="eu-central",
        logical_name="analytics",
        backend_id="frontier",
    )

    first = hash_utils.generate_backend_bucket_name(inputs)
    second = hash_utils.generate_backend_bucket_name(inputs)
    assert first == second
    assert first.startswith(hash_utils.DEFAULT_PREFIX)
    assert first.islower()


def test_generate_backend_bucket_name_handles_collisions():
    base = hash_utils.BucketHashInput(
        customer_id="cust-abc",
        region_id="us-east",
        logical_name="invoices",
        backend_id="ceph-cluster",
    )
    name_a = hash_utils.generate_backend_bucket_name(base)
    name_b = hash_utils.generate_backend_bucket_name(
        hash_utils.BucketHashInput(**{**base.__dict__, "collision_counter": 1})
    )
    assert name_a != name_b


@pytest.mark.parametrize(
    "backend_ids, expected_count",
    [
        (["cluster-a"], 1),
        (["cluster-a", "cluster-b"], 2),
    ],
)
def test_map_backends_creates_mapping(backend_ids, expected_count):
    mapping = hash_utils.map_backends(
        customer_id="tenant-1",
        region_id="fi",
        logical_name="logs",
        backend_ids=backend_ids,
    )
    assert len(mapping) == expected_count
    for backend_id, bucket_name in mapping.items():
        assert backend_id in backend_ids
        assert bucket_name.startswith(hash_utils.DEFAULT_PREFIX)
        assert bucket_name.islower()

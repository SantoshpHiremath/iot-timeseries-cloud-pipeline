"""
Tests for the S3 landing layer, run against moto's mocked AWS backend
(see src/s3_landing.py's module docstring for why -- this sandbox has no
outbound access to real AWS). These tests exercise the real boto3 client
API surface (create_bucket, put_object, list_objects_v2 via paginator,
get_object) against the mock, which is the same interface a real AWS
account would present.
"""

import pytest
from moto import mock_aws

from src.s3_landing import get_s3_client, ensure_bucket, upload_raw_batch, list_raw_keys, read_raw_object


@pytest.fixture
def s3():
    with mock_aws():
        client = get_s3_client()
        ensure_bucket(client, "test-bucket")
        yield client


def test_ensure_bucket_is_idempotent(s3):
    # calling ensure_bucket again should not raise
    ensure_bucket(s3, "test-bucket")
    buckets = [b["Name"] for b in s3.list_buckets()["Buckets"]]
    assert buckets.count("test-bucket") == 1


def test_upload_and_read_roundtrip(s3):
    key = upload_raw_batch(s3, "test-bucket", "veh-001", 0, b'{"a": 1}')
    assert key == "device_id=veh-001/batch=00000.jsonl"
    data = read_raw_object(s3, "test-bucket", key)
    assert data == b'{"a": 1}'


def test_list_raw_keys_filters_by_device(s3):
    upload_raw_batch(s3, "test-bucket", "veh-001", 0, b"{}")
    upload_raw_batch(s3, "test-bucket", "veh-001", 1, b"{}")
    upload_raw_batch(s3, "test-bucket", "veh-002", 0, b"{}")

    veh1_keys = list_raw_keys(s3, "test-bucket", device_id="veh-001")
    assert len(veh1_keys) == 2
    assert all("veh-001" in k for k in veh1_keys)

    all_keys = list_raw_keys(s3, "test-bucket")
    assert len(all_keys) == 3


def test_list_raw_keys_empty_bucket_returns_empty_list(s3):
    assert list_raw_keys(s3, "test-bucket") == []

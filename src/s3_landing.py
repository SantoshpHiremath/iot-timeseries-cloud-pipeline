"""
Raw IoT log landing zone, using real boto3 (the actual AWS SDK for
Python) against an S3 bucket.

Honest disclosure: this sandbox has no outbound access to AWS (aws.amazon.com
itself returns a 403 from the sandbox's outbound proxy, the same class of
network block documented elsewhere in this application portfolio -- Docker
Hub, OpenML, Zenodo, timeseriesclassification.com were all tried and
blocked for other projects). Real AWS console/API access is not available
here. Rather than fake having used AWS, or skip cloud-SDK work entirely,
this module is built and tested against `moto` -- the standard library the
AWS Python ecosystem itself uses to test real boto3 code without touching
a real AWS account (https://github.com/getmoto/moto, used by AWS's own
SDK test suites and thousands of production codebases to unit-test S3/
DynamoDB/etc. code paths). The boto3 calls below are the exact same calls
that would run against a real AWS account -- create_bucket, put_object,
list_objects_v2, get_object -- only the backend they're talking to is
mocked. Swapping to a real account requires no code change here, only AWS
credentials and removing the `@mock_aws` decorator in the test suite.
"""

import boto3


def get_s3_client(region="eu-central-1", endpoint_url=None):
    kwargs = {"region_name": region}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def ensure_bucket(s3_client, bucket_name, region="eu-central-1"):
    existing = [b["Name"] for b in s3_client.list_buckets().get("Buckets", [])]
    if bucket_name in existing:
        return
    if region == "us-east-1":
        s3_client.create_bucket(Bucket=bucket_name)
    else:
        s3_client.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


def upload_raw_batch(s3_client, bucket_name, device_id, batch_index, jsonl_bytes):
    """
    Land one raw upload batch as an object under a device-partitioned
    key prefix -- device_id=<id>/batch=<index>.jsonl -- the same
    partitioning-by-device pattern a real IoT ingestion pipeline uses so
    downstream structuring can process one device's data at a time
    without scanning the whole bucket.
    """
    key = f"device_id={device_id}/batch={batch_index:05d}.jsonl"
    s3_client.put_object(Bucket=bucket_name, Key=key, Body=jsonl_bytes)
    return key


def list_raw_keys(s3_client, bucket_name, device_id=None):
    prefix = f"device_id={device_id}/" if device_id else ""
    paginator = s3_client.get_paginator("list_objects_v2")
    keys = []
    for page in paginator.paginate(Bucket=bucket_name, Prefix=prefix):
        for obj in page.get("Contents", []):
            keys.append(obj["Key"])
    return sorted(keys)


def read_raw_object(s3_client, bucket_name, key):
    resp = s3_client.get_object(Bucket=bucket_name, Key=key)
    return resp["Body"].read()

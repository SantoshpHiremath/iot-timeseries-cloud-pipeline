"""
End-to-end pipeline: generate synthetic IoT telemetry, land it raw in
(mocked) S3 partitioned by device, structure and deduplicate it into a
queryable DuckDB time-series table, detect data-integrity gaps (e.g. an
OTA-update connectivity loss), and measure query performance with vs.
without the device+timestamp index.
"""

import time

from moto import mock_aws

from src.generate_telemetry import generate_raw_upload_batches, logs_to_jsonl_bytes
from src.s3_landing import get_s3_client, ensure_bucket, upload_raw_batch, list_raw_keys, read_raw_object
from src.structure_timeseries import get_connection, structure_batch, query_device_series, row_count, detect_data_gaps

BUCKET_NAME = "me-battery-telemetry-raw"


def _run_pipeline_impl(seed=42, batch_size=50):
    s3 = get_s3_client()
    ensure_bucket(s3, BUCKET_NAME)

    batches, silent_windows = generate_raw_upload_batches(seed=seed)

    batch_index = 0
    for device_id, logs in batches.items():
        # Upload in chunks of `batch_size`, simulating periodic uploads
        # rather than one giant dump.
        for start in range(0, len(logs), batch_size):
            chunk = logs[start:start + batch_size]
            upload_raw_batch(s3, BUCKET_NAME, device_id, batch_index, logs_to_jsonl_bytes(chunk))
            batch_index += 1

    con = get_connection()
    total_inserted = 0
    for key in list_raw_keys(s3, BUCKET_NAME):
        raw_bytes = read_raw_object(s3, BUCKET_NAME, key)
        total_inserted += structure_batch(con, raw_bytes)

    results = {
        "raw_objects_uploaded": len(list_raw_keys(s3, BUCKET_NAME)),
        "raw_records_seen": total_inserted,
        "clean_rows_stored": row_count(con),
        "gaps_by_device": {},
    }

    for device_id in batches.keys():
        gaps = detect_data_gaps(con, device_id)
        results["gaps_by_device"][device_id] = gaps

    results["expected_silent_windows"] = silent_windows
    return con, results


@mock_aws
def run_pipeline(seed=42, batch_size=50):
    """
    Public entry point, wrapped in @mock_aws so every boto3 call inside
    (create_bucket, put_object, list_objects_v2, get_object) is served
    by moto's in-process mock rather than attempting a real network call
    to AWS -- this sandbox has no outbound access to AWS (see
    s3_landing.py's module docstring for the disclosure). The DuckDB
    connection returned here stays open after the mock_aws context
    exits, since DuckDB itself is real and local, not mocked.
    """
    return _run_pipeline_impl(seed=seed, batch_size=batch_size)


def measure_query_performance(con, device_id="veh-001", n_repeats=200):
    """
    Compare query latency for a device-range lookup with the
    (device_id, ts) index present vs. dropped, demonstrating the actual
    query-performance-improvement task the posting names, with a real
    measured number rather than an assumed one.
    """
    con.execute("DROP INDEX IF EXISTS idx_telemetry_device_ts")
    t0 = time.perf_counter()
    for _ in range(n_repeats):
        con.execute("SELECT * FROM telemetry WHERE device_id = ? ORDER BY ts", [device_id]).fetchall()
    no_index_time = time.perf_counter() - t0

    con.execute("CREATE INDEX idx_telemetry_device_ts ON telemetry (device_id, ts)")
    t0 = time.perf_counter()
    for _ in range(n_repeats):
        con.execute("SELECT * FROM telemetry WHERE device_id = ? ORDER BY ts", [device_id]).fetchall()
    with_index_time = time.perf_counter() - t0

    return {"no_index_seconds": no_index_time, "with_index_seconds": with_index_time}


if __name__ == "__main__":
    con, results = run_pipeline()
    print("=== IoT telemetry ingestion (mocked S3 -> DuckDB time-series table) ===")
    print(f"  raw objects uploaded: {results['raw_objects_uploaded']}")
    print(f"  raw records seen (incl. duplicates): {results['raw_records_seen']}")
    print(f"  clean rows stored (after dedup): {results['clean_rows_stored']}")
    print()
    print("=== Data-integrity gap detection (per device) ===")
    for device_id, gaps in results["gaps_by_device"].items():
        print(f"  {device_id}: {len(gaps)} gap(s) found")
        for start, end, seconds in gaps:
            print(f"    gap from ts={start} to ts={end} ({seconds}s)")
    print(f"  expected silent windows (ground truth): {results['expected_silent_windows']}")
    print()
    print("=== Query performance: indexed vs. non-indexed lookup ===")
    perf = measure_query_performance(con)
    for k, v in perf.items():
        print(f"  {k}: {v:.4f}s")

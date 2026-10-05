# IoT Time-Series Cloud Pipeline: Battery Telemetry Ingestion and Data Integrity

A tested Python project that lands raw IoT battery-telemetry logs in S3, structures and deduplicates them into a queryable time-series table, detects data-integrity gaps (for example an OTA-update connectivity loss), and measures query performance. It covers cloud SDK usage, time-series storage, and query-performance work on top of a SQL, ELT, and monitoring foundation.

## What it does

- **`src/generate_telemetry.py`**: a per-vehicle battery telemetry generator (3 devices, 500 readings each) producing voltage, current, temperature, and SOC, with out-of-order delivery, a 2% duplicate upload rate, and one device (`veh-002`) with an injected 50-reading silent window (a connectivity/OTA-update outage).
- **`src/s3_landing.py`**: lands raw telemetry as JSON-lines objects in an S3 bucket, partitioned by `device_id=<id>/batch=<n>.jsonl`, the device-partitioning pattern a real IoT ingestion pipeline uses so downstream processing does not need to scan the whole bucket.
- **`src/structure_timeseries.py`**: parses raw S3 objects and structures them into a clean, indexed DuckDB time-series table. It does exact-match deduplication (verified not to overcollapse genuinely distinct readings, see Notes), sorts by timestamp per device, and runs a data-integrity gap detector that flags timestamp gaps larger than 3x the expected sampling interval, which is how OTA-update data loss is monitored.
- **`src/pipeline.py`**: runs the full flow end to end and measures query latency with and without the `(device_id, ts)` index.

## Scope

The telemetry is synthetic, generated per vehicle with realistic messiness (out-of-order delivery, occasional duplicate uploads, and one device with an injected connectivity outage). The pipeline is built so real device logs can replace the generator.

S3 is served by [`moto`](https://github.com/getmoto/moto), the standard library the AWS Python ecosystem uses to test boto3 code without a real account. Every boto3 call in the project (`create_bucket`, `put_object`, `list_objects_v2` via paginator, `get_object`) is the exact call that runs against a real AWS account; only the backend is mocked. Moving to a real account needs no code change in `s3_landing.py`, only AWS credentials and removing the `@mock_aws` decorator around the pipeline entry point.

Time-series storage is DuckDB, an embedded analytical database with columnar storage and SQL, so the schema design, indexing, and query-performance work run locally. A hosted time-series service (Timestream, InfluxDB Cloud) would be a drop-in target for the same schema.

## Results

`python3 -m src.pipeline` runs the full flow end to end:

- 32 raw objects uploaded, 1,482 raw records seen, 1,450 clean rows stored after deduplication (32 duplicates removed).
- The injected gap is found exactly where expected.
- Query-latency numbers are measured and printed, not hardcoded. On this ~1,450-row dataset the `(device_id, ts)` index gives a small speedup of roughly 1-8% across repeated runs, because DuckDB's planner already optimizes well at this data scale. At production IoT scale (millions of rows across many devices) the same indexing strategy would be expected to matter more; that is a reasoned expectation, not a measured number.

## Tests

`python3 -m pytest tests/ -v` runs 23 tests (23/23 passing), including:

- The dedup-overcollapse regression test (see Notes), confirmed to fail against the buggy version and pass against the fix.
- A data-integrity gap-detection test confirming the exact injected silent window is found, with no false positives on the two devices that do not have one.
- S3-landing tests against the real boto3 client API surface (bucket idempotency, upload/read roundtrip, prefix-filtered listing).

## Project structure

```
src/
  generate_telemetry.py
  s3_landing.py
  structure_timeseries.py
  pipeline.py
tests/
  test_generate_telemetry.py
  test_s3_landing.py
  test_structure_timeseries.py
  test_pipeline.py
requirements.txt
pytest.ini
```

## Running it

```bash
pip install -r requirements.txt
python3 -m src.pipeline      # full ingestion + gap detection + perf run
pytest tests/ -v              # 23 tests
```

## Notes

**A dedup bug caught during development.** An early version of the deduplication logic matched only on `(device_id, timestamp)` to decide whether an incoming reading was a duplicate. Two **different** sensor readings from the same device that arrive with the same timestamp (for example a corrected retransmission with a different value) would be silently collapsed into one row, discarding real data. A dedicated test (`test_duplicate_dedup_does_not_overcollapse_same_device_different_reading_same_timestamp`) was written to catch this and confirmed to **fail** against the `(device_id, ts)`-only version (2 distinct readings collapsed into 1 row) before the dedup key was fixed to match on every field. This is the same "verify dedup doesn't overcollapse" discipline used in `elt-selfservice-analytics`, applied to an IoT-specific dedup risk.

## Possible extensions

- Point `s3_landing.py` at a real AWS account and a hosted time-series database.
- Benchmark the index at larger synthetic scale (millions of rows).
- Add battery state-estimation modeling (for example Kalman filters) on top of the structured series.

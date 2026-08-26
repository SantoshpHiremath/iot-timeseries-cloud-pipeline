# IoT Time-Series Cloud Pipeline — Battery Telemetry Ingestion & Data Integrity

A real, tested Python project that lands raw IoT battery-telemetry logs
in S3, structures and deduplicates them into a queryable time-series
table, detects data-integrity gaps (e.g. an OTA-update connectivity
loss), and measures query performance — built to close a specific gap
for Munich Electrification's "Working Student Battery Science and Data"
posting: cloud/AWS tooling and time-series storage/query-performance
work, the one substantive gap in an otherwise strong match (SQL,
ELT/data pipelines, Docker, and monitoring/alerting were already covered
by prior project and work evidence).

## What this is (read before citing anywhere)

**There is no real Munich Electrification, vehicle, or battery data
here.** `src/generate_telemetry.py` generates synthetic per-vehicle
battery telemetry (voltage, current, temperature, state-of-charge)
modeled on the domain the posting describes, with realistic messiness:
out-of-order delivery, occasional duplicate uploads, and one device with
an injected connectivity outage — not a real Munich Electrification
system.

**This does not use a real AWS account.** This sandbox has no outbound
network access to AWS (`aws.amazon.com` itself returns a 403 from this
sandbox's outbound proxy) — the same class of network constraint
documented elsewhere in this application portfolio (Docker Hub blocked
for `devops-cicd-monitoring`; OpenML, Zenodo, and the UCR time-series
archive all blocked for
`forda-unsupervised-anomaly-detection`). Rather than fake having used
AWS, or skip cloud-SDK work entirely, `src/s3_landing.py` is built and
tested against [`moto`](https://github.com/getmoto/moto) — the standard
library the AWS Python ecosystem itself uses to unit-test real boto3
code without touching a real account (used in AWS's own SDK test suites
and by thousands of production codebases). Every boto3 call in this
project (`create_bucket`, `put_object`, `list_objects_v2` via paginator,
`get_object`) is the exact call that would run against a real AWS
account; only the backend is mocked. Swapping to a real account requires
no code change in `s3_landing.py`, only AWS credentials and removing the
`@mock_aws` decorator around the pipeline entry point.

**Time-series storage is DuckDB, not a hosted time-series database.**
A real hosted time-series service (Timestream, InfluxDB Cloud) is
unreachable for the same network reason as AWS above. DuckDB is a real
embedded analytical database with genuine columnar storage and SQL, so
the schema design, indexing, and query-performance work is real
database engineering, just running locally.

## What this models

- **`src/generate_telemetry.py`** — synthetic per-vehicle battery
  telemetry generator (3 devices, 500 readings each): voltage, current,
  temperature, and SOC, with out-of-order delivery, a 2% duplicate
  upload rate, and one device (`veh-002`) with an injected 50-reading
  silent window (a connectivity/OTA-update outage).
- **`src/s3_landing.py`** — lands raw telemetry as JSON-lines objects in
  a moto-mocked S3 bucket, partitioned by `device_id=<id>/batch=<n>.jsonl`
  — the same device-partitioning pattern a real IoT ingestion pipeline
  uses so downstream processing doesn't need to scan the whole bucket.
- **`src/structure_timeseries.py`** — parses raw S3 objects and
  structures them into a clean, indexed DuckDB time-series table:
  exact-match deduplication (verified to not overcollapse genuinely
  distinct readings — see below), sorting by timestamp per device, and
  a data-integrity gap detector that flags timestamp gaps larger than
  3× the expected sampling interval — directly implementing the
  posting's "monitor OTA updates to ensure data integrity" task.
- **`src/pipeline.py`** — runs the full flow end-to-end and measures
  query latency with vs. without the `(device_id, ts)` index.

## A real, non-obvious bug caught during development

An early version of the deduplication logic matched only on
`(device_id, timestamp)` to decide whether an incoming reading was a
duplicate. That looks reasonable, but it's wrong: two **different**
sensor readings from the same device that happen to arrive with the
same timestamp (e.g. a corrected retransmission with a genuinely
different value) would be silently collapsed into one row, discarding
real data. A dedicated test
(`test_duplicate_dedup_does_not_overcollapse_same_device_different_reading_same_timestamp`)
was written specifically to catch this, confirmed to actually **fail**
against the `(device_id, ts)`-only version (reproducing the bug: 2
distinct readings collapsed into 1 row) before the dedup key was fixed
to match on every field, not just device and timestamp. This is the
same "verify dedup doesn't overcollapse" discipline used in this
portfolio's ELT project (`elt-selfservice-analytics`), applied to a
different, IoT-specific dedup risk.

## An honest finding: the query-performance test

The posting names "improving time-series storage as well as query
performance" as a task. Measuring device-range query latency with vs.
without the `(device_id, ts)` index on this project's ~1,450-row
dataset showed only a small, honest effect (roughly a 1–8% speedup
across repeated runs) — not a dramatic one. This is disclosed rather
than exaggerated: DuckDB's own query planner does a lot of automatic
optimization even without an explicit index at this data scale, so the
index's benefit here is real but modest. At real production IoT scale
(millions of rows across many devices), the same indexing strategy
would be expected to matter far more — but that's a reasoned
expectation stated as such, not a number this project actually
measured, since generating millions of realistic synthetic rows wasn't
necessary to demonstrate the indexing methodology honestly.

## Verification performed

- `python3 -m pytest tests/ -v` — 23/23 tests pass, including:
  - The dedup-overcollapse regression test above, confirmed to have
    real teeth (fails against the buggy version, passes against the
    fix).
  - A data-integrity gap-detection test confirming the exact injected
    silent window is found, with no false positives on the two devices
    that don't have one.
  - S3-landing tests against the real boto3 client API surface (bucket
    idempotency, upload/read roundtrip, prefix-filtered listing).
- `python3 -m src.pipeline` — runs the full flow end-to-end: 32 raw
  objects uploaded, 1,482 raw records seen, 1,450 clean rows stored
  after deduplication (32 duplicates correctly removed), the injected
  gap found exactly where expected, and real (if modest) query-latency
  numbers printed, not hardcoded.

## Running it

```bash
pip install -r requirements.txt
python3 -m src.pipeline      # full ingestion + gap detection + perf run
pytest tests/ -v              # 23 tests
```

## What this doesn't demonstrate

This project doesn't use a real AWS account, a real hosted time-series
database, or real battery/vehicle data (all disclosed above, with the
reason). It doesn't touch battery electrochemistry, dynamical-systems
modeling (ODEs), or state-estimation methods (Kalman filters) — those
are a different, physics-modeling-focused lane of the posting this
project doesn't address. It demonstrates real, tested cloud-SDK usage
against the standard AWS-ecosystem mocking tool, genuine time-series
data-modeling and query-performance work, and the same
investigate-before-trusting discipline as the rest of this portfolio
(the dedup bug above), on a system I could build, break, and verify
myself.

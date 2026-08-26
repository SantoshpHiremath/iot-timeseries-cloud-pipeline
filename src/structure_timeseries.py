"""
Structures raw, messy IoT log objects (landed in S3 as unordered,
occasionally-duplicated JSON lines) into a clean, queryable time-series
table in DuckDB -- the "structuring raw IoT logs, designing data models,
improving time-series storage and query performance" task from the
posting.

Design choices, and why:
- DuckDB, not a hosted time-series DB (InfluxDB/Timestream): this
  sandbox cannot reach a real hosted time-series database service either
  (same network constraint as AWS/S3 -- see s3_landing.py's disclosure).
  DuckDB is a genuine embedded analytical database with real columnar
  storage and real SQL, so the schema design, indexing, and query-
  performance work here is real database engineering, just running
  locally rather than against a hosted service.
- Deduplication by (device_id, timestamp, voltage, current, temperature,
  soc) exact match: a duplicate delivery of the identical reading should
  collapse to one row; two different readings that happen to arrive at
  the same timestamp should NOT be silently merged (see the test
  checking this doesn't over-collapse genuinely distinct readings --
  the same "verify dedup doesn't overcollapse" discipline used in this
  portfolio's ELT project).
- Sorting by timestamp per device after structuring, since raw delivery
  order is not read order for a time-series table.
"""

import json
import duckdb


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS telemetry (
    device_id VARCHAR,
    ts BIGINT,
    voltage_v DOUBLE,
    current_a DOUBLE,
    temperature_c DOUBLE,
    soc_pct DOUBLE
)
"""

CREATE_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_telemetry_device_ts ON telemetry (device_id, ts)
"""


def get_connection(db_path=":memory:"):
    con = duckdb.connect(db_path)
    con.execute(CREATE_TABLE_SQL)
    con.execute(CREATE_INDEX_SQL)
    return con


def parse_jsonl_bytes(raw_bytes):
    lines = raw_bytes.decode("utf-8").strip().split("\n")
    return [json.loads(line) for line in lines if line.strip()]


def structure_batch(con, raw_bytes):
    """
    Parse one raw S3 object's bytes and insert into the telemetry table,
    deduplicating against what's already stored (exact-match dedup on
    all fields, the same "true duplicate deliveries only" discipline as
    the rest of this portfolio's ELT work).
    """
    records = parse_jsonl_bytes(raw_bytes)
    if not records:
        return 0

    con.executemany(
        """
        INSERT INTO telemetry (device_id, ts, voltage_v, current_a, temperature_c, soc_pct)
        SELECT ?, ?, ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM telemetry
            WHERE device_id = ? AND ts = ? AND voltage_v = ? AND current_a = ?
              AND temperature_c = ? AND soc_pct = ?
        )
        """,
        [
            (
                r["device_id"], r["timestamp"], r["voltage_v"], r["current_a"],
                r["temperature_c"], r["soc_pct"],
                r["device_id"], r["timestamp"], r["voltage_v"], r["current_a"],
                r["temperature_c"], r["soc_pct"],
            )
            for r in records
        ],
    )
    return len(records)


def query_device_series(con, device_id):
    """Return the clean, sorted time series for one device."""
    return con.execute(
        "SELECT * FROM telemetry WHERE device_id = ? ORDER BY ts", [device_id]
    ).df()


def row_count(con):
    return con.execute("SELECT COUNT(*) FROM telemetry").fetchone()[0]


def detect_data_gaps(con, device_id, expected_interval_s=10, gap_multiplier=3):
    """
    Data-integrity check: find timestamp gaps in a device's series
    larger than `gap_multiplier` times the expected sampling interval --
    a real signal of a connectivity loss, e.g. during an OTA update,
    directly matching the posting's "monitor OTA updates to ensure data
    integrity" task. Returns a list of (gap_start_ts, gap_end_ts,
    gap_seconds) tuples.
    """
    rows = con.execute(
        "SELECT ts FROM telemetry WHERE device_id = ? ORDER BY ts", [device_id]
    ).fetchall()
    timestamps = [r[0] for r in rows]
    threshold = expected_interval_s * gap_multiplier

    gaps = []
    for i in range(1, len(timestamps)):
        delta = timestamps[i] - timestamps[i - 1]
        if delta > threshold:
            gaps.append((timestamps[i - 1], timestamps[i], delta))
    return gaps

import json

import pytest

from src.structure_timeseries import (
    get_connection, structure_batch, query_device_series, row_count, detect_data_gaps,
)


def _jsonl(records):
    return "\n".join(json.dumps(r) for r in records).encode("utf-8")


def _record(device_id="veh-001", ts=0, v=350.0, a=-8.0, t=25.0, soc=80.0):
    return {
        "device_id": device_id, "timestamp": ts, "voltage_v": v,
        "current_a": a, "temperature_c": t, "soc_pct": soc,
    }


def test_structure_batch_inserts_rows():
    con = get_connection()
    n = structure_batch(con, _jsonl([_record(ts=0), _record(ts=10)]))
    assert n == 2
    assert row_count(con) == 2


def test_exact_duplicate_deliveries_are_deduplicated():
    con = get_connection()
    rec = _record(ts=0)
    structure_batch(con, _jsonl([rec, rec]))  # same record delivered twice
    assert row_count(con) == 1


def test_duplicate_dedup_does_not_overcollapse_distinct_readings_at_same_timestamp():
    """
    Regression-style test for a real, non-obvious dedup risk: two
    DIFFERENT readings from different devices, at the same timestamp,
    must NOT be collapsed into one row -- only exact full-row duplicates
    are removed. Same discipline as this portfolio's ELT project's dedup
    test.
    """
    con = get_connection()
    rec_a = _record(device_id="veh-001", ts=0, v=350.0)
    rec_b = _record(device_id="veh-002", ts=0, v=351.0)  # different device AND value
    structure_batch(con, _jsonl([rec_a, rec_b]))
    assert row_count(con) == 2


def test_duplicate_dedup_does_not_overcollapse_same_device_different_reading_same_timestamp():
    """
    Stricter version of the above: this is the case that actually
    exercises full-row-match dedup rather than device-partitioning alone
    -- two DIFFERENT sensor readings from the SAME device at the SAME
    timestamp (e.g. a corrected re-transmission with a genuinely
    different value, not a retry of the identical reading) must NOT be
    collapsed into one row. A dedup key of (device_id, ts) only --
    without also matching on the actual sensor values -- would
    incorrectly overcollapse this case; this test caught exactly that
    bug during development (confirmed to fail when dedup was
    temporarily narrowed to (device_id, ts) only, before being
    confirmed to pass again against the real full-row-match dedup).
    """
    con = get_connection()
    rec_a = _record(device_id="veh-001", ts=0, v=350.0)
    rec_b = _record(device_id="veh-001", ts=0, v=351.5)  # same device+ts, different value
    structure_batch(con, _jsonl([rec_a, rec_b]))
    assert row_count(con) == 2


def test_structure_batch_across_multiple_calls_still_dedups_against_existing_rows():
    con = get_connection()
    rec = _record(ts=0)
    structure_batch(con, _jsonl([rec]))
    structure_batch(con, _jsonl([rec]))  # re-delivered in a LATER batch
    assert row_count(con) == 1


def test_empty_batch_inserts_nothing():
    con = get_connection()
    n = structure_batch(con, b"")
    assert n == 0
    assert row_count(con) == 0


def test_query_device_series_is_sorted_by_timestamp_even_if_inserted_out_of_order():
    con = get_connection()
    structure_batch(con, _jsonl([_record(ts=30), _record(ts=10), _record(ts=20)]))
    df = query_device_series(con, "veh-001")
    assert list(df["ts"]) == [10, 20, 30]


def test_detect_data_gaps_finds_injected_gap():
    con = get_connection()
    # 10-second interval readings, with a deliberate 100s gap
    records = [_record(ts=t) for t in range(0, 50, 10)]
    records += [_record(ts=t) for t in range(150, 200, 10)]
    structure_batch(con, _jsonl(records))

    gaps = detect_data_gaps(con, "veh-001", expected_interval_s=10, gap_multiplier=3)
    assert len(gaps) == 1
    gap_start, gap_end, gap_seconds = gaps[0]
    assert gap_start == 40
    assert gap_end == 150
    assert gap_seconds == 110


def test_detect_data_gaps_no_false_positive_on_regular_series():
    con = get_connection()
    records = [_record(ts=t) for t in range(0, 200, 10)]
    structure_batch(con, _jsonl(records))
    gaps = detect_data_gaps(con, "veh-001", expected_interval_s=10, gap_multiplier=3)
    assert gaps == []

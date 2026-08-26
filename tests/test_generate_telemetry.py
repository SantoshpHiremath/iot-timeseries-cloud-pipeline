import numpy as np
import pytest

from src.generate_telemetry import (
    generate_device_log, generate_raw_upload_batches, DEVICE_IDS,
)


def test_generate_device_log_produces_expected_field_set():
    rng = np.random.default_rng(0)
    logs = generate_device_log(rng, "veh-001", n_points=50, duplicate_rate=0.0)
    assert len(logs) == 50
    for line in logs:
        assert set(line.keys()) == {
            "device_id", "timestamp", "voltage_v", "current_a",
            "temperature_c", "soc_pct",
        }


def test_silent_window_produces_no_log_lines_in_that_range():
    rng = np.random.default_rng(0)
    logs = generate_device_log(
        rng, "veh-002", n_points=300, silent_window=(100, 150), duplicate_rate=0.0
    )
    timestamps = sorted(l["timestamp"] for l in logs)
    # timestamps 1000..1490 (index*10) should be entirely absent
    silent_start_ts, silent_end_ts = 1000, 1500
    in_silent_range = [t for t in timestamps if silent_start_ts <= t < silent_end_ts]
    assert in_silent_range == []


def test_duplicate_rate_produces_some_duplicates_at_high_rate():
    rng = np.random.default_rng(0)
    logs = generate_device_log(rng, "veh-001", n_points=200, duplicate_rate=0.5)
    n_unique = len(set((l["timestamp"], l["voltage_v"]) for l in logs))
    assert n_unique < len(logs)  # some duplicates present


def test_generate_raw_upload_batches_covers_all_devices():
    batches, silent_windows = generate_raw_upload_batches(seed=1, n_points_per_device=50)
    assert set(batches.keys()) == set(DEVICE_IDS)
    assert "veh-002" in silent_windows


def test_deterministic_with_fixed_seed():
    b1, _ = generate_raw_upload_batches(seed=7, n_points_per_device=30)
    b2, _ = generate_raw_upload_batches(seed=7, n_points_per_device=30)
    assert b1 == b2

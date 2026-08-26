"""
Synthetic battery-pack IoT telemetry generator, shaped like real
in-vehicle logging data: per-device JSON log lines with a timestamp,
voltage, current, temperature, and state-of-charge (SOC) reading, plus
realistic messiness (out-of-order arrival, occasional duplicate
deliveries, and a device that goes silent for a window — the same class
of real-world IoT ingestion problems named in the posting: "structuring
raw IoT logs" and "ensure data integrity" during OTA deployments).

Not real Munich Electrification or vehicle data. Modeled on the domain
the posting describes (battery cell data, IoT logs, test-car
deployments) to build and honestly verify a real ingestion + storage +
integrity-monitoring pipeline against inspectable synthetic data.
"""

import json
import numpy as np

DEVICE_IDS = ["veh-001", "veh-002", "veh-003"]


def _simulate_soc_curve(rng, n_points, start_soc=None):
    """A slowly-discharging SOC curve with small noise, in [0, 100]."""
    start_soc = start_soc if start_soc is not None else rng.uniform(70, 95)
    drain_rate = rng.uniform(0.02, 0.08)
    soc = start_soc - np.cumsum(np.full(n_points, drain_rate)) + rng.normal(0, 0.15, n_points)
    return np.clip(soc, 5, 100)


def generate_device_log(rng, device_id, n_points=500, start_ts=0, interval_s=10,
                         duplicate_rate=0.02, silent_window=None):
    """
    Generate one device's raw telemetry as a list of dict log lines
    (this is what would land in S3 as raw JSON objects, one per
    upload batch, before any structuring/cleaning happens).

    silent_window: optional (start_idx, end_idx) range where this device
    stops reporting entirely, simulating a connectivity/OTA-update outage.
    """
    soc = _simulate_soc_curve(rng, n_points)
    logs = []
    for i in range(n_points):
        if silent_window and silent_window[0] <= i < silent_window[1]:
            continue  # device silent -- no log line at all

        ts = start_ts + i * interval_s
        voltage = 350 + 40 * (soc[i] / 100) + rng.normal(0, 1.5)
        current = rng.normal(-8, 3)  # negative = discharging
        temperature = 25 + rng.normal(0, 3) + max(0, -current) * 0.1

        line = {
            "device_id": device_id,
            "timestamp": ts,
            "voltage_v": round(float(voltage), 3),
            "current_a": round(float(current), 3),
            "temperature_c": round(float(temperature), 2),
            "soc_pct": round(float(soc[i]), 2),
        }
        logs.append(line)

        # Occasionally duplicate this exact log line (a common real IoT
        # bug: a retry after an ack timeout re-sends the same reading).
        if rng.random() < duplicate_rate:
            logs.append(dict(line))

    return logs


def generate_raw_upload_batches(seed=42, n_points_per_device=500):
    """
    Returns a dict {device_id: [log_line, ...]} simulating what would be
    uploaded to S3 as raw, unstructured JSON per device. One device
    (veh-002) has an injected silent window (rows 200-250) simulating an
    OTA-update connectivity gap -- the exact scenario the posting names
    ("monitor OTA updates to ensure data integrity").

    Also returns out-of-order versions of each device's log (shuffled
    within a bounded window) to simulate realistic out-of-order network
    delivery, which any real ingestion pipeline must handle.
    """
    rng = np.random.default_rng(seed)
    batches = {}
    silent_windows = {"veh-002": (200, 250)}

    for device_id in DEVICE_IDS:
        logs = generate_device_log(
            rng, device_id, n_points=n_points_per_device,
            silent_window=silent_windows.get(device_id),
        )
        # Simulate mild out-of-order delivery: shuffle within a small
        # sliding window rather than fully randomizing (network jitter,
        # not total chaos).
        logs = _locally_shuffle(rng, logs, window=5)
        batches[device_id] = logs

    return batches, silent_windows


def _locally_shuffle(rng, logs, window=5):
    logs = list(logs)
    n = len(logs)
    for start in range(0, n, window):
        end = min(start + window, n)
        chunk = logs[start:end]
        rng.shuffle(chunk)
        logs[start:end] = chunk
    return logs


def logs_to_jsonl_bytes(logs):
    return "\n".join(json.dumps(line) for line in logs).encode("utf-8")

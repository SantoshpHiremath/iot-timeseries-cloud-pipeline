from src.pipeline import run_pipeline, measure_query_performance


def test_pipeline_runs_end_to_end_and_dedups():
    con, results = run_pipeline(seed=42, batch_size=50)
    assert results["raw_records_seen"] > results["clean_rows_stored"]  # some dupes removed
    assert results["clean_rows_stored"] > 0


def test_pipeline_detects_injected_silent_window():
    con, results = run_pipeline(seed=42, batch_size=50)
    gaps = results["gaps_by_device"]["veh-002"]
    assert len(gaps) >= 1
    # the injected silent window is indices 200-250 at 10s spacing -> ts 2000-2500
    gap_start, gap_end, gap_seconds = gaps[0]
    assert 1900 <= gap_start <= 2050
    assert 2450 <= gap_end <= 2600


def test_pipeline_finds_no_gaps_on_devices_without_injected_outage():
    con, results = run_pipeline(seed=42, batch_size=50)
    assert results["gaps_by_device"]["veh-001"] == []
    assert results["gaps_by_device"]["veh-003"] == []


def test_query_performance_measurement_runs_and_returns_positive_times():
    con, results = run_pipeline(seed=42, batch_size=50)
    perf = measure_query_performance(con, n_repeats=20)
    assert perf["no_index_seconds"] > 0
    assert perf["with_index_seconds"] > 0


def test_pipeline_deterministic_row_count_given_seed():
    _, results1 = run_pipeline(seed=42, batch_size=50)
    _, results2 = run_pipeline(seed=42, batch_size=50)
    assert results1["clean_rows_stored"] == results2["clean_rows_stored"]

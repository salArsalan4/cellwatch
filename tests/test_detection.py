from common.detection import (
    EWMA_WARMUP_SAMPLES,
    Z_SCORE_THRESHOLD,
    check_sleeping_cell,
    check_thresholds,
    detect,
    update_ewma_and_check,
)
from common.kpi import KpiSample


def _sample(valid_kpi_payload, **overrides) -> KpiSample:
    return KpiSample(**dict(valid_kpi_payload, **overrides))


def test_check_thresholds_flags_high_call_drop_rate(valid_kpi_payload):
    sample = _sample(valid_kpi_payload, call_drop_rate=6.0)

    anomalies = check_thresholds(sample)

    assert any(a.kpi_name == "call_drop_rate" and a.severity == "critical" for a in anomalies)


def test_check_thresholds_flags_low_handover_success_rate(valid_kpi_payload):
    sample = _sample(valid_kpi_payload, handover_success_rate=80.0)

    anomalies = check_thresholds(sample)

    assert any(a.kpi_name == "handover_success_rate" for a in anomalies)


def test_check_thresholds_no_anomaly_for_normal_sample(valid_kpi_payload):
    sample = _sample(valid_kpi_payload)

    assert check_thresholds(sample) == []


def test_check_sleeping_cell_detects_pattern(valid_kpi_payload):
    sample = _sample(valid_kpi_payload, prb_utilization_dl=0.0, rrc_connected_users=0, dl_throughput_mbps=0.0)

    anomalies = check_sleeping_cell(sample)

    assert len(anomalies) == 1
    assert anomalies[0].alert_type == "sleeping_cell"
    assert anomalies[0].severity == "critical"


def test_check_sleeping_cell_requires_all_conditions(valid_kpi_payload):
    # Low utilization alone (still serving some users) isn't a sleeping cell.
    sample = _sample(valid_kpi_payload, prb_utilization_dl=0.0, rrc_connected_users=5, dl_throughput_mbps=0.0)

    assert check_sleeping_cell(sample) == []


def test_ewma_no_anomaly_during_warmup(valid_kpi_payload):
    stats = {}
    for _ in range(EWMA_WARMUP_SAMPLES - 1):
        sample = _sample(valid_kpi_payload, rsrp_dbm=-95.0)
        stats, anomalies = update_ewma_and_check(sample, stats)
        assert anomalies == []


def test_ewma_detects_outlier_after_warmup(valid_kpi_payload):
    stats = {}
    for _ in range(EWMA_WARMUP_SAMPLES + 5):
        sample = _sample(valid_kpi_payload, rsrp_dbm=-95.0)
        stats, _ = update_ewma_and_check(sample, stats)

    outlier = _sample(valid_kpi_payload, rsrp_dbm=-140.0)
    _, anomalies = update_ewma_and_check(outlier, stats)

    assert any(a.kpi_name == "rsrp_dbm" and a.alert_type == "zscore" for a in anomalies)


def test_ewma_stable_series_never_flags_itself(valid_kpi_payload):
    stats = {}
    for _ in range(30):
        sample = _sample(valid_kpi_payload, rsrp_dbm=-95.0)
        stats, anomalies = update_ewma_and_check(sample, stats)
        assert anomalies == []


def test_detect_combines_threshold_and_sleeping_cell(valid_kpi_payload):
    sample = _sample(
        valid_kpi_payload,
        prb_utilization_dl=0.0,
        rrc_connected_users=0,
        dl_throughput_mbps=0.0,
        call_drop_rate=10.0,
    )

    _, anomalies = detect(sample, {})

    alert_types = {a.alert_type for a in anomalies}
    assert "sleeping_cell" in alert_types
    assert "threshold" in alert_types


def test_z_score_threshold_is_reasonably_strict():
    # Sanity check on the constant itself -- not "does 3.0 work" (covered
    # above) but that nobody accidentally drops it to something noisy.
    assert Z_SCORE_THRESHOLD >= 2.5

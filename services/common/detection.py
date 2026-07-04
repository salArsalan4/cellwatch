"""Threshold + EWMA/z-score anomaly detection for incoming KPI samples.

Threshold-based here means a small set of hardcoded defaults, not the
RDS-backed per-cell thresholds from services/query's admin CRUD API. That
API governs what's *visible/editable*; wiring it into this hot path would
mean the ingest path needs RDS reachability, which the architecture
deliberately avoids (see docs/OVERVIEW.md §5 and services/processor's
module docstring). A reasonable stretch item, not a silent gap.

Statistical detection keeps its state (running EWMA mean/variance per
cell+KPI) entirely in DynamoDB, so -- like the threshold check -- it never
needs RDS either.
"""

import math
from dataclasses import dataclass

from common.kpi import KpiSample

# kpi_name -> (min, max, severity). None means "no bound on that side."
THRESHOLDS: dict[str, tuple[float | None, float | None, str]] = {
    "call_drop_rate": (None, 5.0, "critical"),
    "prb_utilization_dl": (None, 95.0, "warning"),
    "prb_utilization_ul": (None, 95.0, "warning"),
    "handover_success_rate": (85.0, None, "warning"),
    "rsrp_dbm": (-110.0, None, "warning"),
    "sinr_db": (-5.0, None, "warning"),
}

EWMA_TRACKED_KPIS = ("rsrp_dbm", "sinr_db", "call_drop_rate", "dl_throughput_mbps", "prb_utilization_dl")
EWMA_ALPHA = 0.1
EWMA_WARMUP_SAMPLES = 5
Z_SCORE_THRESHOLD = 3.0
# Floor, not a "skip the check" cutoff: a history that's been perfectly
# constant (var == 0) is exactly the case where any deviation matters most,
# not a reason to suppress detection. Flooring keeps z-score computable
# (avoids a literal division by zero) while still flagging that case.
Z_SCORE_MIN_VARIANCE = 1e-6


@dataclass
class Anomaly:
    kpi_name: str
    value: float
    alert_type: str  # "threshold" | "sleeping_cell" | "zscore"
    severity: str


def check_thresholds(sample: KpiSample) -> list[Anomaly]:
    anomalies = []
    for kpi_name, (lo, hi, severity) in THRESHOLDS.items():
        value = getattr(sample, kpi_name)
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            anomalies.append(Anomaly(kpi_name, value, "threshold", severity))
    return anomalies


def check_sleeping_cell(sample: KpiSample) -> list[Anomaly]:
    # Composite pattern, not a single-KPI threshold: near-zero utilization,
    # zero connected users, and near-zero throughput together indicate a
    # cell that's technically reporting but not actually serving traffic.
    if sample.prb_utilization_dl < 1.0 and sample.rrc_connected_users == 0 and sample.dl_throughput_mbps < 1.0:
        return [Anomaly("prb_utilization_dl", sample.prb_utilization_dl, "sleeping_cell", "critical")]
    return []


def update_ewma_and_check(sample: KpiSample, stats: dict) -> tuple[dict, list[Anomaly]]:
    """stats is the cell's current {kpi_name: {"mean", "var", "n"}} dict
    (missing entries are treated as cold start). Returns the updated stats
    dict for the caller to persist, plus any z-score anomalies found."""
    anomalies = []
    updated = dict(stats)

    for kpi_name in EWMA_TRACKED_KPIS:
        value = float(getattr(sample, kpi_name))
        prior = stats.get(kpi_name, {"mean": value, "var": 0.0, "n": 0})
        mean, var, n = float(prior["mean"]), float(prior["var"]), int(prior["n"])

        if n >= EWMA_WARMUP_SAMPLES:
            z = (value - mean) / math.sqrt(max(var, Z_SCORE_MIN_VARIANCE))
            if abs(z) > Z_SCORE_THRESHOLD:
                anomalies.append(Anomaly(kpi_name, value, "zscore", "warning"))

        diff = value - mean
        new_mean = mean + EWMA_ALPHA * diff
        new_var = (1 - EWMA_ALPHA) * (var + EWMA_ALPHA * diff * diff)
        updated[kpi_name] = {"mean": new_mean, "var": new_var, "n": n + 1}

    return updated, anomalies


def detect(sample: KpiSample, stats: dict) -> tuple[dict, list[Anomaly]]:
    updated_stats, zscore_anomalies = update_ewma_and_check(sample, stats)
    anomalies = check_sleeping_cell(sample) + check_thresholds(sample) + zscore_anomalies
    return updated_stats, anomalies

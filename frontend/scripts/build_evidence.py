#!/usr/bin/env python3
"""Builds frontend/evidence/*.json — the static fallback the dashboard falls
back to once the Learner Lab account is gone (or whenever live mode isn't
configured). Two modes write the exact same four files, so the frontend's
static-mode loader doesn't care which one produced them:

  --mode synthetic   Simulates a small fleet locally, reusing the real
                      generator (generator.cells) and the real detector
                      (services.common.detection) — no AWS needed. Lets the
                      dashboard be built and demoed before real evidence is
                      captured, or after the account is decommissioned.
  --mode live        Captures a real snapshot from the deployed query API —
                      this is the "capture demo evidence" step. Requires
                      --base-url and --api-key (see infra output query_url /
                      query_api_key_id).

Run from the repo root: uv run python frontend/scripts/build_evidence.py --mode synthetic
"""

import argparse
import json
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "services"))
sys.path.insert(0, str(REPO_ROOT / "generator"))

from cells import CellState, Mode  # noqa: E402
from common.detection import check_sleeping_cell, check_thresholds  # noqa: E402

EVIDENCE_DIR = Path(__file__).resolve().parent.parent / "evidence"

# Mirrors services/migrate/handler.py's SEED_CELLS convention so synthetic
# evidence looks like a real demo seed, not made-up data.
NUM_CELLS = 8
ROUNDS = 40
INTERVAL_MS = 60_000

# (cell index, anomaly mode, round the anomaly window starts, rounds it lasts)
# Chosen so the run ends with one still-active alert (index 2, ends at round
# 40) and one already-cleared one (index 5, ends at round 34) — the static
# evidence should show both states, not just "everything is currently red".
FORCED_ANOMALIES = [
    (2, Mode.CONGESTED, 33, 8),
    (5, Mode.DEGRADED, 24, 8),
    (7, Mode.SLEEPING, 15, 6),
]


def _iso(timestamp_ms: int) -> str:
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat()


def build_synthetic(seed: int) -> dict:
    random.seed(seed)
    now_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    start_ms = now_ms - ROUNDS * INTERVAL_MS

    cells = [
        {
            "id": f"CELL-{i:04d}",
            "site": f"Site-{i // 4:03d}",
            "latitude": None,
            "longitude": None,
            "band": "n78",
            "sector": (i % 4) + 1,
            "status": "active",
        }
        for i in range(NUM_CELLS)
    ]
    states = {c["id"]: CellState.new(c["id"]) for c in cells}
    forced = {idx: (mode, start, dur) for idx, mode, start, dur in FORCED_ANOMALIES}

    kpis: dict[str, list[dict]] = {c["id"]: [] for c in cells}
    # (cell_id, kpi_name, alert_type) -> alert dict, so repeated detections
    # within one anomaly window collapse into a single open/close alert
    # instead of one row per sample (matching how a NOC would actually see it).
    open_alerts: dict[tuple[str, str, str], dict] = {}
    closed_alerts: list[dict] = []
    next_alert_id = 1

    for round_idx in range(ROUNDS):
        ts = start_ms + round_idx * INTERVAL_MS
        for i, cell in enumerate(cells):
            cell_id = cell["id"]
            state = states[cell_id]

            if i in forced:
                mode, start_round, duration = forced[i]
                if round_idx == start_round:
                    state.mode = mode
                    state.mode_rounds_left = duration + 1  # see generator/cells.py step() decrement-then-apply order

            sample = state.step(ts, anomaly_rate=0.0)
            kpis[cell_id].append(sample.model_dump() | {"pk": f"CELL#{cell_id}", "sk": f"TS#{ts}"})

            anomalies = check_thresholds(sample) + check_sleeping_cell(sample)
            still_anomalous = {(cell_id, a.kpi_name, a.alert_type) for a in anomalies}
            for key in list(open_alerts):
                if key[0] == cell_id and key not in still_anomalous:
                    alert = open_alerts.pop(key)
                    alert["cleared_at"] = _iso(ts)
                    closed_alerts.append(alert)
            for a in anomalies:
                key = (cell_id, a.kpi_name, a.alert_type)
                if key not in open_alerts:
                    alert_id = next_alert_id
                    next_alert_id += 1
                    open_alerts[key] = {
                        "id": alert_id,
                        "cell_id": cell_id,
                        "kpi_name": a.kpi_name,
                        "value": a.value,
                        "alert_type": a.alert_type,
                        "severity": a.severity,
                        "opened_at": _iso(ts),
                        "cleared_at": None,
                    }

    for cell_id, samples in kpis.items():
        samples.reverse()  # newest first, matching GET /cells/{id}/kpis

    all_alerts = sorted(closed_alerts + list(open_alerts.values()), key=lambda a: a["opened_at"], reverse=True)

    health = {}
    for cell in cells:
        cell_id = cell["id"]
        latest = kpis[cell_id][0]
        active = [a for a in all_alerts if a["cell_id"] == cell_id and a["cleared_at"] is None]
        health[cell_id] = {
            "cell_id": cell_id,
            "latest_kpi": latest,
            "active_alert_count": len(active),
            "active_alerts": active,
            "status": "degraded" if active else "healthy",
        }

    meta = {
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
        "synthetic": True,
        "source": "synthetic-generator",
        "note": (
            "Placeholder evidence generated locally with generator.cells + "
            "services/common/detection.py — not a real deployment capture. "
            "Regenerate against the live API with --mode live before the "
            "Learner Lab account is torn down."
        ),
    }
    return {"meta": meta, "cells": cells, "kpis": kpis, "alerts": all_alerts, "health": health}


def build_live(base_url: str, api_key: str, limit: int) -> dict:
    import httpx

    headers = {"x-api-key": api_key}
    with httpx.Client(base_url=base_url.rstrip("/") + "/", headers=headers, timeout=30.0) as client:
        cells = client.get("cells").raise_for_status().json()
        alerts = client.get("alerts", params={"active": "false"}).raise_for_status().json()

        kpis, health = {}, {}
        for cell in cells:
            cell_id = cell["id"]
            kpis[cell_id] = client.get(f"cells/{cell_id}/kpis", params={"limit": limit}).raise_for_status().json()
            health[cell_id] = client.get(f"cells/{cell_id}/health").raise_for_status().json()

    meta = {
        "captured_at": datetime.now(tz=timezone.utc).isoformat(),
        "synthetic": False,
        "source": urljoin(base_url, "/"),
        "note": "Captured from the live CellWatch deployment.",
    }
    return {"meta": meta, "cells": cells, "kpis": kpis, "alerts": alerts, "health": health}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mode", choices=["synthetic", "live"], required=True)
    parser.add_argument("--seed", type=int, default=42, help="Synthetic mode: RNG seed for reproducible evidence")
    parser.add_argument("--base-url", help="Live mode: query API base URL (infra output query_url)")
    parser.add_argument("--api-key", help="Live mode: query API key value")
    parser.add_argument("--limit", type=int, default=60, help="Live mode: KPI samples per cell to capture")
    parser.add_argument("--out-dir", type=Path, default=EVIDENCE_DIR)
    args = parser.parse_args()

    if args.mode == "synthetic":
        data = build_synthetic(args.seed)
    else:
        if not args.base_url or not args.api_key:
            parser.error("--mode live requires --base-url and --api-key")
        data = build_live(args.base_url, args.api_key, args.limit)

    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("meta", "cells", "kpis", "alerts", "health"):
        (args.out_dir / f"{name}.json").write_text(json.dumps(data[name], indent=2) + "\n")

    print(f"Wrote {args.mode} evidence to {args.out_dir} ({len(data['cells'])} cells, {len(data['alerts'])} alerts)")


if __name__ == "__main__":
    main()

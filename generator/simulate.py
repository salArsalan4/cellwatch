#!/usr/bin/env python3
"""Simulated cell-site KPI generator.

Posts one KPI sample per cell per interval to the ingest API over the same
HTTPS + JSON contract a real OSS northbound feed would use (see
docs/OVERVIEW.md §1). Requests within a round are spread across the
interval (jitter) rather than fired all at once, approximating how 1,000
independent cell agents would actually report.

Usage:
    uv run python generator/simulate.py --endpoint https://.../kpi --api-key XXX
    uv run python generator/simulate.py --endpoint http://localhost:3000/kpi --cells 20 --rounds 1
"""

import argparse
import asyncio
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "services"))

import httpx

from cells import CellState  # noqa: E402


async def _post_one(client: httpx.AsyncClient, url: str, headers: dict, cell: CellState, timestamp_ms: int, anomaly_rate: float, stats: dict) -> None:
    sample = cell.step(timestamp_ms, anomaly_rate)
    try:
        resp = await client.post(url, json=sample.model_dump(), headers=headers)
        if resp.status_code == 202:
            stats["ok"] += 1
        else:
            stats["rejected"] += 1
            print(f"[{cell.cell_id}] unexpected status {resp.status_code}: {resp.text[:200]}", file=sys.stderr)
    except httpx.HTTPError as exc:
        stats["errors"] += 1
        print(f"[{cell.cell_id}] request failed: {exc}", file=sys.stderr)


async def _run_round(client: httpx.AsyncClient, url: str, headers: dict, cells: list[CellState], interval: float, anomaly_rate: float, concurrency: int, stats: dict) -> None:
    semaphore = asyncio.Semaphore(concurrency)

    async def _task(cell: CellState) -> None:
        await asyncio.sleep(random.uniform(0, interval * 0.9))
        async with semaphore:
            await _post_one(client, url, headers, cell, int(time.time() * 1000), anomaly_rate, stats)

    await asyncio.gather(*(_task(cell) for cell in cells))


async def main() -> None:
    parser = argparse.ArgumentParser(description="CellWatch simulated cell-site KPI generator")
    parser.add_argument("--endpoint", required=True, help="Ingest API URL, e.g. https://.../kpi")
    parser.add_argument("--api-key", default=None, help="x-api-key header value")
    parser.add_argument("--cells", type=int, default=1000, help="Number of simulated cells")
    parser.add_argument("--interval", type=float, default=60.0, help="Seconds between rounds per cell")
    parser.add_argument("--rounds", type=int, default=0, help="Number of rounds to run (0 = forever)")
    parser.add_argument("--concurrency", type=int, default=50, help="Max in-flight HTTP requests")
    parser.add_argument("--anomaly-rate", type=float, default=0.0, help="Per-cell, per-round probability of entering an anomaly mode")
    parser.add_argument("--seed", type=int, default=None, help="Random seed for reproducible runs")
    args = parser.parse_args()

    if args.seed is not None:
        random.seed(args.seed)

    cells = [CellState.new(f"CELL-{i:04d}") for i in range(args.cells)]
    headers = {"x-api-key": args.api_key} if args.api_key else {}

    round_num = 0
    async with httpx.AsyncClient(timeout=10.0) as client:
        while args.rounds == 0 or round_num < args.rounds:
            round_num += 1
            stats = {"ok": 0, "rejected": 0, "errors": 0}
            started = time.monotonic()

            await _run_round(client, args.endpoint, headers, cells, args.interval, args.anomaly_rate, args.concurrency, stats)

            elapsed = time.monotonic() - started
            print(f"round {round_num}: sent={len(cells)} ok={stats['ok']} rejected={stats['rejected']} errors={stats['errors']} elapsed={elapsed:.1f}s")

            remaining = args.interval - elapsed
            if remaining > 0 and (args.rounds == 0 or round_num < args.rounds):
                await asyncio.sleep(remaining)


if __name__ == "__main__":
    asyncio.run(main())

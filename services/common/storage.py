"""DynamoDB item mapping and S3 key layout for KPI samples.

DynamoDB table key schema (see infra, table created in Phase 1/2) must be
`pk` (HASH, string) / `sk` (RANGE, string) to match to_ddb_item below —
PK = CELL#<cell_id>, SK = TS#<epoch_ms> per docs/OVERVIEW.md §5.3.
"""

import json
import time
from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from common.kpi import KpiSample

DDB_TTL_SECONDS = 7 * 24 * 60 * 60


def to_ddb_item(sample: KpiSample) -> dict:
    # boto3's DynamoDB resource rejects native float (wants Decimal); round-trip
    # through JSON with parse_float=Decimal rather than hand-walking every field.
    item = json.loads(sample.model_dump_json(), parse_float=Decimal)
    item["pk"] = f"CELL#{sample.cell_id}"
    item["sk"] = f"TS#{sample.timestamp}"
    item["ttl"] = int(time.time()) + DDB_TTL_SECONDS
    return item


def from_ddb_item(value):
    # Inverse of the Decimal round-trip in to_ddb_item. Needed because
    # Powertools' response JSON encoder stringifies Decimal (to avoid
    # precision loss on arbitrary values) rather than returning a number --
    # fine for round-tripping into DynamoDB, bad for an API response. Our
    # KPI values are all bounded, ordinary floats/ints, so it's safe to
    # convert back to native types before they ever reach the encoder.
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    if isinstance(value, dict):
        return {k: from_ddb_item(v) for k, v in value.items()}
    if isinstance(value, list):
        return [from_ddb_item(v) for v in value]
    return value


def raw_archive_key(sample: KpiSample) -> str:
    dt = datetime.fromtimestamp(sample.timestamp / 1000, tz=timezone.utc).strftime("%Y-%m-%d")
    return f"raw/dt={dt}/cell={sample.cell_id}/{sample.timestamp}-{uuid4().hex}.json"


STATS_SORT_KEY = "STATS"


def stats_key(cell_id: str) -> dict:
    return {"pk": f"CELL#{cell_id}", "sk": STATS_SORT_KEY}


def to_stats_item(cell_id: str, stats: dict) -> dict:
    # No TTL: unlike hot KPI points, running EWMA state should persist for
    # as long as the cell is active, not expire after 7 days.
    item = json.loads(json.dumps(stats), parse_float=Decimal)
    item.update(stats_key(cell_id))
    return item

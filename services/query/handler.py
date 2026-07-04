"""Query/admin API: cell inventory, thresholds, alert history (RDS) and KPI
reads (DynamoDB). One Lambda behind API Gateway's {proxy+} ANY integration,
routed internally by Powertools' resolver — one Terraform integration
instead of one per endpoint. VPC-bound (see docs/OVERVIEW.md §5.4).
"""

import os
from datetime import date, datetime

import boto3
import psycopg2
from aws_lambda_powertools.event_handler import APIGatewayRestResolver, CORSConfig
from aws_lambda_powertools.event_handler.exceptions import BadRequestError, NotFoundError, ServiceUnavailableError
from aws_lambda_powertools.utilities.typing import LambdaContext
from psycopg2.extras import RealDictCursor

from common.config import require_env
from common.db import get_connection
from common.logging import get_logger, get_metrics, get_tracer
from common.storage import from_ddb_item

logger = get_logger("query")
metrics = get_metrics("query")
tracer = get_tracer()
# The static dashboard frontend calls this API directly from the browser
# (no server-side proxy — see frontend/README.md), so the browser-visible
# response needs CORS headers. Preflight OPTIONS is handled by API Gateway
# itself (a MOCK integration ahead of the api_key_required proxy methods —
# see infra/modules/control-plane/api_gateway.tf) since a preflight request
# never carries the x-api-key header. This CORSConfig only covers the actual
# GET/ANY responses that do reach the Lambda.
app = APIGatewayRestResolver(cors=CORSConfig(allow_origin=os.environ.get("CORS_ALLOW_ORIGIN", "*")))

_dynamodb = boto3.resource("dynamodb")

_CELL_FIELDS = {"site", "latitude", "longitude", "band", "sector", "status"}


# Global fallback for any route that doesn't handle an RDS outage itself
# (cell_health below is the one exception -- it degrades to DynamoDB-only
# instead of failing outright, per docs/OVERVIEW.md §7.3: "reads fall back
# to DynamoDB-only if cache or RDS is down"). Everything else here reads or
# writes RDS as its only data source, so there's no fallback data to serve
# -- the graceful part is returning a clear 503 instead of an opaque 500.
@app.exception_handler(psycopg2.OperationalError)
def handle_rds_unavailable(ex: psycopg2.OperationalError):
    logger.exception("rds_unavailable")
    raise ServiceUnavailableError("RDS is temporarily unavailable")


def _normalize(row: dict) -> dict:
    # psycopg2 returns Decimal only for NUMERIC columns (none here) and
    # datetime for TIMESTAMPTZ; Powertools' response encoder handles
    # Decimal but not datetime, so normalize it here once.
    return {k: (v.isoformat() if isinstance(v, (datetime, date)) else v) for k, v in row.items()}


def _rows(cur) -> list[dict]:
    return [_normalize(row) for row in cur.fetchall()]


def _kpi_table():
    return _dynamodb.Table(require_env("KPI_TABLE_NAME"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/cells")
def list_cells():
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cells ORDER BY id")
        return _rows(cur)


@app.post("/cells")
def create_cell():
    body = app.current_event.json_body
    if "id" not in body or "site" not in body:
        raise BadRequestError("id and site are required")
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO cells (id, site, latitude, longitude, band, sector, status)
            VALUES (%(id)s, %(site)s, %(latitude)s, %(longitude)s, %(band)s, %(sector)s,
                    COALESCE(%(status)s, 'active'))
            RETURNING *
            """,
            {field: body.get(field) for field in ("id", "site", "latitude", "longitude", "band", "sector", "status")},
        )
        conn.commit()
        return _rows(cur)[0]


@app.get("/cells/<cell_id>")
def get_cell(cell_id: str):
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("SELECT * FROM cells WHERE id = %s", (cell_id,))
        row = cur.fetchone()
        if row is None:
            raise NotFoundError(f"Cell {cell_id} not found")
        return _normalize(row)


@app.put("/cells/<cell_id>")
def update_cell(cell_id: str):
    body = app.current_event.json_body
    fields = {k: v for k, v in body.items() if k in _CELL_FIELDS}
    if not fields:
        raise BadRequestError(f"No updatable fields provided; allowed: {sorted(_CELL_FIELDS)}")
    set_clause = ", ".join(f"{k} = %({k})s" for k in fields)
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"UPDATE cells SET {set_clause} WHERE id = %(id)s RETURNING *",
            {**fields, "id": cell_id},
        )
        row = cur.fetchone()
        if row is None:
            raise NotFoundError(f"Cell {cell_id} not found")
        conn.commit()
        return _normalize(row)


@app.delete("/cells/<cell_id>")
def delete_cell(cell_id: str):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM cells WHERE id = %s", (cell_id,))
        deleted = cur.rowcount
        conn.commit()
        if deleted == 0:
            raise NotFoundError(f"Cell {cell_id} not found")
        return {"status": "deleted"}


@app.get("/cells/<cell_id>/kpis")
def cell_kpi_history(cell_id: str):
    params = app.current_event.query_string_parameters or {}
    limit = int(params.get("limit", 100))
    query_kwargs = {
        "KeyConditionExpression": "pk = :pk",
        "ExpressionAttributeValues": {":pk": f"CELL#{cell_id}"},
        "ScanIndexForward": False,  # newest first
        "Limit": limit,
    }
    if "from" in params or "to" in params:
        lo = f"TS#{params.get('from', '0')}"
        hi = f"TS#{params.get('to', '9' * 13)}"
        query_kwargs["KeyConditionExpression"] += " AND sk BETWEEN :lo AND :hi"
        query_kwargs["ExpressionAttributeValues"].update({":lo": lo, ":hi": hi})

    response = _kpi_table().query(**query_kwargs)
    return from_ddb_item(response.get("Items", []))


@app.get("/cells/<cell_id>/health")
def cell_health(cell_id: str):
    kpi_response = _kpi_table().query(
        KeyConditionExpression="pk = :pk",
        ExpressionAttributeValues={":pk": f"CELL#{cell_id}"},
        ScanIndexForward=False,
        Limit=1,
    )
    latest_items = kpi_response.get("Items", [])
    latest = from_ddb_item(latest_items[0]) if latest_items else None

    try:
        with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM alerts WHERE cell_id = %s AND cleared_at IS NULL ORDER BY opened_at DESC",
                (cell_id,),
            )
            active_alerts = _rows(cur)
    except psycopg2.OperationalError:
        # DynamoDB-derived data (latest_kpi) is still meaningful on its own;
        # degrade to that rather than failing the whole request over an
        # RDS outage that has nothing to do with telemetry health.
        logger.exception("rds_unavailable_degrading_to_dynamodb_only", cell_id=cell_id)
        return {
            "cell_id": cell_id,
            "latest_kpi": latest,
            "active_alert_count": None,
            "active_alerts": None,
            "status": "unknown",
            "degraded": True,
            "degraded_reason": "RDS unavailable; alert data omitted",
        }

    return {
        "cell_id": cell_id,
        "latest_kpi": latest,
        "active_alert_count": len(active_alerts),
        "active_alerts": active_alerts,
        "status": "degraded" if active_alerts else "healthy",
    }


@app.get("/thresholds")
def list_thresholds():
    cell_id = (app.current_event.query_string_parameters or {}).get("cell_id")
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if cell_id:
            cur.execute("SELECT * FROM thresholds WHERE cell_id = %s ORDER BY id", (cell_id,))
        else:
            cur.execute("SELECT * FROM thresholds ORDER BY id")
        return _rows(cur)


@app.post("/thresholds")
def create_threshold():
    body = app.current_event.json_body
    if "cell_id" not in body or "kpi_name" not in body:
        raise BadRequestError("cell_id and kpi_name are required")
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            """
            INSERT INTO thresholds (cell_id, kpi_name, min_value, max_value, severity)
            VALUES (%(cell_id)s, %(kpi_name)s, %(min_value)s, %(max_value)s, COALESCE(%(severity)s, 'warning'))
            ON CONFLICT (cell_id, kpi_name) DO UPDATE
                SET min_value = EXCLUDED.min_value, max_value = EXCLUDED.max_value, severity = EXCLUDED.severity
            RETURNING *
            """,
            {field: body.get(field) for field in ("cell_id", "kpi_name", "min_value", "max_value", "severity")},
        )
        conn.commit()
        return _rows(cur)[0]


@app.delete("/thresholds/<threshold_id>")
def delete_threshold(threshold_id: str):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM thresholds WHERE id = %s", (threshold_id,))
        deleted = cur.rowcount
        conn.commit()
        if deleted == 0:
            raise NotFoundError(f"Threshold {threshold_id} not found")
        return {"status": "deleted"}


@app.get("/alerts")
def list_alerts():
    active_only = (app.current_event.query_string_parameters or {}).get("active", "true") != "false"
    with get_connection() as conn, conn.cursor(cursor_factory=RealDictCursor) as cur:
        if active_only:
            cur.execute("SELECT * FROM alerts WHERE cleared_at IS NULL ORDER BY opened_at DESC")
        else:
            cur.execute("SELECT * FROM alerts ORDER BY opened_at DESC")
        return _rows(cur)


@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    return app.resolve(event, context)

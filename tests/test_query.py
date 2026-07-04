import json

import boto3
import psycopg2
from moto import mock_aws

from common.kpi import KpiSample
from common.storage import to_ddb_item
from query.handler import handler as query_handler


def _event(method: str, path: str, body=None, query=None, headers=None) -> dict:
    return {
        "httpMethod": method,
        "path": path,
        "resource": path,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "multiValueHeaders": {},
        "queryStringParameters": query,
        "pathParameters": None,
        "body": json.dumps(body) if body is not None else None,
        "isBase64Encoded": False,
        "requestContext": {"resourcePath": path, "httpMethod": method, "path": path, "stage": "test"},
    }


def _call(method, path, lambda_context, body=None, query=None):
    response = query_handler(_event(method, path, body=body, query=query), lambda_context)
    parsed_body = json.loads(response["body"]) if response.get("body") else None
    return response["statusCode"], parsed_body


def test_health(clean_db, lambda_context):
    status, body = _call("GET", "/health", lambda_context)
    assert status == 200
    assert body == {"status": "ok"}


def test_cors_header_present_for_browser_origin(clean_db, lambda_context):
    # The static dashboard (frontend/) calls this API directly from the
    # browser, so a request carrying an Origin header must get back an
    # Access-Control-Allow-Origin the browser will accept -- see
    # infra/modules/control-plane/api_gateway.tf for the OPTIONS-preflight
    # half of this (handled by API Gateway, not exercised here).
    event = _event("GET", "/health", headers={"Origin": "https://cellwatch.pages.dev"})
    response = query_handler(event, lambda_context)
    assert response["statusCode"] == 200
    assert response["multiValueHeaders"]["Access-Control-Allow-Origin"] == ["*"]


def test_create_list_get_update_delete_cell(clean_db, lambda_context):
    status, created = _call("POST", "/cells", lambda_context, body={"id": "CELL-9000", "site": "Site-Test"})
    assert status == 200
    assert created["id"] == "CELL-9000"
    assert created["status"] == "active"

    status, listed = _call("GET", "/cells", lambda_context)
    assert status == 200
    assert [c["id"] for c in listed] == ["CELL-9000"]

    status, fetched = _call("GET", "/cells/CELL-9000", lambda_context)
    assert status == 200
    assert fetched["site"] == "Site-Test"

    status, updated = _call("PUT", "/cells/CELL-9000", lambda_context, body={"status": "maintenance"})
    assert status == 200
    assert updated["status"] == "maintenance"

    status, _ = _call("DELETE", "/cells/CELL-9000", lambda_context)
    assert status == 200

    status, _ = _call("GET", "/cells/CELL-9000", lambda_context)
    assert status == 404


def test_get_missing_cell_is_404(clean_db, lambda_context):
    status, body = _call("GET", "/cells/NOPE", lambda_context)
    assert status == 404


def test_create_cell_missing_required_field_is_400(clean_db, lambda_context):
    status, _ = _call("POST", "/cells", lambda_context, body={"site": "Site-Test"})
    assert status == 400


def test_threshold_crud(clean_db, lambda_context):
    _call("POST", "/cells", lambda_context, body={"id": "CELL-9001", "site": "Site-Test"})

    status, created = _call(
        "POST",
        "/thresholds",
        lambda_context,
        body={"cell_id": "CELL-9001", "kpi_name": "call_drop_rate", "min_value": 0, "max_value": 5},
    )
    assert status == 200
    assert created["severity"] == "warning"

    status, listed = _call("GET", "/thresholds", lambda_context, query={"cell_id": "CELL-9001"})
    assert status == 200
    assert len(listed) == 1

    status, _ = _call("DELETE", f"/thresholds/{listed[0]['id']}", lambda_context)
    assert status == 200


@mock_aws
def test_cell_kpi_history_reads_dynamodb(clean_db, lambda_context, monkeypatch, valid_kpi_payload):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="cellwatch-kpi",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    monkeypatch.setenv("KPI_TABLE_NAME", "cellwatch-kpi")

    table = dynamodb.Table("cellwatch-kpi")
    for ts in (1000, 2000, 3000):
        sample_data = dict(valid_kpi_payload, cell_id="CELL-9002", timestamp=ts)
        table.put_item(Item=to_ddb_item(KpiSample(**sample_data)))

    status, history = _call("GET", "/cells/CELL-9002/kpis", lambda_context)
    assert status == 200
    assert [item["timestamp"] for item in history] == [3000, 2000, 1000]  # newest first


@mock_aws
def test_cell_health_combines_dynamodb_and_open_alerts(clean_db, lambda_context, monkeypatch, valid_kpi_payload):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="cellwatch-kpi",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    monkeypatch.setenv("KPI_TABLE_NAME", "cellwatch-kpi")

    _call("POST", "/cells", lambda_context, body={"id": "CELL-9003", "site": "Site-Test"})

    from common.db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alerts (cell_id, kpi_name, value, alert_type, severity) VALUES (%s, %s, %s, %s, %s)",
            ("CELL-9003", "call_drop_rate", 12.0, "threshold", "critical"),
        )
        conn.commit()

    status, health = _call("GET", "/cells/CELL-9003/health", lambda_context)
    assert status == 200
    assert health["status"] == "degraded"
    assert health["active_alert_count"] == 1
    assert health["latest_kpi"] is None


def test_alerts_list_defaults_to_active_only(clean_db, lambda_context):
    _call("POST", "/cells", lambda_context, body={"id": "CELL-9004", "site": "Site-Test"})

    from common.db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(
            "INSERT INTO alerts (cell_id, kpi_name, value, alert_type, severity, cleared_at) "
            "VALUES (%s, %s, %s, %s, %s, now())",
            ("CELL-9004", "call_drop_rate", 12.0, "threshold", "critical"),
        )
        cur.execute(
            "INSERT INTO alerts (cell_id, kpi_name, value, alert_type, severity) VALUES (%s, %s, %s, %s, %s)",
            ("CELL-9004", "prb_utilization_dl", 99.0, "threshold", "warning"),
        )
        conn.commit()

    status, active = _call("GET", "/alerts", lambda_context)
    assert status == 200
    assert len(active) == 1
    assert active[0]["cleared_at"] is None

    status, all_alerts = _call("GET", "/alerts", lambda_context, query={"active": "false"})
    assert status == 200
    assert len(all_alerts) == 2


def _rds_down(monkeypatch):
    import query.handler as handler_module

    def _boom():
        raise psycopg2.OperationalError("could not connect to server")

    monkeypatch.setattr(handler_module, "get_connection", _boom)


def test_list_cells_returns_503_when_rds_unavailable(monkeypatch, lambda_context):
    _rds_down(monkeypatch)

    status, body = _call("GET", "/cells", lambda_context)

    assert status == 503


@mock_aws
def test_cell_health_degrades_to_dynamodb_only_when_rds_unavailable(monkeypatch, lambda_context, valid_kpi_payload):
    dynamodb = boto3.resource("dynamodb", region_name="us-east-1")
    dynamodb.create_table(
        TableName="cellwatch-kpi",
        KeySchema=[
            {"AttributeName": "pk", "KeyType": "HASH"},
            {"AttributeName": "sk", "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "pk", "AttributeType": "S"},
            {"AttributeName": "sk", "AttributeType": "S"},
        ],
        BillingMode="PAY_PER_REQUEST",
    )
    monkeypatch.setenv("KPI_TABLE_NAME", "cellwatch-kpi")

    table = dynamodb.Table("cellwatch-kpi")
    sample_data = dict(valid_kpi_payload, cell_id="CELL-9005", timestamp=5000)
    table.put_item(Item=to_ddb_item(KpiSample(**sample_data)))

    _rds_down(monkeypatch)

    status, health = _call("GET", "/cells/CELL-9005/health", lambda_context)

    assert status == 200
    assert health["degraded"] is True
    assert health["latest_kpi"]["timestamp"] == 5000
    assert health["active_alerts"] is None

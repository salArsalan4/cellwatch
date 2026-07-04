import json

from alerter.handler import handler as alerter_handler
from common.db import get_connection


def _sns_record(cell_id: str, anomalies: list[dict]) -> dict:
    message = json.dumps({"cell_id": cell_id, "timestamp": 1751328000000, "anomalies": anomalies})
    return {
        "EventSource": "aws:sns",
        "EventVersion": "1.0",
        "Sns": {
            "Type": "Notification",
            "MessageId": "test-message-id",
            "TopicArn": "arn:aws:sns:us-east-1:123456789012:cellwatch-alerts",
            "Subject": "CellWatch alert",
            "Message": message,
            "Timestamp": "2026-07-01T00:00:00.000Z",
            "MessageAttributes": {},
        },
    }


def test_alerter_writes_one_row_per_anomaly(clean_db, lambda_context):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cells (id, site) VALUES (%s, %s)", ("CELL-9010", "Site-Test"))
        conn.commit()

    anomalies = [
        {"kpi_name": "call_drop_rate", "value": 10.0, "alert_type": "threshold", "severity": "critical"},
        {"kpi_name": "rsrp_dbm", "value": -140.0, "alert_type": "zscore", "severity": "warning"},
    ]
    event = {"Records": [_sns_record("CELL-9010", anomalies)]}

    alerter_handler(event, lambda_context)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT kpi_name, alert_type, severity, cleared_at FROM alerts WHERE cell_id = %s ORDER BY id", ("CELL-9010",))
        rows = cur.fetchall()

    assert len(rows) == 2
    assert rows[0][0] == "call_drop_rate"
    assert rows[0][1] == "threshold"
    assert rows[0][2] == "critical"
    assert rows[0][3] is None  # newly opened, not cleared
    assert rows[1][0] == "rsrp_dbm"


def test_alerter_handles_multiple_records_in_one_batch(clean_db, lambda_context):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO cells (id, site) VALUES (%s, %s)", ("CELL-9011", "Site-Test"))
        conn.commit()

    event = {
        "Records": [
            _sns_record(
                "CELL-9011", [{"kpi_name": "sinr_db", "value": -10.0, "alert_type": "threshold", "severity": "warning"}]
            ),
            _sns_record(
                "CELL-9011",
                [{"kpi_name": "prb_utilization_dl", "value": 0.0, "alert_type": "sleeping_cell", "severity": "critical"}],
            ),
        ]
    }

    alerter_handler(event, lambda_context)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM alerts WHERE cell_id = %s", ("CELL-9011",))
        assert cur.fetchone()[0] == 2

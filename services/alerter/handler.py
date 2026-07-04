"""SNS-triggered: writes one alert row to RDS per anomaly the processor
published. VPC-bound (needs RDS), unlike the processor -- that split is the
whole point (see services/processor's module docstring): it keeps the
RDS-touching write off the ingest hot path, decoupled via SNS so an RDS
hiccup here can't block or duplicate the ingest telemetry write.

SNS retries failed Lambda invocations on its own schedule and, per the
subscription's redrive policy, eventually routes to a DLQ -- so this
doesn't need its own retry logic.
"""

import json

from aws_lambda_powertools.utilities.typing import LambdaContext

from common.db import get_connection
from common.logging import get_logger, get_metrics, get_tracer

logger = get_logger("alerter")
metrics = get_metrics("alerter")
tracer = get_tracer()


@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> None:
    alerts_written = 0

    with get_connection() as conn, conn.cursor() as cur:
        for record in event["Records"]:
            message = json.loads(record["Sns"]["Message"])
            cell_id = message["cell_id"]
            for anomaly in message["anomalies"]:
                cur.execute(
                    """
                    INSERT INTO alerts (cell_id, kpi_name, value, alert_type, severity)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (cell_id, anomaly["kpi_name"], anomaly["value"], anomaly["alert_type"], anomaly["severity"]),
                )
                alerts_written += 1
                logger.info("alert_recorded", cell_id=cell_id, **anomaly)
        conn.commit()

    metrics.add_metric(name="AlertsWritten", unit="Count", value=alerts_written)

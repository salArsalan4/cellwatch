"""SQS batch-triggered handler: archives each KPI sample to S3, upserts the
hot DynamoDB item, then runs anomaly detection and -- on a hit -- publishes
to SNS. Detection/alerting failures are caught and logged rather than
re-raised: the telemetry write above is what must never be lost, and by
the time detection runs it has already succeeded, so a detection hiccup
shouldn't turn into an SQS retry that redoes (and potentially duplicates)
that write. Uses Powertools' BatchProcessor so a poison message fails only
its own item (partial batch response) instead of the whole batch being
retried/blocked -- repeated failures land it in the DLQ per the queue's
redrive policy.
"""

import json

import boto3
from aws_lambda_powertools.utilities.batch import BatchProcessor, EventType, process_partial_response
from aws_lambda_powertools.utilities.data_classes.sqs_event import SQSRecord
from aws_lambda_powertools.utilities.typing import LambdaContext

from common.config import require_env
from common.detection import detect
from common.kpi import KpiSample
from common.logging import get_logger, get_metrics, get_tracer
from common.storage import from_ddb_item, raw_archive_key, stats_key, to_ddb_item, to_stats_item

logger = get_logger("processor")
metrics = get_metrics("processor")
tracer = get_tracer()

_s3 = boto3.client("s3")
_dynamodb = boto3.resource("dynamodb")
_sns = boto3.client("sns")

processor = BatchProcessor(event_type=EventType.SQS)


def _detect_and_alert(sample: KpiSample, table) -> None:
    response = table.get_item(Key=stats_key(sample.cell_id))
    stats = from_ddb_item(response.get("Item", {}))
    stats.pop("pk", None)
    stats.pop("sk", None)

    updated_stats, anomalies = detect(sample, stats)
    table.put_item(Item=to_stats_item(sample.cell_id, updated_stats))

    if not anomalies:
        return

    metrics.add_metric(name="AnomaliesDetected", unit="Count", value=len(anomalies))
    anomaly_payloads = [a.__dict__ for a in anomalies]
    logger.warning("anomaly_detected", cell_id=sample.cell_id, timestamp=sample.timestamp, anomalies=anomaly_payloads)

    _sns.publish(
        TopicArn=require_env("ALERTS_TOPIC_ARN"),
        Subject=f"CellWatch alert: {sample.cell_id}",
        Message=json.dumps({"cell_id": sample.cell_id, "timestamp": sample.timestamp, "anomalies": anomaly_payloads}),
    )


def record_handler(record: SQSRecord) -> None:
    sample = KpiSample.model_validate_json(record.body)

    bucket = require_env("RAW_ARCHIVE_BUCKET")
    _s3.put_object(
        Bucket=bucket,
        Key=raw_archive_key(sample),
        Body=sample.model_dump_json().encode("utf-8"),
        ContentType="application/json",
    )

    table = _dynamodb.Table(require_env("KPI_TABLE_NAME"))
    table.put_item(Item=to_ddb_item(sample))

    logger.info("kpi_sample_stored", cell_id=sample.cell_id, timestamp=sample.timestamp)
    metrics.add_metric(name="SamplesStored", unit="Count", value=1)

    try:
        _detect_and_alert(sample, table)
    except Exception:
        logger.exception("detection_failed", cell_id=sample.cell_id, timestamp=sample.timestamp)


@logger.inject_lambda_context(log_event=False)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    return process_partial_response(
        event=event,
        record_handler=record_handler,
        processor=processor,
        context=context,
    )

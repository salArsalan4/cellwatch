"""API Gateway (REST, proxy integration) handler for POST /kpi.

API Gateway's own REQUEST model validation (schemas/kpi_sample.schema.json)
is the edge-level check; this handler re-validates via KpiSample so it's
also correct when invoked directly (local testing, or if the model isn't
wired up on a given stage) before handing the sample to SQS.
"""

import base64
import json

import boto3
from aws_lambda_powertools.utilities.typing import LambdaContext
from pydantic import ValidationError

from common.config import require_env
from common.kpi import KpiSample
from common.logging import get_logger, get_metrics, get_tracer

logger = get_logger("ingest")
metrics = get_metrics("ingest")
tracer = get_tracer()

_sqs = boto3.client("sqs")


def _response(status_code: int, body: dict) -> dict:
    return {
        "statusCode": status_code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }


@logger.inject_lambda_context(log_event=True)
@tracer.capture_lambda_handler
@metrics.log_metrics
def handler(event: dict, context: LambdaContext) -> dict:
    raw_body = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw_body = base64.b64decode(raw_body).decode("utf-8")

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        logger.warning("invalid_json_body")
        return _response(400, {"message": "Request body must be valid JSON"})

    try:
        sample = KpiSample.model_validate(payload)
    except ValidationError as exc:
        logger.warning("kpi_validation_failed", errors=exc.errors())
        return _response(400, {"message": "KPI sample failed validation", "errors": exc.errors()})

    queue_url = require_env("INGEST_QUEUE_URL")
    _sqs.send_message(
        QueueUrl=queue_url,
        MessageBody=sample.model_dump_json(),
        MessageAttributes={
            "cell_id": {"DataType": "String", "StringValue": sample.cell_id},
        },
    )

    logger.info("kpi_sample_enqueued", cell_id=sample.cell_id, timestamp=sample.timestamp)
    metrics.add_metric(name="SamplesIngested", unit="Count", value=1)

    return _response(202, {"status": "accepted"})

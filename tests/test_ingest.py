import json

import boto3
from moto import mock_aws

from ingest.handler import handler as ingest_handler


def _api_event(body) -> dict:
    return {
        "body": body if isinstance(body, str) else json.dumps(body),
        "isBase64Encoded": False,
        "headers": {"Content-Type": "application/json"},
    }


@mock_aws
def test_ingest_accepts_valid_sample_and_enqueues(monkeypatch, lambda_context, valid_kpi_payload):
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="kpi-ingest")["QueueUrl"]
    monkeypatch.setenv("INGEST_QUEUE_URL", queue_url)

    response = ingest_handler(_api_event(valid_kpi_payload), lambda_context)

    assert response["statusCode"] == 202
    assert json.loads(response["body"]) == {"status": "accepted"}

    messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1)["Messages"]
    assert len(messages) == 1
    enqueued = json.loads(messages[0]["Body"])
    assert enqueued["cell_id"] == valid_kpi_payload["cell_id"]
    assert enqueued["timestamp"] == valid_kpi_payload["timestamp"]


@mock_aws
def test_ingest_rejects_out_of_range_value(monkeypatch, lambda_context, valid_kpi_payload):
    sqs = boto3.client("sqs", region_name="us-east-1")
    queue_url = sqs.create_queue(QueueName="kpi-ingest")["QueueUrl"]
    monkeypatch.setenv("INGEST_QUEUE_URL", queue_url)

    bad_payload = dict(valid_kpi_payload)
    bad_payload["rsrp_dbm"] = 10.0  # outside the -140..-44 dBm range

    response = ingest_handler(_api_event(bad_payload), lambda_context)

    assert response["statusCode"] == 400
    assert sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1).get("Messages") is None


def test_ingest_rejects_malformed_json(lambda_context):
    response = ingest_handler(_api_event("{not valid json"), lambda_context)

    assert response["statusCode"] == 400

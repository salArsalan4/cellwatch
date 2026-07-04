import json

import boto3
from moto import mock_aws

from processor.handler import handler as processor_handler


def _sqs_record(message_id: str, body: str) -> dict:
    return {
        "messageId": message_id,
        "receiptHandle": f"receipt-{message_id}",
        "body": body,
        "attributes": {
            "ApproximateReceiveCount": "1",
            "SentTimestamp": "1751328000000",
            "SenderId": "AIDAEXAMPLE",
            "ApproximateFirstReceiveTimestamp": "1751328000000",
        },
        "messageAttributes": {},
        "md5OfBody": "test-md5",
        "eventSource": "aws:sqs",
        "eventSourceARN": "arn:aws:sqs:us-east-1:123456789012:kpi-queue",
        "awsRegion": "us-east-1",
    }


def _setup(monkeypatch):
    s3 = boto3.client("s3", region_name="us-east-1")
    s3.create_bucket(Bucket="cellwatch-raw")

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

    sns = boto3.client("sns", region_name="us-east-1")
    topic_arn = sns.create_topic(Name="cellwatch-alerts")["TopicArn"]

    monkeypatch.setenv("RAW_ARCHIVE_BUCKET", "cellwatch-raw")
    monkeypatch.setenv("KPI_TABLE_NAME", "cellwatch-kpi")
    monkeypatch.setenv("ALERTS_TOPIC_ARN", topic_arn)

    return s3, dynamodb, sns, topic_arn


@mock_aws
def test_processor_stores_valid_sample_and_reports_bad_one(monkeypatch, lambda_context, valid_kpi_payload):
    s3, dynamodb, _sns, _topic_arn = _setup(monkeypatch)

    event = {
        "Records": [
            _sqs_record("good-1", json.dumps(valid_kpi_payload)),
            _sqs_record("bad-1", "{not valid json"),
        ]
    }

    response = processor_handler(event, lambda_context)

    failures = response["batchItemFailures"]
    assert failures == [{"itemIdentifier": "bad-1"}]

    table = dynamodb.Table("cellwatch-kpi")
    item = table.get_item(
        Key={
            "pk": f"CELL#{valid_kpi_payload['cell_id']}",
            "sk": f"TS#{valid_kpi_payload['timestamp']}",
        }
    )["Item"]
    assert item["cell_id"] == valid_kpi_payload["cell_id"]
    assert "ttl" in item

    objects = s3.list_objects_v2(Bucket="cellwatch-raw")["Contents"]
    assert len(objects) == 1
    assert objects[0]["Key"].startswith(f"raw/dt=2025-07-01/cell={valid_kpi_payload['cell_id']}/")


@mock_aws
def test_processor_updates_ewma_stats_without_alerting_on_normal_sample(monkeypatch, lambda_context, valid_kpi_payload):
    _s3, dynamodb, _sns, _topic_arn = _setup(monkeypatch)

    event = {"Records": [_sqs_record("normal-1", json.dumps(valid_kpi_payload))]}
    processor_handler(event, lambda_context)

    table = dynamodb.Table("cellwatch-kpi")
    stats_item = table.get_item(Key={"pk": f"CELL#{valid_kpi_payload['cell_id']}", "sk": "STATS"}).get("Item")
    assert stats_item is not None
    assert "ttl" not in stats_item


@mock_aws
def test_processor_publishes_sns_alert_on_threshold_breach(monkeypatch, lambda_context, valid_kpi_payload):
    _s3, _dynamodb, sns, topic_arn = _setup(monkeypatch)

    queue_url = boto3.client("sqs", region_name="us-east-1").create_queue(QueueName="alert-catcher")["QueueUrl"]
    queue_arn = boto3.client("sqs", region_name="us-east-1").get_queue_attributes(
        QueueUrl=queue_url, AttributeNames=["QueueArn"]
    )["Attributes"]["QueueArn"]
    sns.subscribe(TopicArn=topic_arn, Protocol="sqs", Endpoint=queue_arn)

    anomalous = dict(valid_kpi_payload, call_drop_rate=10.0)
    event = {"Records": [_sqs_record("anomaly-1", json.dumps(anomalous))]}
    processor_handler(event, lambda_context)

    sqs = boto3.client("sqs", region_name="us-east-1")
    messages = sqs.receive_message(QueueUrl=queue_url, MaxNumberOfMessages=1, WaitTimeSeconds=1).get("Messages", [])
    assert len(messages) == 1
    sns_envelope = json.loads(messages[0]["Body"])
    alert = json.loads(sns_envelope["Message"])
    assert alert["cell_id"] == valid_kpi_payload["cell_id"]
    assert any(a["kpi_name"] == "call_drop_rate" and a["alert_type"] == "threshold" for a in alert["anomalies"])

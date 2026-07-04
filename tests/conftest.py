import os
import shutil
import socket
import subprocess
import time

os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "testing")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "testing")
os.environ.setdefault("AWS_SESSION_TOKEN", "testing")
os.environ.setdefault("POWERTOOLS_TRACE_DISABLED", "true")

# Belt-and-suspenders alongside the session-wide mock_aws fixture below:
# Tracer.__init__ calls self.patch(...) (wrapping botocore for X-Ray)
# whenever auto_patch is true, regardless of the disabled flag above.
# Tracer's config is a shared class-level dict across every Tracer()
# instance in the process, so constructing one here with auto_patch=False
# -- before any handler module is imported -- propagates to all of them.
from aws_lambda_powertools import Tracer  # noqa: E402

Tracer(auto_patch=False)

import psycopg2
import pytest
from moto import mock_aws

# Some handler modules construct real boto3 clients at import time
# (e.g. ingest's SQS client, common.db's Secrets Manager client) -- a
# deliberate, correct choice for warm-invocation reuse in production.
# But it means those clients can exist before any single test's @mock_aws
# decorator ever activates, and depending on *which* module gets imported
# first (an artifact of test file collection order, not anything we
# control), that's enough to leave the first real AWS call afterward
# unmocked -- observed as a live SendMessage/Query hitting real AWS with
# fake "testing" credentials instead of moto intercepting it. Keeping one
# mock_aws() active for the whole session, entered before any test module
# is even collected, removes the window where that can happen at all.
_session_mock = mock_aws()
_session_mock.start()


def pytest_unconfigure(config):
    _session_mock.stop()


@pytest.fixture(autouse=True)
def _reset_aws_mock_state():
    # Keeping one mock_aws active for the whole session (rather than
    # stopping/restarting it per test via each test's own @mock_aws
    # decorator) is what fixes the collection-time issue above, but it
    # means backend state -- DynamoDB tables, SQS queues, S3 buckets --
    # would otherwise leak across tests. Reset it before every test
    # instead so each test still gets a clean slate.
    _session_mock.reset()
    yield


class FakeLambdaContext:
    function_name = "test-function"
    memory_limit_in_mb = 128
    invoked_function_arn = "arn:aws:lambda:us-east-1:123456789012:function:test-function"
    aws_request_id = "test-request-id"

    def get_remaining_time_in_millis(self) -> int:
        return 30000


@pytest.fixture
def lambda_context() -> FakeLambdaContext:
    return FakeLambdaContext()


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_postgres(dsn: dict, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = None
    while time.monotonic() < deadline:
        try:
            psycopg2.connect(connect_timeout=2, **dsn).close()
            return
        except psycopg2.OperationalError as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"Postgres test container did not become ready: {last_error}")


@pytest.fixture(scope="session")
def postgres_container():
    """A real Postgres in Docker, not a mock — psycopg2/SQL correctness
    isn't something moto (or any mock) can stand in for."""
    if shutil.which("docker") is None:
        pytest.skip("docker not available")

    port = _free_port()
    name = f"cellwatch-test-pg-{port}"
    dsn = {"host": "127.0.0.1", "port": port, "dbname": "cellwatch", "user": "postgres", "password": "test"}

    subprocess.run(
        [
            "docker", "run", "-d", "--rm", "--name", name,
            "-e", "POSTGRES_PASSWORD=test",
            "-e", "POSTGRES_DB=cellwatch",
            "-p", f"{port}:5432",
            "postgres:16-alpine",
        ],
        check=True,
        capture_output=True,
    )
    try:
        _wait_for_postgres(dsn)
        yield dsn
    finally:
        subprocess.run(["docker", "stop", name], capture_output=True)


@pytest.fixture
def db_env(monkeypatch, postgres_container):
    import common.db as db_module

    monkeypatch.setenv("DB_HOST", postgres_container["host"])
    monkeypatch.setenv("DB_PORT", str(postgres_container["port"]))
    monkeypatch.setenv("DB_NAME", postgres_container["dbname"])
    monkeypatch.setenv("DB_SECRET_ARN", "arn:aws:secretsmanager:us-east-1:123456789012:secret:test")
    monkeypatch.setenv("DB_SSLMODE", "disable")  # local container has no SSL configured
    monkeypatch.setattr(
        db_module,
        "_get_credentials",
        lambda: {"username": postgres_container["user"], "password": postgres_container["password"]},
    )


@pytest.fixture
def clean_db(db_env):
    from migrate.handler import SCHEMA_SQL

    from common.db import get_connection

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)
        cur.execute("TRUNCATE cells, thresholds, alerts RESTART IDENTITY CASCADE")
        conn.commit()
    yield


@pytest.fixture
def valid_kpi_payload() -> dict:
    return {
        "cell_id": "CELL-0001-A3",
        "timestamp": 1751328000000,
        "prb_utilization_dl": 42.5,
        "prb_utilization_ul": 18.3,
        "rrc_connected_users": 57,
        "dl_throughput_mbps": 120.4,
        "ul_throughput_mbps": 22.1,
        "rsrp_dbm": -95.0,
        "rsrq_db": -10.5,
        "sinr_db": 12.0,
        "handover_success_rate": 98.2,
        "call_drop_rate": 0.4,
        "prach_attempts": 133,
    }

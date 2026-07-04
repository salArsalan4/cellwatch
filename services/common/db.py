"""RDS Postgres connection for VPC-bound Lambdas (query, migrate).

Credentials are never in code/env: RDS's `manage_master_user_password`
puts them in a Secrets Manager secret AWS creates and rotates itself, and
this only ever reads that secret at runtime (cached per warm container).
"""

import json
import os
from contextlib import contextmanager

import boto3
import psycopg2

from common.config import require_env

_secrets_client = boto3.client("secretsmanager")
_cached_credentials: dict | None = None


def _get_credentials() -> dict:
    global _cached_credentials
    if _cached_credentials is None:
        secret_arn = require_env("DB_SECRET_ARN")
        response = _secrets_client.get_secret_value(SecretId=secret_arn)
        _cached_credentials = json.loads(response["SecretString"])
    return _cached_credentials


@contextmanager
def get_connection():
    creds = _get_credentials()
    conn = psycopg2.connect(
        host=require_env("DB_HOST"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=require_env("DB_NAME"),
        user=creds["username"],
        password=creds["password"],
        connect_timeout=5,
        # RDS enforces this server-side too (rds.force_ssl=1, see
        # infra/modules/control-plane/rds.tf) -- requiring it client-side
        # as well means a misconfigured server fails closed rather than
        # silently connecting in plaintext. Tests override this to
        # "disable" (see tests/conftest.py's db_env fixture) since the
        # local Postgres container doesn't have SSL configured.
        sslmode=os.environ.get("DB_SSLMODE", "require"),
    )
    try:
        yield conn
    finally:
        conn.close()

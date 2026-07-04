from common.db import get_connection
from migrate.handler import handler as migrate_handler


def test_migrate_creates_schema_and_seeds_cells(db_env, lambda_context):
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS alerts, thresholds, cells CASCADE")
        conn.commit()

    result = migrate_handler({}, lambda_context)

    assert result == {"status": "ok", "cells_seeded": 20}

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cells")
        assert cur.fetchone()[0] == 20
        cur.execute("SELECT count(*) FROM thresholds")
        assert cur.fetchone()[0] == 40  # 2 seeded thresholds per cell


def test_migrate_is_idempotent(clean_db, lambda_context):
    migrate_handler({}, lambda_context)
    migrate_handler({}, lambda_context)

    with get_connection() as conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM cells")
        assert cur.fetchone()[0] == 20

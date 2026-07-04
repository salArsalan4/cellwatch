"""One-off schema migration + demo seed for RDS. Not on any request path —
invoke manually after RDS comes up:

    aws lambda invoke --function-name cellwatch-migrate --payload '{}' out.json

Safe to re-run: DDL uses IF NOT EXISTS, seed uses ON CONFLICT DO NOTHING.
RDS sits in a private subnet with no NAT/bastion, so a VPC-bound Lambda is
the only way to reach it from outside the VPC without standing up a bastion.
"""

import importlib.resources

from aws_lambda_powertools.utilities.typing import LambdaContext

from common.db import get_connection
from common.logging import get_logger

logger = get_logger("migrate")

SCHEMA_SQL = importlib.resources.files("common").joinpath("schema.sql").read_text()

# Matches the generator's default cell_id convention (CELL-0000..) so a demo
# run has inventory + thresholds to query against immediately.
SEED_CELLS = [(f"CELL-{i:04d}", f"Site-{i // 4:03d}", (i % 4) + 1) for i in range(20)]
SEED_THRESHOLDS = [
    ("prb_utilization_dl", 0, 90, "warning"),
    ("call_drop_rate", 0, 3, "critical"),
]


def handler(event: dict, context: LambdaContext) -> dict:
    with get_connection() as conn, conn.cursor() as cur:
        cur.execute(SCHEMA_SQL)

        for cell_id, site, sector in SEED_CELLS:
            cur.execute(
                """
                INSERT INTO cells (id, site, sector, band, status)
                VALUES (%s, %s, %s, %s, 'active')
                ON CONFLICT (id) DO NOTHING
                """,
                (cell_id, site, sector, "n78"),
            )
            for kpi_name, min_value, max_value, severity in SEED_THRESHOLDS:
                cur.execute(
                    """
                    INSERT INTO thresholds (cell_id, kpi_name, min_value, max_value, severity)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (cell_id, kpi_name) DO NOTHING
                    """,
                    (cell_id, kpi_name, min_value, max_value, severity),
                )

        conn.commit()

    logger.info("migration_complete", cells_seeded=len(SEED_CELLS))
    return {"status": "ok", "cells_seeded": len(SEED_CELLS)}

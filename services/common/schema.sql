-- RDS relational schema per docs/OVERVIEW.md §5.3: cell inventory, per-cell/
-- per-KPI thresholds, alert history. Applied by services/migrate/handler.py.
-- All statements are idempotent (IF NOT EXISTS / ON CONFLICT) so re-running
-- the migrate Lambda is always safe.

CREATE TABLE IF NOT EXISTS cells (
    id         VARCHAR(64) PRIMARY KEY,
    site       VARCHAR(128) NOT NULL,
    latitude   DOUBLE PRECISION,
    longitude  DOUBLE PRECISION,
    band       VARCHAR(32),
    sector     INTEGER,
    status     VARCHAR(32) NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS thresholds (
    id         SERIAL PRIMARY KEY,
    cell_id    VARCHAR(64) NOT NULL REFERENCES cells(id) ON DELETE CASCADE,
    kpi_name   VARCHAR(64) NOT NULL,
    min_value  DOUBLE PRECISION,
    max_value  DOUBLE PRECISION,
    severity   VARCHAR(16) NOT NULL DEFAULT 'warning',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (cell_id, kpi_name)
);

CREATE TABLE IF NOT EXISTS alerts (
    id         SERIAL PRIMARY KEY,
    cell_id    VARCHAR(64) NOT NULL REFERENCES cells(id) ON DELETE CASCADE,
    kpi_name   VARCHAR(64) NOT NULL,
    value      DOUBLE PRECISION NOT NULL,
    alert_type VARCHAR(32) NOT NULL,
    severity   VARCHAR(16) NOT NULL,
    opened_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    cleared_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_thresholds_cell_id ON thresholds (cell_id);
CREATE INDEX IF NOT EXISTS idx_alerts_cell_id ON alerts (cell_id);
CREATE INDEX IF NOT EXISTS idx_alerts_open ON alerts (cell_id) WHERE cleared_at IS NULL;

#!/usr/bin/env bash
# Build Lambda deployment artifacts under infra/build/:
#   build/layer/python/     - powertools/pydantic/xray-sdk + services/common,
#                              shared by all four functions
#   build/db-layer/python/  - psycopg2-binary only, shared by query + migrate
#                              (kept separate so ingest/processor don't carry
#                              a Postgres C-extension they never use)
#   build/ingest/            - just the ingest handler
#   build/processor/         - just the processor handler
#   build/query/             - just the query/admin handler
#   build/migrate/           - just the migrate handler
#   build/alerter/           - just the alerter handler
#
# Terraform's archive_file data sources zip these directories at plan/apply
# time (see infra/modules/data-plane, infra/modules/control-plane). Re-run
# this whenever services/common or the pinned dependency versions change —
# Terraform has no visibility into what's inside these directories, only
# their zip hash.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/../.."  # repo root
BUILD_DIR="infra/build"

rm -rf "$BUILD_DIR"
mkdir -p "$BUILD_DIR/layer/python" "$BUILD_DIR/db-layer/python" \
  "$BUILD_DIR/ingest" "$BUILD_DIR/processor" "$BUILD_DIR/query" "$BUILD_DIR/migrate" "$BUILD_DIR/alerter"

echo "Installing shared layer dependencies (x86_64-manylinux2014, Python 3.12)..."
uv pip install \
  --target "$BUILD_DIR/layer/python" \
  --python-platform x86_64-manylinux2014 \
  --python 3.12 \
  aws-lambda-powertools pydantic aws-xray-sdk

echo "Installing db layer dependencies..."
uv pip install \
  --target "$BUILD_DIR/db-layer/python" \
  --python-platform x86_64-manylinux2014 \
  --python 3.12 \
  psycopg2-binary

echo "Copying services/common into the shared layer..."
cp -r services/common "$BUILD_DIR/layer/python/common"
find "$BUILD_DIR/layer/python/common" -name '__pycache__' -exec rm -rf {} +

echo "Copying function handlers..."
cp services/ingest/handler.py "$BUILD_DIR/ingest/handler.py"
cp services/processor/handler.py "$BUILD_DIR/processor/handler.py"
cp services/query/handler.py "$BUILD_DIR/query/handler.py"
cp services/migrate/handler.py "$BUILD_DIR/migrate/handler.py"
cp services/alerter/handler.py "$BUILD_DIR/alerter/handler.py"

echo "Build artifacts ready under $BUILD_DIR/"
du -sh "$BUILD_DIR"/layer "$BUILD_DIR"/db-layer "$BUILD_DIR"/ingest "$BUILD_DIR"/processor "$BUILD_DIR"/query "$BUILD_DIR"/migrate "$BUILD_DIR"/alerter

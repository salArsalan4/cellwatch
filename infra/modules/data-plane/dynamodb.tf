# Hot KPI time-series store per docs/OVERVIEW.md §5.3: PK = CELL#<cell_id>,
# SK = TS#<epoch_ms>. On-demand capacity (bursty, unpredictable write volume),
# 7-day TTL, PITR for the durability NFR.

resource "aws_dynamodb_table" "kpi" {
  name         = "${var.project_name}-kpi"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pk"
  range_key    = "sk"

  attribute {
    name = "pk"
    type = "S"
  }

  attribute {
    name = "sk"
    type = "S"
  }

  ttl {
    attribute_name = "ttl"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = {
    Name = "${var.project_name}-kpi"
  }
}

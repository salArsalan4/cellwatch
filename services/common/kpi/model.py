"""Python-side mirror of schemas/kpi_sample.schema.json.

API Gateway request validation uses the JSON Schema file directly (it can't
import Pydantic). This model is for everything on the Python side — the
generator building samples, and Lambda Powertools' event parser validating
them again once inside processor/query. Keep the two in sync by hand; there's
no codegen step for a schema this small and stable.
"""

from pydantic import BaseModel, Field


class KpiSample(BaseModel):
    cell_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    timestamp: int = Field(ge=0, description="UTC epoch milliseconds")
    prb_utilization_dl: float = Field(ge=0, le=100)
    prb_utilization_ul: float = Field(ge=0, le=100)
    rrc_connected_users: int = Field(ge=0)
    dl_throughput_mbps: float = Field(ge=0)
    ul_throughput_mbps: float = Field(ge=0)
    rsrp_dbm: float = Field(ge=-140, le=-44)
    rsrq_db: float = Field(ge=-19.5, le=-3)
    sinr_db: float = Field(ge=-20, le=30)
    handover_success_rate: float = Field(ge=0, le=100)
    call_drop_rate: float = Field(ge=0, le=100)
    prach_attempts: int = Field(ge=0)

    model_config = {"extra": "forbid"}

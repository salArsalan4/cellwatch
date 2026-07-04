"""Per-cell state and one bounded random-walk step per KPI, with optional
anomaly modes (sleeping / congested / degraded) so the same generator that
feeds steady-state traffic can also exercise the anomaly detector once
Phase 3 exists.
"""

import random
from dataclasses import dataclass
from enum import Enum

from common.kpi import KpiSample


class Mode(str, Enum):
    NORMAL = "normal"
    SLEEPING = "sleeping"
    CONGESTED = "congested"
    DEGRADED = "degraded"


def _walk(value: float, step: float, low: float, high: float) -> float:
    value += random.uniform(-step, step)
    return max(low, min(high, value))


@dataclass
class CellState:
    cell_id: str
    prb_dl: float
    prb_ul: float
    rrc_users: float
    dl_mbps: float
    ul_mbps: float
    rsrp: float
    rsrq: float
    sinr: float
    handover_rate: float
    drop_rate: float
    prach: float
    mode: Mode = Mode.NORMAL
    mode_rounds_left: int = 0

    @classmethod
    def new(cls, cell_id: str) -> "CellState":
        return cls(
            cell_id=cell_id,
            prb_dl=random.uniform(20, 60),
            prb_ul=random.uniform(10, 40),
            rrc_users=random.uniform(15, 80),
            dl_mbps=random.uniform(40, 150),
            ul_mbps=random.uniform(8, 30),
            rsrp=random.uniform(-100, -80),
            rsrq=random.uniform(-14, -8),
            sinr=random.uniform(5, 20),
            handover_rate=random.uniform(96, 99.5),
            drop_rate=random.uniform(0.1, 1.0),
            prach=random.uniform(50, 200),
        )

    def maybe_start_anomaly(self, anomaly_rate: float) -> None:
        if self.mode != Mode.NORMAL or anomaly_rate <= 0:
            return
        if random.random() < anomaly_rate:
            self.mode = random.choice((Mode.SLEEPING, Mode.CONGESTED, Mode.DEGRADED))
            self.mode_rounds_left = random.randint(3, 10)

    def step(self, timestamp_ms: int, anomaly_rate: float = 0.0) -> KpiSample:
        self.maybe_start_anomaly(anomaly_rate)

        if self.mode != Mode.NORMAL:
            self.mode_rounds_left -= 1
            if self.mode_rounds_left <= 0:
                self.mode = Mode.NORMAL

        self.prb_dl = _walk(self.prb_dl, 5, 0, 100)
        self.prb_ul = _walk(self.prb_ul, 5, 0, 100)
        self.rrc_users = _walk(self.rrc_users, 5, 0, 500)
        self.dl_mbps = _walk(self.dl_mbps, 10, 0, 300)
        self.ul_mbps = _walk(self.ul_mbps, 3, 0, 100)
        self.rsrp = _walk(self.rsrp, 2, -140, -44)
        self.rsrq = _walk(self.rsrq, 1, -19.5, -3)
        self.sinr = _walk(self.sinr, 2, -20, 30)
        self.handover_rate = _walk(self.handover_rate, 0.5, 0, 100)
        self.drop_rate = _walk(self.drop_rate, 0.2, 0, 100)
        self.prach = _walk(self.prach, 20, 0, 1000)

        prb_dl, prb_ul, rrc_users = self.prb_dl, self.prb_ul, self.rrc_users
        dl_mbps, ul_mbps, prach = self.dl_mbps, self.ul_mbps, self.prach
        handover_rate, drop_rate = self.handover_rate, self.drop_rate
        rsrp, rsrq, sinr = self.rsrp, self.rsrq, self.sinr

        if self.mode == Mode.SLEEPING:
            prb_dl, prb_ul = 0.0, 0.0
            rrc_users, dl_mbps, ul_mbps, prach = 0, 0.0, 0.0, 0
        elif self.mode == Mode.CONGESTED:
            prb_dl = max(prb_dl, random.uniform(95, 100))
            prb_ul = max(prb_ul, random.uniform(90, 100))
            handover_rate = min(handover_rate, random.uniform(60, 80))
            drop_rate = max(drop_rate, random.uniform(5, 15))
        elif self.mode == Mode.DEGRADED:
            rsrp = min(rsrp, random.uniform(-125, -110))
            rsrq = min(rsrq, random.uniform(-19, -16))
            sinr = min(sinr, random.uniform(-15, -5))
            drop_rate = max(drop_rate, random.uniform(3, 10))

        return KpiSample(
            cell_id=self.cell_id,
            timestamp=timestamp_ms,
            prb_utilization_dl=round(prb_dl, 2),
            prb_utilization_ul=round(prb_ul, 2),
            rrc_connected_users=int(rrc_users),
            dl_throughput_mbps=round(dl_mbps, 2),
            ul_throughput_mbps=round(ul_mbps, 2),
            rsrp_dbm=round(rsrp, 1),
            rsrq_db=round(rsrq, 1),
            sinr_db=round(sinr, 1),
            handover_success_rate=round(handover_rate, 2),
            call_drop_rate=round(drop_rate, 2),
            prach_attempts=int(prach),
        )

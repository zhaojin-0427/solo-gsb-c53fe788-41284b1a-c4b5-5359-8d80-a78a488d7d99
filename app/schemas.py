"""Pydantic 请求 / 响应模型。

注意：响应系数 alpha 为 0.01~1.00、至多两位小数，以 Decimal 接收以
避免 0.1 + 0.2 之类的浮点误差；进入求解器与仿真器时统一转成 Fraction。
"""
from __future__ import annotations

from decimal import Decimal
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


def _two_places(value: Decimal, field: str, lo: str, hi: str) -> Decimal:
    d = Decimal(str(value))
    if d.as_tuple().exponent < -2:
        raise ValueError(f"{field} 至多保留两位小数")
    if not (Decimal(lo) <= d <= Decimal(hi)):
        raise ValueError(f"{field} 必须位于 [{lo}, {hi}]")
    return d.quantize(Decimal("0.01"))


class LockEntry(BaseModel):
    minute: int = Field(..., ge=1, le=24, description="锁定的分钟序号（1~24）")
    value: int = Field(..., ge=0, le=300, description="该分钟锁定的设定温度")


class ZoneInput(BaseModel):
    name: str = Field(..., min_length=1, max_length=20)
    initial_temp: int = Field(..., ge=0, le=300, description="初温（℃，整数）")
    alpha1: Decimal = Field(..., description="响应系数 1，0.01~1.00，两位小数")
    alpha2: Decimal = Field(..., description="响应系数 2，0.01~1.00，两位小数")
    final_low: int = Field(..., ge=0, le=300, description="终温区间下限（℃，整数）")
    final_high: int = Field(..., ge=0, le=300, description="终温区间上限（℃，整数）")
    upper_limit: int = Field(..., ge=0, le=300, description="全程温度上限（℃，整数）")
    exposure_threshold: int = Field(..., ge=0, le=300, description="热暴露阈值（℃，整数）")
    exposure_min: Decimal = Field(..., ge=0, max_digits=10, decimal_places=2,
                                  description="非负最低累计热暴露值，两位小数")

    @field_validator("alpha1", "alpha2")
    @classmethod
    def _check_alpha(cls, v: Decimal) -> Decimal:
        return _two_places(v, "响应系数", "0.01", "1.00")

    @model_validator(mode="after")
    def _check_intervals(self) -> "ZoneInput":
        if self.final_low > self.final_high:
            raise ValueError("终温区间下限不得大于上限")
        return self


class SolveRequest(BaseModel):
    duration: int = Field(..., ge=1, le=24, description="烘烤分钟数 1~24")
    max_ramp: int = Field(..., ge=0, description="相邻分钟设定温度跃变上限（非负整数）")
    locks: List[LockEntry] = Field(default_factory=list)
    zones: List[ZoneInput] = Field(..., min_length=2, max_length=2)

    @model_validator(mode="after")
    def _check_locks(self) -> "SolveRequest":
        minutes = [lk.minute for lk in self.locks]
        if len(set(minutes)) != len(minutes):
            raise ValueError("同一分钟只能锁定一次")
        return self


class TrajectoryPoint(BaseModel):
    minute: int
    setpoint: Optional[int] = None          # t=0 时为空
    temp: str
    excess: str                             # max(0, T - threshold)
    upper_margin: str                       # upper_limit - T
    final_low_margin: Optional[str] = None  # 仅末分钟
    final_high_margin: Optional[str] = None
    ramp_margin: Optional[str] = None       # max_ramp - |ΔU|，t>=2


class TrajectoryResult(BaseModel):
    zone: str
    alpha: str
    upper_limit: int
    final_low: int
    final_high: int
    exposure_threshold: int
    exposure: str
    exposure_min: str
    exposure_margin: str
    points: List[TrajectoryPoint]
    violations: List[str] = []


class SolveResponse(BaseModel):
    status: str          # INFEASIBLE / FEASIBLE_OPTIMAL / FEASIBLE_NOT_OPTIMAL / NO_FEASIBLE_FOUND / ERROR
    status_text: str
    optimal: Optional[bool] = None
    elapsed_ms: int
    timed_out: bool
    setpoints: List[int] = []
    objective_sum: Optional[int] = None
    trajectories: List[TrajectoryResult] = []
    reason: Optional[str] = None


class SnapshotSaveRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)
    request: SolveRequest
    result: SolveResponse


class SnapshotSummary(BaseModel):
    id: int
    name: str
    status: str
    status_text: str
    objective_sum: Optional[int]
    optimal: Optional[bool]
    elapsed_ms: int
    created_at: str

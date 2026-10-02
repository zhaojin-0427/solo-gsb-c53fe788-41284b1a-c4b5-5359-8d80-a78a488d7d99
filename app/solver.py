"""双区烘箱曲线求解器。

物理模型（对每一区、每一种响应系数 alpha 各有一条轨迹）：
    T(0) = T0
    T(t+1) = T(t) + alpha * (U(t+1) - T(t))      t = 0..N-1
其中 U(1..N) 为两区共享的设定温度（0~300 整数），
热暴露量 E = Σ_{t=1..N} max(0, T(t) - 阈值)。

优化目标（字典序）：
    1) 最小化 Σ U(t)
    2) 在总和相同的前提下，按分钟序依次最小化 U(1), U(2), ..., U(N)

Z3 中温度使用 Real 理论；alpha 为两位小数，故全部用有理数精确表达，
不存在浮点误差。求解分两阶段：
    A. 可行性检查（判定无解 / 取得初始可行曲线）
    B. Optimize 字典序优化
两阶段共享同一个 10 秒墙上时间预算。
"""
from __future__ import annotations

import time
from decimal import Decimal
from fractions import Fraction
from typing import Any, Dict, List, Optional, Tuple

import z3

from .schemas import LockEntry, SolveRequest, ZoneInput

TOTAL_BUDGET_SEC = 10.0
MARGIN_SEC = 0.15

# 求解状态
INFEASIBLE = "INFEASIBLE"                       # 已证明无解
FEASIBLE_OPTIMAL = "FEASIBLE_OPTIMAL"           # 可行且已证字典序最优
FEASIBLE_NOT_OPTIMAL = "FEASIBLE_NOT_OPTIMAL"   # 找到可行曲线，但未在限时内证最优
NO_FEASIBLE_FOUND = "NO_FEASIBLE_FOUND"         # 限时内尚未找到任何可行曲线
ERROR = "ERROR"

STATUS_TEXT = {
    INFEASIBLE: "无解：约束互相冲突，不存在任何可行曲线",
    FEASIBLE_OPTIMAL: "已找到可行曲线，并证明为字典序最优",
    FEASIBLE_NOT_OPTIMAL: "已找到可行曲线，但限时内未能证明最优",
    NO_FEASIBLE_FOUND: "求解超时：尚未找到可行曲线（不代表无解）",
    ERROR: "求解过程发生错误",
}


def dec_to_fraction(d: Decimal) -> Fraction:
    return Fraction(d.quantize(Decimal("0.01")))


def frac_to_q(num: Fraction) -> z3.RatNumRef:
    """将 Fraction 转为 Z3 实有理值。"""
    return z3.RealVal(num.numerator) / z3.RealVal(num.denominator)


def fmt_frac(v: Fraction, places: int = 6) -> str:
    """把 Fraction 格式化为至多 places 位小数（去除尾随 0）。"""
    q = Decimal(10) ** -places
    d = Decimal(v.numerator) / Decimal(v.denominator)
    s = format(d.quantize(q), f"f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    return s or "0"


class _Model:
    def __init__(self, request: SolveRequest) -> None:
        self.n = request.duration
        self.max_ramp = request.max_ramp
        self.zones = request.zones
        # 锁定 minute -> value
        self.locked: Dict[int, int] = {lk.minute: lk.value for lk in request.locks}
        self.alphas: List[List[Fraction]] = [
            [dec_to_fraction(z.alpha1), dec_to_fraction(z.alpha2)] for z in self.zones
        ]
        self.exposure_min: List[Fraction] = [
            dec_to_fraction(z.exposure_min) for z in self.zones
        ]

    def build(self) -> Tuple[z3.Solver, List[z3.ArithRef], List[List[List[z3.ArithRef]]]]:
        """构造基础求解器。返回 (solver, U, temps)。

        temps[z][k][t]：第 z 区、第 k 种系数、第 t 分钟末温度（t=0..N）。
        """
        s = z3.Solver()
        n = self.n
        U = [z3.Int(f"u_{t}") for t in range(1, n + 1)]

        for t in range(n):
            s.add(U[t] >= 0, U[t] <= 300)
        for t, v in self.locked.items():
            s.add(U[t - 1] == v)
        # 相邻分钟跃变：|U(t) - U(t-1)| <= max_ramp
        ramp = self.max_ramp
        for t in range(1, n):
            s.add(U[t] - U[t - 1] <= ramp)
            s.add(U[t - 1] - U[t] <= ramp)

        temps: List[List[List[z3.ArithRef]]] = []
        for zi, zone in enumerate(self.zones):
            traj_k: List[List[z3.ArithRef]] = []
            for k in (0, 1):
                alpha = self.alphas[zi][k]
                aq = frac_to_q(alpha)
                T = [frac_to_q(Fraction(zone.initial_temp))]
                for t in range(n):
                    nt = z3.Real(f"T_z{zi}_a{k}_{t + 1}")
                    # 精确递推：T(t+1) = (1-alpha)*T(t) + alpha*U(t+1)
                    s.add(nt == (1 - alpha) * T[t] + aq * U[t])
                    T.append(nt)
                # 初温及每一分钟末温度不得超过上限
                for t in range(n + 1):
                    s.add(T[t] <= zone.upper_limit)
                # 终温闭区间
                s.add(T[n] >= zone.final_low, T[n] <= zone.final_high)
                # 热暴露量达标
                exposure = z3.Sum([
                    z3.If(T[t] > zone.exposure_threshold,
                          T[t] - zone.exposure_threshold, 0)
                    for t in range(1, n + 1)
                ])
                s.add(exposure >= frac_to_q(self.exposure_min[zi]))
                traj_k.append(T)
            temps.append(traj_k)
        return s, U, temps


def _eval_uset(model: z3.ModelRef, U: List[z3.ArithRef]) -> List[int]:
    return [model.eval(u, model_completion=True).as_long() for u in U]


def simulate(req: SolveRequest, setpoints: List[int]) -> List[Dict[str, Any]]:
    """用 Python Fraction 按公式精确递推，独立复核 Z3 结果并计算各项余量。"""
    n = req.duration
    result: List[Dict[str, Any]] = []
    for zi, zone in enumerate(req.zones):
        for k, alpha_dec in enumerate((zone.alpha1, zone.alpha2)):
            alpha = dec_to_fraction(alpha_dec)
            T = [Fraction(zone.initial_temp)]
            for t in range(n):
                T.append(T[t] + alpha * (Fraction(setpoints[t]) - T[t]))
            excess = [Fraction(0)] + [
                max(Fraction(0), x - zone.exposure_threshold) for x in T[1:]
            ]
            exposure = sum(excess[1:], Fraction(0))
            points: List[Dict[str, Any]] = []
            violations: List[str] = []
            for t in range(n + 1):
                upper_margin = Fraction(zone.upper_limit) - T[t]
                if T[t] > zone.upper_limit:
                    violations.append(f"t={t} 温度 {fmt_frac(T[t], 4)}℃ 超过上限")
                point: Dict[str, Any] = {
                    "minute": t,
                    "setpoint": setpoints[t - 1] if t >= 1 else None,
                    "temp": fmt_frac(T[t]),
                    "excess": fmt_frac(excess[t], 4),
                    "upper_margin": fmt_frac(upper_margin, 4),
                    "final_low_margin": None,
                    "final_high_margin": None,
                    "ramp_margin": None,
                }
                if t >= 1:
                    if t == n:
                        lo_m = T[t] - zone.final_low
                        hi_m = zone.final_high - T[t]
                        point["final_low_margin"] = fmt_frac(lo_m, 4)
                        point["final_high_margin"] = fmt_frac(hi_m, 4)
                        if T[t] < zone.final_low:
                            violations.append(
                                f"终温 {fmt_frac(T[t], 4)}℃ 低于区间下限 {zone.final_low}")
                        if T[t] > zone.final_high:
                            violations.append(
                                f"终温 {fmt_frac(T[t], 4)}℃ 高于区间上限 {zone.final_high}")
                    if t >= 2:
                        jump = abs(setpoints[t - 1] - setpoints[t - 2])
                        point["ramp_margin"] = fmt_frac(
                            Fraction(req.max_ramp - jump), 4)
                points.append(point)
            # 跃变约束复核
            for t in range(1, n):
                jump = abs(setpoints[t] - setpoints[t - 1])
                if jump > req.max_ramp:
                    violations.append(
                        f"t={t + 1} 设定温度跃变 {jump}℃ 超过允许 {req.max_ramp}℃")
            exp_margin = exposure - dec_to_fraction(zone.exposure_min)
            if exp_margin < 0:
                violations.append(
                    f"热暴露量 {fmt_frac(exposure, 4)} 未达到最低值 "
                    f"{fmt_frac(dec_to_fraction(zone.exposure_min), 4)}")
            result.append({
                "zone": zone.name,
                "alpha": f"{alpha_dec:.2f}",
                "upper_limit": zone.upper_limit,
                "final_low": zone.final_low,
                "final_high": zone.final_high,
                "exposure_threshold": zone.exposure_threshold,
                "exposure": fmt_frac(exposure, 4),
                "exposure_min": f"{zone.exposure_min:.2f}",
                "exposure_margin": fmt_frac(exp_margin, 4),
                "points": points,
                "violations": violations,
            })
    return result


def _feasible(setpoints: List[int], req: SolveRequest) -> bool:
    """用 Fraction 精确递推独立复核候选曲线是否满足全部硬约束。

    Z3 Optimize 在超时（unknown）时返回的模型不保证满足硬约束，
    因此任何候选 U 都必须经过本函数复核后才能返回给前端。
    """
    if len(setpoints) != req.duration:
        return False
    if any(not isinstance(u, int) or not (0 <= u <= 300) for u in setpoints):
        return False
    for t in range(1, req.duration):
        if abs(setpoints[t] - setpoints[t - 1]) > req.max_ramp:
            return False
    locked = {lk.minute: lk.value for lk in req.locks}
    if any(setpoints[t - 1] != v for t, v in locked.items()):
        return False
    trajs = simulate(req, setpoints)
    return all(not tr["violations"] for tr in trajs)


def solve(req: SolveRequest) -> Dict[str, Any]:
    """执行求解，返回可直接序列化为 SolveResponse 的字典。"""
    start = time.monotonic()

    def elapsed_ms() -> int:
        return int((time.monotonic() - start) * 1000)

    def respond(status: str, **kw: Any) -> Dict[str, Any]:
        out = {
            "status": status,
            "status_text": STATUS_TEXT[status],
            "optimal": None,
            "elapsed_ms": elapsed_ms(),
            "timed_out": status in (FEASIBLE_NOT_OPTIMAL, NO_FEASIBLE_FOUND),
            "setpoints": [],
            "objective_sum": None,
            "trajectories": [],
            "reason": None,
        }
        out.update(kw)
        out["elapsed_ms"] = elapsed_ms()
        return out

    try:
        m = _Model(req)
        base_solver, U, _temps = m.build()

        # ---- 阶段 A：可行性（给足几乎全部预算）----
        # 对难实例（如 N=24），单纯可行性本身就要 ~5s；必须先拿到一条
        # 经过验证的可行曲线，阶段 B 超时回退才有东西可给。
        a_timeout = int((TOTAL_BUDGET_SEC - MARGIN_SEC) * 1000)
        a_solver = z3.Solver()
        a_solver.set("timeout", a_timeout)
        a_solver.add(*base_solver.assertions())
        a_res = a_solver.check()

        if a_res == z3.unsat:
            return respond(INFEASIBLE)

        feasible_setpoints: Optional[List[int]] = None
        if a_res == z3.sat:
            cand = _eval_uset(a_solver.model(), U)
            # 普通 Solver 的 sat 模型按理应可行，仍做一次防御性复核
            if _feasible(cand, req):
                feasible_setpoints = cand

        # ---- 阶段 B：字典序优化（只用剩余预算，至少保留 0.5s）----
        remaining = TOTAL_BUDGET_SEC - (time.monotonic() - start) - MARGIN_SEC
        if remaining < 0.5:
            if feasible_setpoints is not None:
                return respond(
                    FEASIBLE_NOT_OPTIMAL,
                    optimal=False,
                    setpoints=feasible_setpoints,
                    objective_sum=sum(feasible_setpoints),
                    trajectories=simulate(req, feasible_setpoints),
                )
            return respond(NO_FEASIBLE_FOUND)

        opt = z3.Optimize()
        opt.set(priority="lex")
        opt.set("timeout", int(remaining * 1000))
        opt.add(*base_solver.assertions())
        opt.minimize(z3.Sum(U))
        for u in U:
            opt.minimize(u)
        b_res = opt.check()

        if b_res == z3.unsat:
            # 优化器证伪，与阶段 A 冲突时以 unsat 为准
            return respond(INFEASIBLE)

        if b_res == z3.sat:
            cand = _eval_uset(opt.model(), U)
            if _feasible(cand, req):
                return respond(
                    FEASIBLE_OPTIMAL,
                    optimal=True,
                    setpoints=cand,
                    objective_sum=sum(cand),
                    trajectories=simulate(req, cand),
                )
            # sat 却复核不过属于内部异常，退回已知可行解
            if feasible_setpoints is not None:
                return respond(
                    FEASIBLE_NOT_OPTIMAL,
                    optimal=False,
                    setpoints=feasible_setpoints,
                    objective_sum=sum(feasible_setpoints),
                    trajectories=simulate(req, feasible_setpoints),
                )

        # b_res == unknown（超时）：incumbent 不保证可行，必须复核
        incumbent: Optional[List[int]] = None
        try:
            incumbent = _eval_uset(opt.model(), U)
        except z3.Z3Exception:
            incumbent = None

        # 选择“经复核可行且目标值更小”的候选
        best = feasible_setpoints
        if incumbent is not None and _feasible(incumbent, req):
            if best is None or sum(incumbent) < sum(best):
                best = incumbent
        if best is not None:
            return respond(
                FEASIBLE_NOT_OPTIMAL,
                optimal=False,
                setpoints=best,
                objective_sum=sum(best),
                trajectories=simulate(req, best),
            )
        return respond(NO_FEASIBLE_FOUND)
    except Exception as exc:  # pragma: no cover - 防御性
        return respond(ERROR, reason=f"{type(exc).__name__}: {exc}")


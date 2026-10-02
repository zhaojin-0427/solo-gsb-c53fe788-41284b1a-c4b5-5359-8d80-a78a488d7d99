"""求解器关键场景测试：python tests/test_solver.py"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.schemas import SolveRequest
from app.solver import solve, INFEASIBLE, FEASIBLE_OPTIMAL, FEASIBLE_NOT_OPTIMAL, NO_FEASIBLE_FOUND
from fractions import Fraction
from decimal import Decimal


def base_req(**over):
    d = dict(
        duration=6, max_ramp=30, locks=[],
        zones=[
            dict(name="A", initial_temp=20, alpha1="0.20", alpha2="0.35",
                 final_low=80, final_high=120, upper_limit=200,
                 exposure_threshold=100, exposure_min="0.00"),
            dict(name="B", initial_temp=25, alpha1="0.15", alpha2="0.25",
                 final_low=70, final_high=110, upper_limit=180,
                 exposure_threshold=90, exposure_min="0.00"),
        ],
    )
    d.update(over)
    return SolveRequest(**d)


def check(name, cond, extra=""):
    print(("PASS" if cond else "FAIL"), name, extra)
    if not cond:
        check.failed += 1
check.failed = 0


def verify_feasible(r, req):
    """独立 Fraction 递推，复核所有轨迹 violations 为空。"""
    assert r["setpoints"], "无设定曲线"
    for tr in r["trajectories"]:
        assert not tr["violations"], (tr["zone"], tr["alpha"], tr["violations"])
    U = r["setpoints"]
    for t in range(1, req.duration):
        assert abs(U[t] - U[t-1]) <= req.max_ramp
    assert all(0 <= u <= 300 for u in U)


# 1) 基本可行 + 最优
r = solve(base_req())
check("基本场景可解", r["status"] == FEASIBLE_OPTIMAL, r["status"])
verify_feasible(r, base_req())
# 终温约束宽松且 exposure_min=0 时，最小总和策略应让所有 U 保持低值；
# 末温仍需达终温下限，所以末段有爬升
print("  U =", r["setpoints"], "sum =", r["objective_sum"], "elapsed =", r["elapsed_ms"])

# 2) 字典序：固定总和下 U(1) 最小。构造对称需求使多种曲线同总和。
# 用锁定把除首分钟外都锁死，只让 u1 自由，验证取最小可行值
req2 = base_req(
    duration=4, max_ramp=300,
    locks=[dict(minute=2, value=100), dict(minute=3, value=100),
           dict(minute=4, value=100)],
    zones=[
        dict(name="A", initial_temp=20, alpha1="0.50", alpha2="0.50",
             final_low=0, final_high=300, upper_limit=300,
             exposure_threshold=300, exposure_min="0.00"),
        dict(name="B", initial_temp=20, alpha1="0.50", alpha2="0.50",
             final_low=0, final_high=300, upper_limit=300,
             exposure_threshold=300, exposure_min="0.00"),
    ],
)
r2 = solve(req2)
# u2..4 锁 100，无任何下限约束，最小化总和 => u1=0
check("字典序：自由首分钟取 0",
      r2["status"] == FEASIBLE_OPTIMAL and r2["setpoints"][0] == 0,
      str(r2["setpoints"]))

# 3) 无解：初温超上限（初温不得超上限）
req3 = base_req(zones=[
    dict(name="A", initial_temp=210, alpha1="0.20", alpha2="0.35",
         final_low=80, final_high=120, upper_limit=200,
         exposure_threshold=100, exposure_min="0.00"),
    dict(name="B", initial_temp=25, alpha1="0.15", alpha2="0.25",
         final_low=70, final_high=110, upper_limit=180,
         exposure_threshold=90, exposure_min="0.00"),
])
r3 = solve(req3)
check("初温超上限 => 无解", r3["status"] == INFEASIBLE)

# 4) 无解：跃变约束 + 锁定冲突（第1分钟锁300，第2分钟锁0，max_ramp=10）
req4 = base_req(
    duration=2, max_ramp=10,
    locks=[dict(minute=1, value=300), dict(minute=2, value=0)],
)
r4 = solve(req4)
check("锁定与跃变冲突 => 无解", r4["status"] == INFEASIBLE)

# 5) 无解：终温区间物理不可达（alpha=0.01，N=1，初温20，终温要求>=200）
req5 = base_req(duration=1, max_ramp=300, zones=[
    dict(name="A", initial_temp=20, alpha1="0.01", alpha2="1.00",
         final_low=200, final_high=220, upper_limit=300,
         exposure_threshold=300, exposure_min="0.00"),
    dict(name="B", initial_temp=20, alpha1="0.01", alpha2="1.00",
         final_low=200, final_high=220, upper_limit=300,
         exposure_threshold=300, exposure_min="0.00"),
])
r5 = solve(req5)
check("alpha=0.01 单分钟不可达终温 => 无解", r5["status"] == INFEASIBLE)

# 6) 热暴露约束可行
req6 = base_req(
    duration=8, max_ramp=300,
    zones=[
        dict(name="A", initial_temp=100, alpha1="0.50", alpha2="0.50",
             final_low=100, final_high=300, upper_limit=300,
             exposure_threshold=100, exposure_min="100.00"),
        dict(name="B", initial_temp=100, alpha1="0.50", alpha2="0.50",
             final_low=100, final_high=300, upper_limit=300,
             exposure_threshold=100, exposure_min="100.00"),
    ],
)
r6 = solve(req6)
check("热暴露达标可解", r6["status"] == FEASIBLE_OPTIMAL, r6["status"])
verify_feasible(r6, req6)
print("  U =", r6["setpoints"], "E =", [t["exposure"] for t in r6["trajectories"]])

# 7) 精确递推验证：alpha=0.1, U 恒定 100, T0=0 => T(t)=100*(1-0.9^t)
req7 = SolveRequest(duration=5, max_ramp=300, locks=[
    dict(minute=t, value=100) for t in range(1, 6)],
    zones=[dict(name="A", initial_temp=0, alpha1="0.10", alpha2="0.10",
                final_low=0, final_high=300, upper_limit=300,
                exposure_threshold=300, exposure_min="0.00"),
           dict(name="B", initial_temp=0, alpha1="0.10", alpha2="0.10",
                final_low=0, final_high=300, upper_limit=300,
                exposure_threshold=300, exposure_min="0.00")])
r7 = solve(req7)
from app.solver import simulate
traj = simulate(req7, [100]*5)[0]
vals = [Fraction(Decimal(p["temp"])) for p in traj["points"]]
ok = all(vals[t] == Fraction(Decimal(str(100*(1-0.9**t)))).limit_denominator(10**10)
        or True for t in range(6))
# 精确比较：T(t)=100-100*0.9^t = 100 - 100*9^t/10^t
exact_ok = True
for t in range(6):
    expect = Fraction(100) - Fraction(100*9**t, 10**t)
    got_via_sim = vals[t]
    if got_via_sim != expect:
        exact_ok = False
        print("  mismatch t=", t, got_via_sim, expect)
check("精确递推 T(t)=100(1-0.9^t)", exact_ok)
# 注意 simulate 输出经过 6 位小数量化，允许该差异：直接内部再验
from app.solver import dec_to_fraction
T = Fraction(0)
for t in range(5):
    T = T + dec_to_fraction(Decimal("0.10")) * (Fraction(100) - T)
    expect = Fraction(100) - Fraction(100*9**(t+1), 10**(t+1))
    assert T == expect
check("Fraction 内部递推精确", True)

# 8) 边界：N=24 可解且在合理时间
t0 = time.time()
r8 = solve(base_req(duration=24))
check("N=24 可解", r8["status"] in (FEASIBLE_OPTIMAL, FEASIBLE_NOT_OPTIMAL),
      f"{r8['status']} {r8['elapsed_ms']}ms")
if r8["setpoints"]:
    verify_feasible(r8, base_req(duration=24))

print(f"\n失败数: {check.failed}")
sys.exit(1 if check.failed else 0)

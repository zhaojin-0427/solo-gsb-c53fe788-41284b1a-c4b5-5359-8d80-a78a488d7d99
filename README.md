# 双区烘箱曲线试算（Dual-Zone Oven Curve Solver）

给定两区烘箱的初温、两种响应系数、终温区间、全程温度上限、热暴露阈值与最低累计
热暴露值，以及一条**两区共享的设定温度曲线**，使用 **Z3 SMT 求解器**求一条同时
满足全部四条温度轨迹（两区 × 两种系数）约束的设定曲线，并按字典序优化。

- 后端：Python 3.11 · FastAPI · SQLite · Z3（z3-solver）
- 前端：原生 HTML / CSS / JavaScript（无构建步骤）
- 部署：Docker Compose 一键启动

## 递推模型与约束

对每一区、每一种响应系数 α（共 4 条轨迹）精确递推（使用有理数，无浮点误差）：

```
T(0) = 初温
T(t+1) = T(t) + α · (U(t+1) − T(t))        t = 0 … N−1
热暴露量 E = Σ_{t=1..N} max(0, T(t) − 阈值)
```

决策变量为共享设定温度 `U(1)…U(N)`（0～300 的整数）。约束：

| 约束 | 说明 |
|---|---|
| 设定范围 | `0 ≤ U(t) ≤ 300`，整数 |
| 相邻跃变 | `|U(t) − U(t−1)| ≤ 最大跃变`（非负整数） |
| 分钟锁定 | 指定分钟的 `U(t)` 等于锁定值（同样受跃变约束） |
| 温度上限 | 初温及**每一分钟末温度** `T(t) ≤ 全程上限` |
| 终温区间 | `终温下限 ≤ T(N) ≤ 终温上限`（闭区间） |
| 热暴露 | `E ≥ 最低累计热暴露值` |

**优化目标（字典序）**：

1. 先最小化设定温度总和 `Σ U(t)`；
2. 在总和相同的前提下，按分钟序依次最小化 `U(1), U(2), …, U(N)`
   （即越靠前的分钟越优先取小值）。

## 输入参数

- 烘烤时长 N：**1～24 的整数（分钟）**
- 初温：每区 0～300℃ 整数
- 响应系数：每区两种，**0.01～1.00、至多两位小数**（如 `0.20`、`1.00`）
- 终温闭区间：0～300℃ 整数（下限 ≤ 上限）
- 全程温度上限：0～300℃ 整数
- 热暴露阈值：0～300℃ 整数
- 非负最低累计热暴露值：≥ 0、至多两位小数
- 共享设定温度：0～300℃ 整数；相邻分钟跃变不超过给定非负整数；可锁定部分分钟

> α 以两位小数的精确有理数参与计算，页面与复核均基于 `Fraction`，不存在
> `0.1 + 0.2` 式浮点误差。

## 求解限时与三种结果

每次求解的墙上时间预算为 **10 秒**，页面横幅明确区分：

| 状态 | 含义 |
|---|---|
| **已证最优**（绿） | 在限时内找到可行曲线，并完成字典序最优性证明 |
| **可行但未证最优**（黄） | 已找到满足全部硬约束的曲线（可直接使用），但限时内未能证明其设定总和最小 |
| **尚未找到曲线**（红） | 10 秒内未找到任何可行曲线；**这不等同于无解**，可放宽约束后重试 |
| **无解**（紫） | Z3 已**证明**约束互相冲突，任何曲线都无法满足（如初温超上限、锁定与跃变冲突、终温物理不可达等） |

内部采用两阶段求解：

1. **可行性阶段**：普通 `z3.Solver` 先找一条可行曲线（对困难实例如 N=24，
   可行性本身可能耗时数秒）；
2. **优化阶段**：`z3.Optimize`（`priority=lex`）用剩余预算证明字典序最优。

> 注意：Z3 的 Optimize 在超时（`unknown`）时返回的模型**不保证满足硬约束**。
> 本应用对任何候选曲线都用 Python `Fraction` 按物理公式**独立复核**（范围、
> 跃变、锁定、上限、终温区间、热暴露），只有复核通过的曲线才会返回前端；
> 不通过则回退到可行性阶段的曲线，或如实报告“尚未找到曲线”。

## 页面展示

- 共享设定温度表：逐分钟 `U(t)`、与上一分钟的变化 `|ΔU|`、**跃变余量**
  `最大跃变 − |ΔU|`，并标出锁定分钟；
- 四条温度轨迹表（按区与 α 分组）：`t`、`U(t)`、精确递推温度 `T(t)`、
  超标量 `max(0,T−阈值)`、**上限余量**、仅末分钟的**终温区间下/上余量**；
- 表脚给出热暴露量与**达标余量**（`E − 最低累计值`）；
- 余量为负时以红色高亮（若出现即代表该约束被违反，正常结果不应出现）；
- 结果（输入 + 求解输出）可**保存为快照**，存入 SQLite，可随时载入复现或删除。

## 一键启动（Docker Compose）

前置：已安装 Docker 与 Docker Compose（v2）。

```bash
docker compose up -d --build
```

启动后浏览器访问：

```
http://localhost:8000
```

- 健康检查：<http://localhost:8000/api/health>
- API 文档（Swagger UI）：<http://localhost:8000/docs>

停止与清理：

```bash
docker compose logs -f        # 查看日志
docker compose down           # 停止并移除容器
docker compose down -v        # 同时删除快照数据卷
```

快照保存在 Docker 命名卷 `oven-data`（容器内 `/data/oven.db`）中，容器重建
不丢失。主机端口如需修改，编辑 `docker-compose.yml` 的 `ports`。

## 本地开发运行（不使用 Docker）

需要 Python 3.11+：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 可选：自定义 SQLite 路径（默认 ./data/oven.db）
export OVEN_DB_PATH=./data/oven.db

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 <http://localhost:8000>。

运行求解器场景测试：

```bash
python tests/test_solver.py
```

## HTTP 接口摘要

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/solve` | 提交参数求解（10 秒限时） |
| POST | `/api/snapshots` | 保存一次试算快照 |
| GET | `/api/snapshots` | 快照列表 |
| GET | `/api/snapshots/{id}` | 快照详情（含完整输入与逐分钟轨迹） |
| DELETE | `/api/snapshots/{id}` | 删除快照 |
| GET | `/api/health` | 健康检查 |

`POST /api/solve` 请求体示例：

```json
{
  "duration": 10,
  "max_ramp": 20,
  "locks": [{"minute": 5, "value": 120}],
  "zones": [
    {"name": "A区", "initial_temp": 20, "alpha1": "0.20", "alpha2": "0.35",
     "final_low": 140, "final_high": 160, "upper_limit": 200,
     "exposure_threshold": 100, "exposure_min": "300.00"},
    {"name": "B区", "initial_temp": 25, "alpha1": "0.15", "alpha2": "0.25",
     "final_low": 120, "final_high": 140, "upper_limit": 180,
     "exposure_threshold": 90, "exposure_min": "200.00"}
  ]
}
```

## 目录结构

```
.
├── app/
│   ├── main.py          # FastAPI 路由与静态托管
│   ├── schemas.py       # Pydantic 输入/输出模型与参数校验
│   ├── solver.py        # Z3 两阶段求解 + Fraction 精确递推/复核/余量
│   ├── database.py      # SQLite 快照存储
│   └── static/          # 原生前端（index.html / style.css / app.js）
├── tests/test_solver.py # 求解器场景测试
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

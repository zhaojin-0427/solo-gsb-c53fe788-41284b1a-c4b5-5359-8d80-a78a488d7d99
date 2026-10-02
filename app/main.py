"""FastAPI 入口：求解、快照、静态页面。"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import database
from .schemas import SnapshotSaveRequest, SnapshotSummary, SolveRequest, SolveResponse
from .solver import solve

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    yield


app = FastAPI(title="双区烘箱曲线试算", version="1.0.0", lifespan=lifespan)


@app.get("/api/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/api/solve", response_model=SolveResponse)
def api_solve(req: SolveRequest) -> Dict[str, Any]:
    # 求解为 CPU 密集型；规模很小（<=24 分钟），直接在线程外的主事件循环中
    # 同步执行会阻塞，因此用普通 def 路由——FastAPI 会自动放到线程池执行。
    return solve(req)


@app.post("/api/snapshots", status_code=201)
def api_save_snapshot(body: SnapshotSaveRequest) -> Dict[str, Any]:
    sid = database.save_snapshot(
        body.name,
        body.request.model_dump(mode="json"),
        body.result.model_dump(mode="json"),
    )
    return {"id": sid}


@app.get("/api/snapshots", response_model=list[SnapshotSummary])
def api_list_snapshots() -> list[Dict[str, Any]]:
    return database.list_snapshots()


@app.get("/api/snapshots/{snapshot_id}")
def api_get_snapshot(snapshot_id: int) -> Dict[str, Any]:
    snap = database.get_snapshot(snapshot_id)
    if snap is None:
        raise HTTPException(status_code=404, detail="快照不存在")
    return snap


@app.delete("/api/snapshots/{snapshot_id}")
def api_delete_snapshot(snapshot_id: int) -> Dict[str, bool]:
    ok = database.delete_snapshot(snapshot_id)
    if not ok:
        raise HTTPException(status_code=404, detail="快照不存在")
    return {"deleted": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(os.path.join(STATIC_DIR, "index.html"))


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

"""
FastAPI: REST + WebSocket /ws.
Planning: /instances, /upload, /run, /result/{id}
Monitoring: /monitor/start, /monitor/stop
Run: PYTHONPATH=. uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from queue import Empty
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import job_manager
from backend.kafka_bridge import start_kafka_forwarder
from backend.realtime import outbound_queue
from backend.monitor_context import build_monitor_context
from backend.telemetry_alert_worker import start_telemetry_alert_worker

INSTANCES_DIR = ROOT / "src" / "data" / "irp-instances"

app = FastAPI(title="IRP-TW-DT API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class RunIn(BaseModel):
    scenario: str = Field(..., pattern="^[PABC]$")
    seed: int = 42
    pop_size: int = 50
    generations: int = 200
    time_limit: float = 300.0
    source: str = Field(..., pattern="^(builtin|upload)$")
    instance_key: Optional[str] = None
    upload_token: Optional[str] = None


class MonitorStartIn(BaseModel):
    run_id: str
    day: int = Field(ge=0, le=6)
    speed_x: int = Field(default=60, ge=1, le=600, description="60=default replay rate; lower=slower, higher=faster")


class MonitorStopIn(BaseModel):
    run_id: str


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self._connections:
            self._connections.remove(websocket)

    async def broadcast_json(self, data: Dict[str, Any]) -> None:
        stale: List[WebSocket] = []
        for ws in self._connections:
            try:
                await ws.send_json(data)
            except Exception:
                stale.append(ws)
        for ws in stale:
            self.disconnect(ws)


manager = ConnectionManager()


@app.on_event("startup")
async def _startup() -> None:
    start_kafka_forwarder()
    start_telemetry_alert_worker()
    asyncio.create_task(_pump_outbound_queue())


async def _pump_outbound_queue() -> None:
    loop = asyncio.get_event_loop()
    while True:
        try:
            item = await loop.run_in_executor(None, _queue_get_timeout, 0.2)
        except Exception:
            item = None
        if item is not None:
            await manager.broadcast_json(item)
        else:
            await asyncio.sleep(0.05)


def _queue_get_timeout(timeout: float) -> Optional[Dict[str, Any]]:
    try:
        return outbound_queue.get(timeout=timeout)
    except Empty:
        return None


@app.get("/instances")
def list_instances() -> Dict[str, Any]:
    if not INSTANCES_DIR.is_dir():
        return {"instances": []}
    names = sorted(
        d.name
        for d in INSTANCES_DIR.iterdir()
        if d.is_dir() and (d / "meta.json").is_file()
    )
    return {"instances": names}


@app.post("/upload")
async def upload_instance(
    file: UploadFile = File(...),
    depot_lon: Optional[float] = Form(None),
    depot_lat: Optional[float] = Form(None),
    n: Optional[int] = Form(None),
    m: Optional[int] = Form(None),
) -> Dict[str, Any]:
    from src.data import upload_loader

    raw = await file.read()
    fname = (file.filename or "").lower()
    try:
        if fname.endswith(".csv"):
            if depot_lon is None or depot_lat is None or n is None or m is None:
                raise HTTPException(
                    status_code=400,
                    detail="CSV upload requires depot_lon, depot_lat, n, m",
                )
            inst, _dist = upload_loader.load_from_csv(
                raw, float(depot_lon), float(depot_lat), int(n), int(m)
            )
        else:
            inst, _dist = upload_loader.load_from_json(raw)
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    token = str(uuid.uuid4())
    job_manager.register_upload_instance(token, inst)
    return {
        "upload_token": token,
        "n": inst.n,
        "m": inst.m,
        "T": inst.T,
        "name": inst.name,
    }


@app.post("/run")
def start_run(body: RunIn) -> Dict[str, str]:
    if body.source == "builtin":
        if not body.instance_key:
            raise HTTPException(400, "instance_key required for builtin")
        from src.data.generator import load_instance as _load_instance

        path = INSTANCES_DIR / body.instance_key
        if not path.is_dir():
            raise HTTPException(404, f"Unknown instance: {body.instance_key}")
        try:
            inst = _load_instance(str(path))
        except Exception as e:
            raise HTTPException(400, str(e)) from e
        scale = body.instance_key.split("_")[0] if "_" in body.instance_key else "custom"
    else:
        if not body.upload_token:
            raise HTTPException(400, "upload_token required for upload")
        inst = job_manager.pop_upload_instance(body.upload_token)
        if inst is None:
            raise HTTPException(400, "Invalid or expired upload_token")
        scale = "upload"

    job = job_manager.create_job()
    job_manager.start_run_thread(
        job,
        instance=inst,
        scenario=body.scenario,
        scale=scale,
        seed=body.seed,
        pop_size=body.pop_size,
        generations=body.generations,
        time_limit=body.time_limit,
    )
    return {"run_id": job.run_id}


@app.post("/monitor/start")
def monitor_start(body: MonitorStartIn) -> Dict[str, str]:
    job = job_manager.get_job(body.run_id)
    if job is None:
        raise HTTPException(404, "Unknown run_id")
    if job.state != job_manager.JobState.COMPLETE:
        raise HTTPException(409, "Planning run not complete yet")
    if not job.run_dir:
        raise HTTPException(500, "Run directory missing")
    art = os.path.join(job.run_dir, "artifacts.pkl")
    if not os.path.isfile(art):
        raise HTTPException(400, "No artifacts.pkl for this run (re-run planning)")
    hours_per_real_second = max(0.05, body.speed_x / 60.0)
    try:
        job_manager.start_monitor_replay_thread(
            body.run_id, day=body.day, hours_per_real_second=hours_per_real_second
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return {"status": "started"}


@app.post("/monitor/stop")
def monitor_stop(body: MonitorStopIn) -> Dict[str, str]:
    if job_manager.get_job(body.run_id) is None:
        raise HTTPException(404, "Unknown run_id")
    job_manager.stop_monitor_replay(body.run_id)
    return {"status": "stopped"}


@app.get("/monitor/context")
def monitor_context(run_id: str = Query(...), day: int = Query(0, ge=0, le=30)) -> JSONResponse:
    """Depot, customer stops, planned route polylines, and suggested time window for the monitoring UI."""
    job = job_manager.get_job(run_id)
    if job is None:
        raise HTTPException(404, "Unknown run_id")
    if not job.run_dir:
        raise HTTPException(500, "Run directory missing")
    art = os.path.join(job.run_dir, "artifacts.pkl")
    if not os.path.isfile(art):
        raise HTTPException(400, "No artifacts.pkl for this run")
    try:
        payload = build_monitor_context(job.run_dir, day)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return JSONResponse(content=json.loads(json.dumps(payload, default=str)))


@app.get("/result/{run_id}")
def get_result(run_id: str) -> JSONResponse:
    job = job_manager.get_job(run_id)
    if job is None:
        raise HTTPException(404, "Unknown run_id")
    if job.state == job_manager.JobState.ERROR:
        return JSONResponse(
            status_code=500,
            content={"error": job.error or "Run failed", "state": job.state.value},
        )
    if job.state != job_manager.JobState.COMPLETE:
        return JSONResponse(
            status_code=202,
            content={"state": job.state.value},
        )
    # JSON-serialize result (numpy etc.)
    def _default(o: Any) -> Any:
        if hasattr(o, "item"):
            return o.item()
        raise TypeError

    payload = {
        "state": job.state.value,
        "result": json.loads(json.dumps(job.result, default=str)),
        "map_html": job.map_html,
    }
    return JSONResponse(content=payload)


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket) -> None:
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}

"""
End-to-end: Planning (POST /run → GET /result) + Monitoring (POST /monitor/start → WS sim_complete).

Requires: repo root on PYTHONPATH, built-in instances under src/data/irp-instances/.
Optional: Kafka for telemetry/convergence on WebSocket; sim_complete is always broadcast from app queue.

Run (from repo root):
  PYTHONPATH=. pytest tests/test_e2e_stack.py -v --tb=short
"""

from __future__ import annotations

import os
import queue
import threading
import time
import uuid

import pytest
from fastapi.testclient import TestClient


def _find_artifacts_pkl(run_root: str) -> bool:
    for root, _, files in os.walk(run_root):
        if "artifacts.pkl" in files:
            return True
    return False


def _ws_pump(ws, q: queue.Queue) -> None:
    try:
        while True:
            q.put(ws.receive_json())
    except Exception:
        pass


@pytest.fixture
def replay_no_osrm(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay calls OSRM per leg; stub so E2E finishes without many HTTP round-trips."""

    def _no_geom(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "src.simulation.replay.get_osrm_route_geometry",
        _no_geom,
    )


@pytest.fixture(scope="module")
def client():
    from backend.main import app

    with TestClient(app) as c:
        yield c


def test_e2e_health_and_instances(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/instances")
    assert r.status_code == 200
    names = r.json().get("instances") or []
    assert len(names) >= 1


def test_e2e_planning_then_monitoring_ws(
    client: TestClient, replay_no_osrm: None
) -> None:
    runs_root = os.environ.get("IRP_RUNS_DIR", "/tmp/irp_runs")
    inst = client.get("/instances").json()
    names = inst.get("instances") or []
    key = "S_n20_seed42" if "S_n20_seed42" in names else names[0]

    pr = client.post(
        "/run",
        json={
            "scenario": "P",
            "seed": 42,
            "pop_size": 10,
            "generations": 5,
            "time_limit": 60.0,
            "source": "builtin",
            "instance_key": key,
        },
    )
    assert pr.status_code == 200, pr.text
    run_id = pr.json()["run_id"]
    assert uuid.UUID(run_id)

    deadline = time.monotonic() + 300.0
    got_complete = False
    while time.monotonic() < deadline:
        rr = client.get(f"/result/{run_id}")
        if rr.status_code == 200:
            body = rr.json()
            assert body.get("state") == "complete"
            assert "result" in body
            assert "total_cost" in body["result"]
            got_complete = True
            break
        assert rr.status_code == 202
        time.sleep(0.3)
    assert got_complete, "Planning /result timeout"

    run_root = os.path.join(runs_root, run_id)
    assert os.path.isdir(run_root), f"missing {run_root}"
    assert _find_artifacts_pkl(run_root), "artifacts.pkl not found under run dir"

    with client.websocket_connect("/ws") as ws:
        q: queue.Queue = queue.Queue()
        pump = threading.Thread(target=_ws_pump, args=(ws, q), daemon=True)
        pump.start()
        try:
            ms = client.post(
                "/monitor/start",
                json={"run_id": run_id, "day": 0, "speed_x": 600},
            )
            assert ms.status_code == 200, ms.text

            deadline2 = time.monotonic() + 400.0
            saw_sim = False
            while time.monotonic() < deadline2:
                try:
                    m = q.get(timeout=0.5)
                except queue.Empty:
                    continue
                if m.get("type") == "sim_complete" and m.get("run_id") == run_id:
                    saw_sim = True
                    break
                if m.get("type") == "monitor_error" and m.get("run_id") == run_id:
                    pytest.fail(f"monitor_error: {m.get('message')}")
            assert saw_sim, "WebSocket did not receive sim_complete in time"

            client.post("/monitor/stop", json={"run_id": run_id})
        finally:
            ws.close()

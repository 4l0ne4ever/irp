#!/usr/bin/env python3
"""
Product-style E2E: real HTTP + WebSocket to a running uvicorn (not TestClient).

Expects backend at --base-url (default http://127.0.0.1:8000).
For fast monitoring replay, start uvicorn with IRP_E2E_REPLAY_NO_OSRM=1 (see run_e2e_product.sh).
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import sys
import time
import uuid
from typing import Any, Dict
from urllib.parse import urlparse

import requests
import websockets


def _ws_url(base_http: str) -> str:
    u = urlparse(base_http.rstrip("/"))
    scheme = "wss" if u.scheme == "https" else "ws"
    return f"{scheme}://{u.netloc}/ws"


def _planning(base: str, instance_key: str) -> str:
    s = requests.Session()
    h = s.get(f"{base}/health", timeout=10)
    h.raise_for_status()
    if h.json() != {"status": "ok"}:
        raise RuntimeError(f"unexpected /health: {h.text}")

    pr = s.post(
        f"{base}/run",
        json={
            "scenario": "P",
            "seed": 42,
            "pop_size": 10,
            "generations": 5,
            "time_limit": 60.0,
            "source": "builtin",
            "instance_key": instance_key,
        },
        timeout=30,
    )
    pr.raise_for_status()
    run_id = pr.json()["run_id"]
    uuid.UUID(run_id)

    deadline = time.monotonic() + 300.0
    while time.monotonic() < deadline:
        rr = s.get(f"{base}/result/{run_id}", timeout=30)
        if rr.status_code == 200:
            body = rr.json()
            if body.get("state") != "complete":
                raise RuntimeError(body)
            if "total_cost" not in (body.get("result") or {}):
                raise RuntimeError("missing total_cost in result")
            return run_id
        if rr.status_code != 202:
            rr.raise_for_status()
        time.sleep(0.3)
    raise TimeoutError("Planning /result timeout")


async def _monitoring_ws(base: str, run_id: str) -> None:
    ws_url = _ws_url(base)
    q: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()

    async def drain(ws: Any) -> None:
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8")
                await q.put(json.loads(raw))
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    async with websockets.connect(ws_url, open_timeout=15) as ws:
        reader = asyncio.create_task(drain(ws))
        try:
            r = await asyncio.to_thread(
                requests.post,
                f"{base}/monitor/start",
                json={"run_id": run_id, "day": 0, "speed_x": 600},
                timeout=30,
            )
            if r.status_code != 200:
                raise RuntimeError(f"/monitor/start {r.status_code}: {r.text}")

            deadline = time.monotonic() + 400.0
            while time.monotonic() < deadline:
                try:
                    m = await asyncio.wait_for(q.get(), timeout=0.5)
                except asyncio.TimeoutError:
                    continue
                if m.get("type") == "sim_complete" and m.get("run_id") == run_id:
                    await asyncio.to_thread(
                        requests.post,
                        f"{base}/monitor/stop",
                        json={"run_id": run_id},
                        timeout=15,
                    )
                    return
                if m.get("type") == "monitor_error" and m.get("run_id") == run_id:
                    raise RuntimeError(f"monitor_error: {m.get('message')}")
            raise TimeoutError("WebSocket did not receive sim_complete in time")
        finally:
            reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await reader


def main() -> int:
    parser = argparse.ArgumentParser(description="E2E against live FastAPI")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="API root URL")
    args = parser.parse_args()
    base = args.base_url.rstrip("/")

    inst = requests.get(f"{base}/instances", timeout=15)
    inst.raise_for_status()
    names = inst.json().get("instances") or []
    if not names:
        print("No built-in instances", file=sys.stderr)
        return 2
    key = "S_n20_seed42" if "S_n20_seed42" in names else names[0]

    run_id = _planning(base, key)
    print(f"planning ok run_id={run_id}")

    asyncio.run(_monitoring_ws(base, run_id))
    print("monitoring ok (sim_complete)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

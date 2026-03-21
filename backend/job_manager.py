"""
Planning: background solver only → run_complete.
Monitoring: optional replay per day via /monitor/start, stoppable via /monitor/stop.
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, Optional

from backend.realtime import outbound_queue

logger = logging.getLogger(__name__)

RUNS_ROOT = os.environ.get("IRP_RUNS_DIR", "/tmp/irp_runs")
KEEP_RECENT = 10


class JobState(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETE = "complete"
    ERROR = "error"


@dataclass
class Job:
    run_id: str
    state: JobState = JobState.PENDING
    result: Optional[Dict[str, Any]] = None
    map_html: Optional[str] = None
    run_dir: Optional[str] = None
    error: Optional[str] = None


_jobs: Dict[str, Job] = {}
_upload_tokens: Dict[str, Any] = {}
_lock = threading.Lock()
_monitor_stop_events: Dict[str, threading.Event] = {}


def register_upload_instance(token: str, inst) -> None:
    with _lock:
        _upload_tokens[token] = inst


def pop_upload_instance(token: str):
    with _lock:
        return _upload_tokens.pop(token, None)


def create_job() -> Job:
    run_id = str(uuid.uuid4())
    job = Job(run_id=run_id)
    with _lock:
        _jobs[run_id] = job
    return job


def get_job(run_id: str) -> Optional[Job]:
    with _lock:
        return _jobs.get(run_id)


def _cleanup_runs() -> None:
    base = RUNS_ROOT
    if not os.path.isdir(base):
        return
    dirs = sorted(
        [os.path.join(base, d) for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))],
        key=lambda p: os.path.getmtime(p),
        reverse=True,
    )
    for d in dirs[KEEP_RECENT:]:
        try:
            shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass


def stop_monitor_replay(run_id: str) -> bool:
    with _lock:
        ev = _monitor_stop_events.get(run_id)
    if ev is None:
        return False
    ev.set()
    return True


def start_monitor_replay_thread(
    run_id: str,
    *,
    day: int,
    hours_per_real_second: float,
) -> None:
    job = get_job(run_id)
    if job is None or job.state != JobState.COMPLETE or not job.run_dir:
        raise ValueError("invalid job for monitoring")
    run_dir = job.run_dir

    stop_ev = threading.Event()
    with _lock:
        old = _monitor_stop_events.get(run_id)
        if old is not None:
            old.set()
        _monitor_stop_events[run_id] = stop_ev

    def _work() -> None:
        cancelled = False
        try:
            from src.experiments.runner import load_planning_artifacts
            from src.simulation.replay import run_simulation_replay

            inst, sol = load_planning_artifacts(run_dir)
            cancelled = bool(
                run_simulation_replay(
                    inst,
                    sol,
                    run_id,
                    day=day,
                    hours_per_real_second=hours_per_real_second,
                    stop_event=stop_ev,
                )
            )
        except Exception as e:
            logger.exception("Monitor replay failed")
            outbound_queue.put(
                {"type": "monitor_error", "run_id": run_id, "day": day, "message": str(e)}
            )
        finally:
            with _lock:
                if _monitor_stop_events.get(run_id) is stop_ev:
                    _monitor_stop_events.pop(run_id, None)
            outbound_queue.put(
                {
                    "type": "sim_complete",
                    "run_id": run_id,
                    "day": day,
                    "cancelled": cancelled,
                }
            )

    threading.Thread(target=_work, daemon=True, name=f"mon-{run_id[:8]}-d{day}").start()


def start_run_thread(
    job: Job,
    *,
    instance,
    scenario: str,
    scale: str,
    seed: int,
    pop_size: int,
    generations: int,
    time_limit: float,
) -> None:
    out_dir = os.path.join(RUNS_ROOT, job.run_id)
    os.makedirs(out_dir, exist_ok=True)

    def _work() -> None:
        try:
            with _lock:
                job.state = JobState.RUNNING
            from src.experiments.runner import run_single_from_instance

            result, run_dir, _sol = run_single_from_instance(
                instance,
                scenario=scenario,
                scale=scale,
                seed=seed,
                pop_size=pop_size,
                generations=generations,
                time_limit=time_limit,
                output_dir=out_dir,
                run_id=job.run_id,
            )
            map_path = os.path.join(run_dir, "map.html")
            map_html = None
            if os.path.isfile(map_path):
                with open(map_path, "r", encoding="utf-8") as f:
                    map_html = f.read()
            with _lock:
                job.result = result
                job.map_html = map_html
                job.run_dir = run_dir
                job.state = JobState.COMPLETE
            outbound_queue.put({"type": "run_complete", "run_id": job.run_id})
            _cleanup_runs()
        except Exception as e:
            logger.exception("Run failed")
            with _lock:
                job.state = JobState.ERROR
                job.error = str(e)
            outbound_queue.put(
                {"type": "run_error", "run_id": job.run_id, "message": str(e)}
            )

    threading.Thread(target=_work, daemon=True, name=f"job-{job.run_id[:8]}").start()

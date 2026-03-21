"""
Planning: background solver only → run_complete.
Monitoring: optional replay per day via /monitor/start, stoppable via /monitor/stop.
Re-plan: warm-start HGA for B/C runs with stored chromosome (see /monitor/replan).
"""

from __future__ import annotations

import logging
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional

from backend.realtime import outbound_queue
from backend.traffic_state import traffic_store

logger = logging.getLogger(__name__)

RUNS_ROOT = os.environ.get("IRP_RUNS_DIR", "/tmp/irp_runs")
KEEP_RECENT = 10

REPLAN_COOLDOWN_S = 120.0
REPLAN_POP_SIZE = 30
REPLAN_GENERATIONS = 60
REPLAN_TIME_LIMIT_S = 90.0


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
    traffic_model: str = "igp"
    plan_revision: int = 0
    replan_cooldown_until: float = 0.0
    replan_in_progress: bool = False
    plan_revision_updated_at: Optional[str] = None


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


def _remaining_stops_count(sol, day: int, sim_time_h: float) -> int:
    n = 0
    for route in sol.schedule[day]:
        for _c, _q, arr in route.stops:
            if float(arr) > float(sim_time_h):
                n += 1
    return n


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

            def _traffic_meta():
                return {"traffic_meta": traffic_store.snapshot_dict()}

            adaptive = job.traffic_model in ("tomtom", "mock_api")

            def _src():
                act = traffic_store.get_active()
                return act.source if act else "none"

            def _auto(sim_h: float) -> None:
                j = get_job(run_id)
                if j is None:
                    return
                err = try_begin_replan(j, day=day, sim_time_h=float(sim_h), trigger="auto")
                if err:
                    logger.debug("auto-replan skipped: %s", err)

            replay_kw: Dict[str, object] = {
                "inst": inst,
                "sol": sol,
                "run_id": run_id,
                "day": day,
                "hours_per_real_second": hours_per_real_second,
                "stop_event": stop_ev,
                "telemetry_extra_fn": _traffic_meta,
            }
            if adaptive:
                replay_kw["adaptive_traffic"] = True
                replay_kw["get_factor"] = lambda h: float(traffic_store.get_factor(h))
                replay_kw["get_baseline_factor"] = lambda h: float(traffic_store.get_baseline_factor(h))
                replay_kw["auto_replan_callback"] = _auto
                replay_kw["traffic_source_fn"] = _src

            cancelled = bool(run_simulation_replay(**replay_kw))
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
    traffic_model: str = "igp",
) -> None:
    out_dir = os.path.join(RUNS_ROOT, job.run_id)
    os.makedirs(out_dir, exist_ok=True)

    with _lock:
        job.traffic_model = traffic_model

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
                traffic_model=traffic_model,
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
                job.plan_revision = 0
                job.replan_cooldown_until = 0.0
                job.plan_revision_updated_at = None
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


def start_replan_thread(
    job: Job,
    *,
    day: int,
    sim_time_h: float,
    trigger: str = "user",
) -> None:
    """Background re-optimization; requires B/C artifact with best_chromosome."""
    run_id = job.run_id
    run_dir = job.run_dir
    if not run_dir:
        raise ValueError("missing run_dir")

    def _work() -> None:
        from src.experiments.runner import _make_result, _save_run_output, load_planning_artifact_bundle
        from src.messaging.kafka_convergence import emit_replan_event

        try:
            bundle = load_planning_artifact_bundle(run_dir)
            inst = bundle["instance"]
            sol = bundle["solution"]
            tm_key = str(bundle.get("traffic_model") or "igp")
            best_chrom = bundle.get("best_chromosome")

            scenario = (job.result or {}).get("scenario")
            if scenario not in ("B", "C"):
                raise RuntimeError("re-plan only supported for scenarios B and C")
            if best_chrom is None:
                raise RuntimeError("no best_chromosome in artifacts; re-run planning with current backend")

            remaining = _remaining_stops_count(sol, day, sim_time_h)
            if remaining == 0:
                raise RuntimeError("no remaining stops after sim_time_h; nothing to re-optimize")
            scale = (job.result or {}).get("scale") or "upload"
            seed = int((job.result or {}).get("seed") or 42)
            parent_dir = os.path.dirname(run_dir)

            started = {
                "type": "replan_started",
                "run_id": run_id,
                "day": day,
                "sim_time_h": float(sim_time_h),
                "remaining_stops": remaining,
                "trigger": trigger,
            }
            outbound_queue.put(started)
            emit_replan_event(started)

            from src.simulation.replan_subinstance import run_sub_replan_hga

            t0 = time.time()
            merged_sol, _sub_sol, _meta = run_sub_replan_hga(
                inst,
                sol,
                best_chrom,
                day,
                float(sim_time_h),
                scenario=scenario,
                traffic_model_key=tm_key,
                seed=seed,
                pop_size=REPLAN_POP_SIZE,
                generations=REPLAN_GENERATIONS,
                time_limit=REPLAN_TIME_LIMIT_S,
                run_id=run_id,
            )
            elapsed = time.time() - t0
            n, m = inst.n, inst.m
            result = _make_result(
                scenario, scale, n, m, seed, merged_sol, elapsed, inst=inst, convergence=None
            )
            new_run_dir = _save_run_output(
                parent_dir,
                scenario,
                scale,
                n,
                seed,
                inst,
                merged_sol,
                result,
                convergence=None,
                best_chromosome=best_chrom,
                traffic_model=tm_key,
            )

            map_path = os.path.join(new_run_dir, "map.html")
            map_html = None
            if os.path.isfile(map_path):
                with open(map_path, "r", encoding="utf-8") as f:
                    map_html = f.read()

            updated_iso = datetime.now(timezone.utc).isoformat()
            with _lock:
                job.result = result
                job.map_html = map_html
                job.run_dir = new_run_dir
                job.plan_revision = int(job.plan_revision) + 1
                job.replan_cooldown_until = time.monotonic() + REPLAN_COOLDOWN_S
                job.plan_revision_updated_at = updated_iso

            done = {
                "type": "replan_complete",
                "run_id": run_id,
                "day": day,
                "sim_time_h": float(sim_time_h),
                "plan_revision": job.plan_revision,
                "run_dir": new_run_dir,
                "plan_revision_updated_at": updated_iso,
            }
            outbound_queue.put(done)
            emit_replan_event(done)
        except Exception as e:
            logger.exception("Re-plan failed")
            outbound_queue.put(
                {
                    "type": "replan_error",
                    "run_id": run_id,
                    "day": day,
                    "message": str(e),
                }
            )
        finally:
            with _lock:
                job.replan_in_progress = False

    threading.Thread(target=_work, daemon=True, name=f"replan-{run_id[:8]}").start()


def try_begin_replan(
    job: Job,
    *,
    day: int,
    sim_time_h: float,
    trigger: str = "user",
) -> Optional[str]:
    """
    Enforce cooldown and single-flight. Returns None if OK (thread started), else error message.
    trigger: 'user' | 'auto' — auto emits an irp-alert before starting the replan thread.
    """
    now = time.monotonic()
    with _lock:
        if job.replan_in_progress:
            return "re-plan already running"
        if now < job.replan_cooldown_until:
            return "re-plan cooldown active (120s between runs)"
        if job.state != JobState.COMPLETE or not job.run_dir:
            return "job not ready for re-plan"
        job.replan_in_progress = True
    try:
        if trigger == "auto":
            from datetime import datetime, timezone

            from src.messaging.kafka_convergence import emit_irp_alert

            emit_irp_alert(
                {
                    "run_id": job.run_id,
                    "type": "auto_replan_triggered",
                    "vehicle_id": -1,
                    "day": day,
                    "sim_time_h": float(sim_time_h),
                    "message": "Auto-replan — congestion detected",
                    "ts": datetime.now(timezone.utc).isoformat(),
                }
            )
        start_replan_thread(job, day=day, sim_time_h=sim_time_h, trigger=trigger)
    except Exception:
        with _lock:
            job.replan_in_progress = False
        raise
    return None

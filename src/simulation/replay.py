"""
Replay solution: emit vehicle-telemetry to Kafka with coarse time steps.
OSRM geometry per leg; if None, straight-line waypoints (log warning only).
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import numpy as np

from src.core.instance import Instance
from src.core.solution import Solution, Route
from src.messaging.kafka_convergence import emit_irp_alert, emit_vehicle_telemetry
from src.simulation.route_geometry import haversine_km, waypoints_for_leg

logger = logging.getLogger(__name__)


def _emit_telemetry_step(
    run_id: str,
    vid: int,
    day: int,
    lat: float,
    lon: float,
    sim_t: float,
    last_emit: List[Optional[float]],
    rest: Dict[str, object],
) -> None:
    """Emit one telemetry row; speed_kmh_sim from sim-time delta vs. great-circle hop."""
    speed = None
    if last_emit[0] is not None and last_emit[2] is not None:
        dt_h = sim_t - float(last_emit[2])
        if dt_h > 1e-12:
            speed = haversine_km(float(last_emit[0]), float(last_emit[1]), lat, lon) / dt_h
    emit_vehicle_telemetry(
        {
            "run_id": run_id,
            "vehicle_id": vid,
            "day": day,
            "lat": lat,
            "lon": lon,
            "sim_time_h": sim_t,
            "speed_kmh_sim": speed,
            **rest,
        }
    )
    last_emit[0], last_emit[1], last_emit[2] = lat, lon, sim_t


def _sleep_cancellable(seconds: float, stop_event: Optional[threading.Event]) -> bool:
    """Sleep up to `seconds` real seconds; return True if cancelled via stop_event."""
    if seconds <= 0:
        return bool(stop_event and stop_event.is_set())
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if stop_event and stop_event.is_set():
            return True
        remaining = end - time.monotonic()
        time.sleep(min(0.05, remaining))
    return bool(stop_event and stop_event.is_set())


def _interpolate_latlon(path: List[Tuple[float, float]], frac: float) -> Tuple[float, float]:
    if len(path) == 1:
        return path[0]
    segs = []
    total = 0.0
    for i in range(len(path) - 1):
        lat1, lon1 = path[i]
        lat2, lon2 = path[i + 1]
        d = abs(lat2 - lat1) + abs(lon2 - lon1)
        segs.append(d)
        total += d
    if total < 1e-12:
        return path[0]
    target = frac * total
    acc = 0.0
    for i, d in enumerate(segs):
        if acc + d >= target:
            t = (target - acc) / d if d > 1e-12 else 0.0
            lat1, lon1 = path[i]
            lat2, lon2 = path[i + 1]
            return (lat1 + t * (lat2 - lat1), lon1 + t * (lon2 - lon1))
        acc += d
    return path[-1]


def run_simulation_replay(
    inst: Instance,
    sol: Solution,
    run_id: str,
    *,
    day: Optional[int] = None,
    hours_per_real_second: float = 1.0,
    steps_per_leg: int = 8,
    stop_event: Optional[threading.Event] = None,
) -> bool:
    """
    Emit telemetry (and stockout/route_complete alerts) for all days or a single day.

    Returns True if cancelled via stop_event before finishing.
    """
    T = len(sol.schedule)
    days = range(T) if day is None else range(max(0, min(day, T - 1)), max(0, min(day, T - 1)) + 1)
    for d in days:
        for route in sol.schedule[d]:
            if not route.stops:
                continue
            if _replay_route(inst, sol, run_id, route, d, hours_per_real_second, steps_per_leg, stop_event):
                return True
    return False


def _replay_route(
    inst: Instance,
    sol: Solution,
    run_id: str,
    route: Route,
    day: int,
    hours_per_real_second: float,
    steps_per_leg: int,
    stop_event: Optional[threading.Event],
) -> bool:
    """Return True if stopped early."""
    vid = route.vehicle_id
    prev_idx = 0
    prev_time = float(route.depart_h)
    last_emit: List[Optional[float]] = [None, None, None]

    for cust_1b, _qty, arrival_h in route.stops:
        arrival_h = float(arrival_h)
        points = waypoints_for_leg(inst.coords, prev_idx, cust_1b)
        duration_h = max(1e-6, arrival_h - prev_time)
        real_dt = duration_h / max(hours_per_real_second, 1e-6)
        n_steps = max(1, steps_per_leg)
        step_sleep = real_dt / n_steps

        for s in range(n_steps + 1):
            if stop_event and stop_event.is_set():
                return True
            frac = s / float(n_steps)
            lat, lon = _interpolate_latlon(points, frac)
            sim_t = prev_time + duration_h * frac
            status = "delivering" if s == n_steps else "en_route"
            _emit_telemetry_step(
                run_id,
                vid,
                day,
                lat,
                lon,
                sim_t,
                last_emit,
                {
                    "status": status,
                    "next_customer_id": cust_1b,
                    "eta_h": sim_t,
                    "planned_arrival_h": arrival_h,
                },
            )
            if s < n_steps and _sleep_cancellable(step_sleep, stop_event):
                return True

        prev_time = arrival_h
        prev_idx = cust_1b

    depot_points = waypoints_for_leg(inst.coords, prev_idx, 0)
    duration_h = max(1e-6, 0.5)
    real_dt = duration_h / max(hours_per_real_second, 1e-6)
    step_sleep = real_dt / max(steps_per_leg, 1)
    for s in range(steps_per_leg + 1):
        if stop_event and stop_event.is_set():
            return True
        frac = s / float(steps_per_leg)
        lat, lon = _interpolate_latlon(depot_points, frac)
        st = prev_time + duration_h * frac
        _emit_telemetry_step(
            run_id,
            vid,
            day,
            lat,
            lon,
            st,
            last_emit,
            {
                "status": "en_route",
                "next_customer_id": 0,
                "eta_h": st,
                "planned_arrival_h": prev_time + duration_h,
            },
        )
        if s < steps_per_leg and _sleep_cancellable(step_sleep, stop_event):
            return True

    _emit_telemetry_step(
        run_id,
        vid,
        day,
        float(inst.coords[0, 1]),
        float(inst.coords[0, 0]),
        prev_time,
        last_emit,
        {
            "status": "done",
            "next_customer_id": -1,
            "eta_h": prev_time,
            "planned_arrival_h": prev_time,
        },
    )
    emit_irp_alert(
        {
            "run_id": run_id,
            "type": "route_complete",
            "vehicle_id": vid,
            "day": day,
            "message": "Route finished for the day",
            "ts": datetime.now(timezone.utc).isoformat(),
        }
    )

    if sol.inventory_trace is not None:
        for cust_1b, _q, _arr in route.stops:
            ci = cust_1b - 1
            if 0 <= ci < inst.n:
                inv = float(sol.inventory_trace[ci, day])
                if inv <= float(inst.L_min[ci]):
                    emit_irp_alert(
                        {
                            "run_id": run_id,
                            "type": "stockout_risk",
                            "vehicle_id": vid,
                            "day": day,
                            "customer_id": cust_1b,
                            "message": f"Inventory at/below min after visit ({inv:.1f})",
                            "ts": datetime.now(timezone.utc).isoformat(),
                        }
                    )
    return False

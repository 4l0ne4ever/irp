"""
Replay solution: emit vehicle-telemetry to Kafka with coarse time steps.
OSRM geometry per leg (depot→customer or customer→customer); if None, straight-line waypoints.
1 simulated hour = hours_per_real_second real seconds (default 1.0).
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np

from src.core.instance import Instance
from src.core.solution import Solution, Route
from src.data.distances import get_osrm_route_geometry
from src.messaging.kafka_convergence import emit_irp_alert, emit_vehicle_telemetry

logger = logging.getLogger(__name__)


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


def _waypoints_for_leg(
    coords: np.ndarray,
    a: int,
    b: int,
) -> List[Tuple[float, float]]:
    geom = get_osrm_route_geometry(coords, [a, b])
    if geom:
        return [(float(p[0]), float(p[1])) for p in geom]
    logger.warning("OSRM geometry None for leg %s→%s — straight line", a, b)
    return [(float(coords[a, 1]), float(coords[a, 0])), (float(coords[b, 1]), float(coords[b, 0]))]


def run_simulation_replay(
    inst: Instance,
    sol: Solution,
    run_id: str,
    *,
    hours_per_real_second: float = 1.0,
    steps_per_leg: int = 8,
) -> None:
    T = len(sol.schedule)
    for day in range(T):
        for route in sol.schedule[day]:
            if not route.stops:
                continue
            _replay_route(inst, sol, run_id, route, day, hours_per_real_second, steps_per_leg)


def _replay_route(
    inst: Instance,
    sol: Solution,
    run_id: str,
    route: Route,
    day: int,
    hours_per_real_second: float,
    steps_per_leg: int,
) -> None:
    vid = route.vehicle_id
    prev_idx = 0
    prev_time = float(route.depart_h)

    for cust_1b, _qty, arrival_h in route.stops:
        arrival_h = float(arrival_h)
        points = _waypoints_for_leg(inst.coords, prev_idx, cust_1b)
        duration_h = max(1e-6, arrival_h - prev_time)
        real_dt = duration_h / max(hours_per_real_second, 1e-6)
        n_steps = max(1, steps_per_leg)
        step_sleep = real_dt / n_steps

        for s in range(n_steps + 1):
            frac = s / float(n_steps)
            lat, lon = _interpolate_latlon(points, frac)
            sim_t = prev_time + duration_h * frac
            status = "delivering" if s == n_steps else "en_route"
            emit_vehicle_telemetry(
                {
                    "run_id": run_id,
                    "vehicle_id": vid,
                    "day": day,
                    "lat": lat,
                    "lon": lon,
                    "status": status,
                    "next_customer_id": cust_1b,
                    "eta_h": sim_t,
                    "planned_arrival_h": arrival_h,
                    "sim_time_h": sim_t,
                }
            )
            if s < n_steps:
                time.sleep(step_sleep)

        prev_time = arrival_h
        prev_idx = cust_1b

    # Return to depot
    depot_points = _waypoints_for_leg(inst.coords, prev_idx, 0)
    duration_h = max(1e-6, 0.5)
    real_dt = duration_h / max(hours_per_real_second, 1e-6)
    step_sleep = real_dt / max(steps_per_leg, 1)
    for s in range(steps_per_leg + 1):
        frac = s / float(steps_per_leg)
        lat, lon = _interpolate_latlon(depot_points, frac)
        emit_vehicle_telemetry(
            {
                "run_id": run_id,
                "vehicle_id": vid,
                "day": day,
                "lat": lat,
                "lon": lon,
                "status": "en_route",
                "next_customer_id": 0,
                "eta_h": prev_time + duration_h * frac,
                "planned_arrival_h": prev_time + duration_h,
                "sim_time_h": prev_time + duration_h * frac,
            }
        )
        time.sleep(step_sleep)

    emit_vehicle_telemetry(
        {
            "run_id": run_id,
            "vehicle_id": vid,
            "day": day,
            "lat": float(inst.coords[0, 1]),
            "lon": float(inst.coords[0, 0]),
            "status": "done",
            "next_customer_id": -1,
            "eta_h": prev_time,
            "planned_arrival_h": prev_time,
            "sim_time_h": prev_time,
        }
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

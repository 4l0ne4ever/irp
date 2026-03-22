"""
Replay solution: emit vehicle-telemetry to Kafka with coarse time steps.
OSRM geometry per leg; if None, straight-line waypoints (log warning only).

Legacy mode follows planned arrival times from the solution. Adaptive mode (TomTom / mock
profile) uses igp_travel_time × congestion factor and can trigger auto-replan.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional, Tuple

from src.core.instance import Instance
from src.core.solution import Solution, Route
from src.core.traffic import igp_travel_time
from src.messaging.kafka_convergence import emit_irp_alert, emit_traffic_update, emit_vehicle_telemetry
from src.simulation.route_geometry import haversine_km, waypoints_for_leg

logger = logging.getLogger(__name__)

TelemetryExtraFn = Optional[Callable[[], Dict[str, object]]]

# Drift threshold (hours): 20 minutes vs planned arrival at next stop
DRIFT_THRESHOLD_H = 20.0 / 60.0
# Factor must drop more than 30% vs baseline to count toward auto-replan
FACTOR_DROP_RATIO = 0.7
FACTOR_CHANGE_EMIT = 0.02


def _merge_telemetry_rest(
    base: Dict[str, object],
    telemetry_extra: Optional[Dict[str, object]],
    telemetry_extra_fn: TelemetryExtraFn,
) -> Dict[str, object]:
    out = dict(base)
    if telemetry_extra:
        out.update(telemetry_extra)
    if telemetry_extra_fn:
        out.update(telemetry_extra_fn())
    return out


def _emit_telemetry_step(
    run_id: str,
    vid: int,
    day: int,
    lat: float,
    lon: float,
    sim_t: float,
    last_emit: List[Optional[float]],
    rest: Dict[str, object],
    *,
    sim_time_h_display: Optional[float] = None,
    timeline_cap: Optional[List[float]] = None,
) -> None:
    """Emit one telemetry row; speed_kmh_sim from internal sim_t delta vs. great-circle hop.

    sim_time_h_display (if set) is sent as sim_time_h for UI timeline; internal sim_t is still
    used for speed between consecutive samples on the same leg.
    """
    emit_h = float(sim_time_h_display) if sim_time_h_display is not None else float(sim_t)
    if timeline_cap is not None:
        timeline_cap[0] = max(timeline_cap[0], emit_h)
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
            "sim_time_h": emit_h,
            "speed_kmh_sim": speed,
            **rest,
        }
    )
    last_emit[0], last_emit[1], last_emit[2] = lat, lon, sim_t


def _sleep_cancellable(seconds: float, stop_event: Optional[threading.Event]) -> bool:
    """Sleep up to `seconds` real seconds; return True if cancelled via stop_event."""
    try:
        sec = float(seconds)
    except (TypeError, ValueError):
        return bool(stop_event and stop_event.is_set())
    if sec <= 0 or sec != sec:  # 0, negative, or NaN
        return bool(stop_event and stop_event.is_set())
    end = time.monotonic() + sec
    while time.monotonic() < end:
        if stop_event and stop_event.is_set():
            return True
        remaining = max(0.0, end - time.monotonic())
        if remaining <= 0:
            break
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
        d = haversine_km(lat1, lon1, lat2, lon2)
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


def _clamp_factor(f: float) -> float:
    return float(max(0.3, min(1.0, f)))


def _maybe_emit_traffic_factor(
    run_id: str,
    day: int,
    sim_t: float,
    fac: float,
    source: str,
    last_fac: List[Optional[float]],
) -> None:
    if last_fac[0] is None or abs(fac - float(last_fac[0])) >= FACTOR_CHANGE_EMIT:
        last_fac[0] = fac
        payload = {
            "run_id": run_id,
            "day": day,
            "sim_time_h": float(sim_t),
            "factor": float(fac),
            "source": source,
            "ts": datetime.now(timezone.utc).isoformat(),
        }
        emit_traffic_update(payload)


def _maybe_auto_replan(
    sim_t: float,
    planned_arrival_h: float,
    arrival_at_stop: float,
    get_factor: Callable[[float], float],
    get_baseline_factor: Callable[[float], float],
    auto_replan_callback: Optional[Callable[[float], None]],
) -> None:
    if auto_replan_callback is None:
        return
    bf = float(get_baseline_factor(sim_t))
    cf = float(get_factor(sim_t))
    if bf <= 1e-9 or cf >= bf * FACTOR_DROP_RATIO:
        return
    drift = float(arrival_at_stop) - float(planned_arrival_h)
    if drift <= DRIFT_THRESHOLD_H:
        return
    auto_replan_callback(float(sim_t))


def run_simulation_replay(
    inst: Instance,
    sol: Solution,
    run_id: str,
    *,
    day: Optional[int] = None,
    hours_per_real_second: float = 1.0,
    steps_per_leg: int = 8,
    stop_event: Optional[threading.Event] = None,
    telemetry_extra: Optional[Dict[str, object]] = None,
    telemetry_extra_fn: TelemetryExtraFn = None,
    adaptive_traffic: bool = False,
    get_factor: Optional[Callable[[float], float]] = None,
    get_baseline_factor: Optional[Callable[[float], float]] = None,
    auto_replan_callback: Optional[Callable[[float], None]] = None,
    traffic_source_fn: Optional[Callable[[], str]] = None,
) -> bool:
    """
    Emit telemetry (and stockout/route_complete alerts) for all days or a single day.

    Returns True if cancelled via stop_event before finishing.
    """
    T = len(sol.schedule)
    days = range(T) if day is None else range(max(0, min(day, T - 1)), max(0, min(day, T - 1)) + 1)
    src_fn = traffic_source_fn or (lambda: "unknown")

    for d in days:
        timeline_end = 0.0
        first_route = True
        for route in sol.schedule[d]:
            if not route.stops:
                continue
            depart = float(route.depart_h)
            offset = 0.0 if first_route else (timeline_end - depart)
            timeline_cap: List[float] = [0.0]
            first_route = False
            if adaptive_traffic and get_factor is not None:
                gb = get_baseline_factor or get_factor
                if _replay_route_adaptive(
                    inst,
                    sol,
                    run_id,
                    route,
                    d,
                    hours_per_real_second,
                    steps_per_leg,
                    stop_event,
                    telemetry_extra,
                    telemetry_extra_fn,
                    get_factor,
                    gb,
                    auto_replan_callback,
                    src_fn,
                    sim_time_offset=offset,
                    timeline_cap=timeline_cap,
                ):
                    return True
            elif _replay_route(
                inst,
                sol,
                run_id,
                route,
                d,
                hours_per_real_second,
                steps_per_leg,
                stop_event,
                telemetry_extra,
                telemetry_extra_fn,
                sim_time_offset=offset,
                timeline_cap=timeline_cap,
            ):
                return True
            timeline_end = max(timeline_end, timeline_cap[0])
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
    telemetry_extra: Optional[Dict[str, object]] = None,
    telemetry_extra_fn: TelemetryExtraFn = None,
    *,
    sim_time_offset: float = 0.0,
    timeline_cap: Optional[List[float]] = None,
) -> bool:
    """Return True if stopped early. Timeline follows planned arrivals from the solution."""
    vid = route.vehicle_id
    prev_idx = 0
    prev_time = float(route.depart_h)
    last_emit: List[Optional[float]] = [None, None, None]

    for cust_1b, _qty, arrival_h in route.stops:
        arrival_h = float(arrival_h)
        points = waypoints_for_leg(inst.coords, prev_idx, cust_1b, stop_event)
        duration_h = max(1e-6, arrival_h - prev_time)
        real_dt = duration_h / max(hours_per_real_second, 1e-6)
        n_steps = max(1, int(steps_per_leg))
        step_sleep = max(0.0, real_dt / n_steps)

        for s in range(n_steps + 1):
            if stop_event and stop_event.is_set():
                return True
            frac = s / float(n_steps)
            lat, lon = _interpolate_latlon(points, frac)
            sim_t = prev_time + duration_h * frac
            status = "delivering" if s == n_steps else "en_route"
            rest = _merge_telemetry_rest(
                {
                    "status": status,
                    "next_customer_id": cust_1b,
                    "eta_h": sim_t,
                    "planned_arrival_h": arrival_h,
                },
                telemetry_extra,
                telemetry_extra_fn,
            )
            _emit_telemetry_step(
                run_id,
                vid,
                day,
                lat,
                lon,
                sim_t,
                last_emit,
                rest,
                sim_time_h_display=sim_t + sim_time_offset,
                timeline_cap=timeline_cap,
            )
            if s < n_steps and _sleep_cancellable(step_sleep, stop_event):
                return True

        prev_time = arrival_h
        prev_idx = cust_1b

    depot_points = waypoints_for_leg(inst.coords, prev_idx, 0, stop_event)
    duration_h = max(1e-6, 0.5)
    real_dt = duration_h / max(hours_per_real_second, 1e-6)
    n_dep = max(1, int(steps_per_leg))
    step_sleep = max(0.0, real_dt / n_dep)
    for s in range(n_dep + 1):
        if stop_event and stop_event.is_set():
            return True
        frac = s / float(n_dep)
        lat, lon = _interpolate_latlon(depot_points, frac)
        st = prev_time + duration_h * frac
        rest_d = _merge_telemetry_rest(
            {
                "status": "en_route",
                "next_customer_id": 0,
                "eta_h": st,
                "planned_arrival_h": prev_time + duration_h,
            },
            telemetry_extra,
            telemetry_extra_fn,
        )
        _emit_telemetry_step(
            run_id,
            vid,
            day,
            lat,
            lon,
            st,
            last_emit,
            rest_d,
            sim_time_h_display=st + sim_time_offset,
            timeline_cap=timeline_cap,
        )
        if s < n_dep and _sleep_cancellable(step_sleep, stop_event):
            return True

    rest_done = _merge_telemetry_rest(
        {
            "status": "done",
            "next_customer_id": -1,
            "eta_h": prev_time,
            "planned_arrival_h": prev_time,
        },
        telemetry_extra,
        telemetry_extra_fn,
    )
    _emit_telemetry_step(
        run_id,
        vid,
        day,
        float(inst.coords[0, 1]),
        float(inst.coords[0, 0]),
        prev_time,
        last_emit,
        rest_done,
        sim_time_h_display=prev_time + sim_time_offset,
        timeline_cap=timeline_cap,
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


def _replay_route_adaptive(
    inst: Instance,
    sol: Solution,
    run_id: str,
    route: Route,
    day: int,
    hours_per_real_second: float,
    steps_per_leg: int,
    stop_event: Optional[threading.Event],
    telemetry_extra: Optional[Dict[str, object]],
    telemetry_extra_fn: TelemetryExtraFn,
    get_factor: Callable[[float], float],
    get_baseline_factor: Callable[[float], float],
    auto_replan_callback: Optional[Callable[[float], None]],
    traffic_source_fn: Callable[[], str],
    *,
    sim_time_offset: float = 0.0,
    timeline_cap: Optional[List[float]] = None,
) -> bool:
    """Return True if stopped early. Leg durations use igp_travel_time × factor (matches TomTomModel)."""
    vid = route.vehicle_id
    prev_idx = 0
    prev_time = float(route.depart_h)
    last_emit: List[Optional[float]] = [None, None, None]
    last_factor_emitted: List[Optional[float]] = [None]

    for cust_1b, _qty, planned_arrival_h in route.stops:
        planned_arrival_h = float(planned_arrival_h)
        dist = float(inst.dist[prev_idx, cust_1b])
        points = waypoints_for_leg(inst.coords, prev_idx, cust_1b, stop_event)
        depart = prev_time
        base_tt = igp_travel_time(dist, depart) if dist > 1e-9 else 0.0
        f_dep = _clamp_factor(get_factor(depart))
        duration_h = max(1e-6, base_tt * f_dep)
        arrival_sim = depart + duration_h
        ci = cust_1b - 1
        if 0 <= ci < inst.n:
            ew = float(inst.e[ci])
            if arrival_sim < ew:
                arrival_sim = ew

        real_dt = duration_h / max(hours_per_real_second, 1e-6)
        n_steps = max(1, int(steps_per_leg))
        step_sleep = max(0.0, real_dt / n_steps)

        for s in range(n_steps + 1):
            if stop_event and stop_event.is_set():
                return True
            frac = s / float(n_steps)
            lat, lon = _interpolate_latlon(points, frac)
            sim_t = depart + duration_h * frac
            fac_now = _clamp_factor(get_factor(sim_t))
            _maybe_emit_traffic_factor(
                run_id, day, sim_t, fac_now, traffic_source_fn(), last_factor_emitted
            )
            status = "delivering" if s == n_steps else "en_route"
            rest = _merge_telemetry_rest(
                {
                    "status": status,
                    "next_customer_id": cust_1b,
                    "eta_h": arrival_sim,
                    "planned_arrival_h": planned_arrival_h,
                },
                telemetry_extra,
                telemetry_extra_fn,
            )
            _emit_telemetry_step(
                run_id,
                vid,
                day,
                lat,
                lon,
                sim_t,
                last_emit,
                rest,
                sim_time_h_display=sim_t + sim_time_offset,
                timeline_cap=timeline_cap,
            )
            _maybe_auto_replan(
                sim_t,
                planned_arrival_h,
                arrival_sim,
                get_factor,
                get_baseline_factor,
                auto_replan_callback,
            )
            if s < n_steps and _sleep_cancellable(step_sleep, stop_event):
                return True

        prev_time = arrival_sim + float(inst.s[ci]) if 0 <= ci < inst.n else arrival_sim
        prev_idx = cust_1b

    depot_points = waypoints_for_leg(inst.coords, prev_idx, 0, stop_event)
    dist_d = float(inst.dist[prev_idx, 0])
    duration_h = max(1e-6, igp_travel_time(dist_d, prev_time) * _clamp_factor(get_factor(prev_time)))
    real_dt = duration_h / max(hours_per_real_second, 1e-6)
    n_steps = max(1, int(steps_per_leg))
    step_sleep = max(0.0, real_dt / n_steps)
    depart = prev_time
    arrival_depot = depart + duration_h

    for s in range(n_steps + 1):
        if stop_event and stop_event.is_set():
            return True
        frac = s / float(n_steps)
        lat, lon = _interpolate_latlon(depot_points, frac)
        sim_t = depart + duration_h * frac
        fac_now = _clamp_factor(get_factor(sim_t))
        _maybe_emit_traffic_factor(run_id, day, sim_t, fac_now, traffic_source_fn(), last_factor_emitted)
        rest_d = _merge_telemetry_rest(
            {
                "status": "en_route",
                "next_customer_id": 0,
                "eta_h": arrival_depot,
                "planned_arrival_h": depart + duration_h,
            },
            telemetry_extra,
            telemetry_extra_fn,
        )
        _emit_telemetry_step(
            run_id,
            vid,
            day,
            lat,
            lon,
            sim_t,
            last_emit,
            rest_d,
            sim_time_h_display=sim_t + sim_time_offset,
            timeline_cap=timeline_cap,
        )
        if s < n_steps and _sleep_cancellable(step_sleep, stop_event):
            return True

    rest_done = _merge_telemetry_rest(
        {
            "status": "done",
            "next_customer_id": -1,
            "eta_h": prev_time,
            "planned_arrival_h": prev_time,
        },
        telemetry_extra,
        telemetry_extra_fn,
    )
    _emit_telemetry_step(
        run_id,
        vid,
        day,
        float(inst.coords[0, 1]),
        float(inst.coords[0, 0]),
        prev_time,
        last_emit,
        rest_done,
        sim_time_h_display=prev_time + sim_time_offset,
        timeline_cap=timeline_cap,
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

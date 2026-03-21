"""
Static map + time window for Monitoring UI (depot, customers, planned polylines per vehicle).
"""

from __future__ import annotations

from typing import Any, Dict, List


def build_monitor_context(run_dir: str, day: int) -> Dict[str, Any]:
    from src.experiments.runner import load_planning_artifacts
    from src.simulation.route_geometry import build_routed_latlon_path

    inst, sol = load_planning_artifacts(run_dir)
    T = len(sol.schedule)
    if day < 0 or day >= T:
        raise ValueError(f"day must be in [0, {T - 1}]")

    coords = inst.coords
    n = int(inst.n)

    depot_lon = float(coords[0, 0])
    depot_lat = float(coords[0, 1])
    depot = {"id": 0, "lat": depot_lat, "lon": depot_lon, "label": "Depot"}

    customers: List[Dict[str, Any]] = []
    for i in range(1, n + 1):
        customers.append(
            {
                "id": int(i),
                "lat": float(coords[i, 1]),
                "lon": float(coords[i, 0]),
                "label": f"C{i}",
            }
        )

    day_routes = sol.schedule[day]
    planned_routes: List[Dict[str, Any]] = []
    hour_samples: List[float] = []
    customer_ids_on_day: List[int] = []

    for route in day_routes:
        hour_samples.append(float(route.depart_h))
        path_idx: List[int] = [0]
        for cust_1b, _qty, arr_h in route.stops:
            ci = int(cust_1b)
            path_idx.append(ci)
            hour_samples.append(float(arr_h))
            if ci > 0:
                customer_ids_on_day.append(ci)
        if route.stops:
            path_idx.append(0)
        latlon_path = build_routed_latlon_path(coords, path_idx)
        if len(latlon_path) >= 2:
            planned_routes.append(
                {
                    "vehicle_id": int(route.vehicle_id),
                    "path": latlon_path,
                }
            )

    if hour_samples:
        t_lo = max(0.0, min(hour_samples) - 0.5)
        t_hi = min(24.0, max(hour_samples) + 1.0)
        if t_hi <= t_lo:
            t_hi = t_lo + 2.0
    else:
        t_lo, t_hi = 6.0, 20.0

    return {
        "day": int(day),
        "n": n,
        "m": int(inst.m),
        "depot": depot,
        "customers": customers,
        "customer_ids_on_day": sorted(set(customer_ids_on_day)),
        "planned_routes": planned_routes,
        "day_window_h": {"start": round(t_lo, 2), "end": round(t_hi, 2)},
    }

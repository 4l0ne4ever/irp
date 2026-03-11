"""
Map visualization for IRP-TW-DT solutions using Folium.

Generates interactive HTML maps showing:
- Customer locations and depot on real Hanoi map
- Routes for each day (color-coded)
- Delivery quantities, time windows, arrival times
- Inventory levels as popups
"""

import logging
import os
from typing import Optional, List, Dict

import numpy as np

from src.core.instance import Instance
from src.core.solution import Solution, Route
from src.data.distances import get_osrm_route_geometry

logger = logging.getLogger(__name__)

# Day colors for routes (7 days max)
DAY_COLORS = [
    "#e6194b",  # Day 0: Red
    "#3cb44b",  # Day 1: Green
    "#4363d8",  # Day 2: Blue
    "#f58231",  # Day 3: Orange
    "#911eb4",  # Day 4: Purple
    "#42d4f4",  # Day 5: Cyan
    "#f032e6",  # Day 6: Magenta
]

TW_SHIFT_NAMES = {
    (8.0, 12.0): "Sáng (8h-12h)",
    (14.0, 18.0): "Chiều (14h-18h)",
}


def visualize_solution(
    inst: Instance,
    sol: Solution,
    output_path: str = "results/map.html",
    title: Optional[str] = None,
    use_osrm_geometry: bool = True,
) -> str:
    """
    Create an interactive Folium map visualizing the IRP-TW-DT solution.

    Parameters
    ----------
    inst : Instance
        Problem instance with GPS coordinates.
    sol : Solution
        Solution to visualize.
    output_path : str
        Path to save the HTML file.
    title : str or None
        Map title (default: instance name).
    use_osrm_geometry : bool
        If True, fetch actual road geometry from OSRM for route lines.
        If False, draw straight lines between stops.

    Returns
    -------
    str
        Path to the generated HTML file.
    """
    try:
        import folium
        from folium import plugins
    except ImportError:
        logger.error("folium not installed. Install with: pip install folium")
        raise ImportError("pip install folium requests")

    if title is None:
        title = f"IRP-TW-DT: {inst.name}"

    # Depot and customer coordinates are GPS [lon, lat]
    # Folium uses [lat, lon]
    depot_latlon = [inst.coords[0, 1], inst.coords[0, 0]]

    m = folium.Map(
        location=depot_latlon,
        zoom_start=13,
        tiles="OpenStreetMap",
    )

    # Add title
    title_html = f'''
    <div style="position: fixed; top: 10px; left: 50%; transform: translateX(-50%);
                z-index: 1000; background: white; padding: 10px 20px;
                border-radius: 8px; box-shadow: 0 2px 6px rgba(0,0,0,0.3);
                font-family: Arial; font-size: 14px; font-weight: bold;">
        {title}
        <br><span style="font-size: 11px; font-weight: normal; color: #666;">
        Total: {sol.total_cost:,.0f} VND | Inv: {sol.cost_inventory:,.0f}
        | Dist: {sol.cost_distance:,.0f} | Time: {sol.cost_time:,.0f}
        | Feasible: {sol.feasible}</span>
    </div>
    '''
    m.get_root().html.add_child(folium.Element(title_html))

    # ----- Depot Marker -----
    folium.Marker(
        location=depot_latlon,
        popup=folium.Popup(
            f"<b>🏭 DEPOT</b><br>"
            f"Lon: {inst.coords[0, 0]:.6f}<br>"
            f"Lat: {inst.coords[0, 1]:.6f}<br>"
            f"Vehicles: {inst.m}<br>"
            f"Capacity: {inst.Q:.0f} units",
            max_width=250,
        ),
        tooltip="Depot",
        icon=folium.Icon(color="red", icon="industry", prefix="fa"),
    ).add_to(m)

    # ----- Customer Markers -----
    customer_group = folium.FeatureGroup(name="Khách hàng", show=True)

    for i in range(inst.n):
        cust_node = i + 1
        lat = inst.coords[cust_node, 1]
        lon = inst.coords[cust_node, 0]
        tw_name = TW_SHIFT_NAMES.get((inst.e[i], inst.l[i]),
                                      f"{inst.e[i]:.0f}h-{inst.l[i]:.0f}h")

        # Compute delivery days
        if sol.delivery_matrix is not None:
            delivery_days = [t for t in range(inst.T) if sol.delivery_matrix[i, t] > 0]
            deliveries_str = ", ".join(
                f"D{t}({sol.delivery_matrix[i, t]:.0f})" for t in delivery_days
            )
        else:
            deliveries_str = "N/A"

        # Inventory trace
        inv_str = ""
        if sol.inventory_trace is not None:
            inv_vals = sol.inventory_trace[i, :]
            inv_str = (
                f"<br><b>Tồn kho:</b> "
                + " → ".join(f"{v:.0f}" for v in inv_vals)
                + f"<br>Avg: {np.mean(inv_vals):.0f} / U={inst.U[i]:.0f}"
            )

        avg_demand = np.mean(inst.demand[i, :])
        popup_html = (
            f"<b>Khách #{cust_node}</b><br>"
            f"<b>TW:</b> {tw_name}<br>"
            f"<b>U:</b> {inst.U[i]:.0f} | <b>L_min:</b> {inst.L_min[i]:.0f}<br>"
            f"<b>I₀:</b> {inst.I0[i]:.0f} | <b>d̄:</b> {avg_demand:.1f}/ngày<br>"
            f"<b>h:</b> {inst.h[i]:.0f} VND/đv/ngày<br>"
            f"<b>Giao:</b> {deliveries_str}"
            f"{inv_str}"
        )

        # Color by time window shift
        color = "blue" if inst.e[i] < 13.0 else "green"

        folium.CircleMarker(
            location=[lat, lon],
            radius=7,
            popup=folium.Popup(popup_html, max_width=300),
            tooltip=f"#{cust_node} ({tw_name})",
            color=color,
            fill=True,
            fill_color=color,
            fill_opacity=0.7,
        ).add_to(customer_group)

    customer_group.add_to(m)

    # ----- Routes for each day -----
    for t in range(inst.T):
        if t >= len(sol.schedule) or not sol.schedule[t]:
            continue

        day_group = folium.FeatureGroup(
            name=f"Ngày {t} ({len(sol.schedule[t])} routes)",
            show=(t == 0),  # Only show day 0 by default
        )
        day_color = DAY_COLORS[t % len(DAY_COLORS)]

        for route_idx, route in enumerate(sol.schedule[t]):
            if not route.stops:
                continue

            # Build waypoint sequence: depot -> customers -> depot
            waypoint_nodes = [0]  # depot
            for cust_1based, qty, arrival in route.stops:
                waypoint_nodes.append(cust_1based)
            waypoint_nodes.append(0)  # back to depot

            # Try to get actual road geometry from OSRM
            road_path = None
            if use_osrm_geometry:
                road_path = get_osrm_route_geometry(
                    inst.coords, waypoint_nodes
                )

            if road_path:
                # Draw road geometry
                folium.PolyLine(
                    locations=road_path,
                    color=day_color,
                    weight=3,
                    opacity=0.8,
                    tooltip=f"Day {t}, Route {route_idx} (depart {route.depart_h:.1f}h)",
                ).add_to(day_group)
            else:
                # Fallback: straight lines
                points = []
                for node in waypoint_nodes:
                    points.append([inst.coords[node, 1], inst.coords[node, 0]])

                folium.PolyLine(
                    locations=points,
                    color=day_color,
                    weight=3,
                    opacity=0.7,
                    dash_array="5 10",
                    tooltip=f"Day {t}, Route {route_idx} (depart {route.depart_h:.1f}h)",
                ).add_to(day_group)

            # Add numbered markers for stops in this route
            for stop_idx, (cust_1based, qty, arrival) in enumerate(route.stops):
                lat = inst.coords[cust_1based, 1]
                lon = inst.coords[cust_1based, 0]

                folium.Marker(
                    location=[lat, lon],
                    popup=f"Route {route_idx}, Stop #{stop_idx+1}<br>"
                          f"Arrival: {arrival:.2f}h<br>"
                          f"Qty: {qty:.0f}",
                    tooltip=f"D{t} R{route_idx} #{stop_idx+1}",
                    icon=folium.DivIcon(
                        html=f'<div style="font-size:9px; color:{day_color}; '
                             f'font-weight:bold; text-shadow: 1px 1px white;">'
                             f'{stop_idx+1}</div>',
                        icon_size=(15, 15),
                    ),
                ).add_to(day_group)

        day_group.add_to(m)

    # Layer control
    folium.LayerControl(collapsed=False).add_to(m)

    # Fit bounds to all points
    all_lats = [inst.coords[i, 1] for i in range(inst.n + 1)]
    all_lons = [inst.coords[i, 0] for i in range(inst.n + 1)]
    m.fit_bounds([
        [min(all_lats) - 0.005, min(all_lons) - 0.005],
        [max(all_lats) + 0.005, max(all_lons) + 0.005],
    ])

    # Save
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    m.save(output_path)
    logger.info(f"Map saved to {output_path}")
    return output_path


def visualize_comparison(
    inst: Instance,
    solutions: Dict[str, Solution],
    output_path: str = "results/comparison_map.html",
) -> str:
    """
    Create comparison map with multiple scenarios side by side.

    Parameters
    ----------
    inst : Instance
    solutions : dict
        {scenario_name: Solution} e.g. {"P": sol_p, "A": sol_a, "C": sol_c}
    output_path : str

    Returns
    -------
    str
        Path to the generated HTML file.
    """
    try:
        import folium
    except ImportError:
        raise ImportError("pip install folium")

    depot_latlon = [inst.coords[0, 1], inst.coords[0, 0]]

    m = folium.Map(location=depot_latlon, zoom_start=13, tiles="OpenStreetMap")

    # Depot
    folium.Marker(
        depot_latlon,
        tooltip="Depot",
        icon=folium.Icon(color="red", icon="industry", prefix="fa"),
    ).add_to(m)

    # Customer markers (always shown)
    for i in range(inst.n):
        lat = inst.coords[i + 1, 1]
        lon = inst.coords[i + 1, 0]
        folium.CircleMarker(
            [lat, lon], radius=5, color="gray",
            fill=True, fill_opacity=0.5,
            tooltip=f"#{i+1}",
        ).add_to(m)

    scenario_colors = {"P": "red", "A": "orange", "B": "blue", "C": "green"}

    for scenario_name, sol in solutions.items():
        color = scenario_colors.get(scenario_name, "purple")
        group = folium.FeatureGroup(
            name=f"{scenario_name} (cost={sol.total_cost:,.0f})",
            show=(scenario_name == list(solutions.keys())[-1]),
        )

        for t in range(inst.T):
            if t >= len(sol.schedule):
                continue
            for route in sol.schedule[t]:
                if not route.stops:
                    continue
                points = [[inst.coords[0, 1], inst.coords[0, 0]]]
                for cust_1based, _, _ in route.stops:
                    points.append([inst.coords[cust_1based, 1],
                                  inst.coords[cust_1based, 0]])
                points.append([inst.coords[0, 1], inst.coords[0, 0]])

                folium.PolyLine(
                    points, color=color, weight=2, opacity=0.6,
                    tooltip=f"{scenario_name} D{t}",
                ).add_to(group)

        group.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    all_lats = [inst.coords[i, 1] for i in range(inst.n + 1)]
    all_lons = [inst.coords[i, 0] for i in range(inst.n + 1)]
    m.fit_bounds([
        [min(all_lats) - 0.005, min(all_lons) - 0.005],
        [max(all_lats) + 0.005, max(all_lons) + 0.005],
    ])

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)
    m.save(output_path)
    logger.info(f"Comparison map saved to {output_path}")
    return output_path

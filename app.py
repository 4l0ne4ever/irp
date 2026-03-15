"""
IRP-TW-DT Streamlit App — browser UI for running experiments.
All controls and output on main screen; instance preview map on upload; live log during/after run.
"""

import io
import logging
import os
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple, Any

import random
import streamlit as st
import numpy as np

# Page config (main screen only; no sidebar)
st.set_page_config(
    page_title="IRP-TW-DT Experiments",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# Session state
if "run_in_progress" not in st.session_state:
    st.session_state.run_in_progress = False
if "run_future" not in st.session_state:
    st.session_state.run_future = None
if "last_result" not in st.session_state:
    st.session_state.last_result = None
if "last_convergence" not in st.session_state:
    st.session_state.last_convergence = None
if "last_map_html" not in st.session_state:
    st.session_state.last_map_html = None
if "error_message" not in st.session_state:
    st.session_state.error_message = None
if "source_mode" not in st.session_state:
    st.session_state.source_mode = "builtin"
if "last_run_log" not in st.session_state:
    st.session_state.last_run_log = ""
if "upload_preview_map" not in st.session_state:
    st.session_state.upload_preview_map = None
if "builtin_instance" not in st.session_state:
    st.session_state.builtin_instance = None  # Instance after Generate
if "builtin_preview_map" not in st.session_state:
    st.session_state.builtin_preview_map = None  # HTML map after Generate
if "upload_instance" not in st.session_state:
    st.session_state.upload_instance = None  # Loaded instance from upload (avoid re-read on rerun)
if "upload_instance_filename" not in st.session_state:
    st.session_state.upload_instance_filename = None
if "instance_for_run" not in st.session_state:
    st.session_state.instance_for_run = None  # Cached so run block can use it after rerun
if "run_params" not in st.session_state:
    st.session_state.run_params = None  # scenario, pop_size, generations, time_limit
if "run_button_clicked" not in st.session_state:
    st.session_state.run_button_clicked = False  # set by button on_click so run block always sees it
if "current_run_output_dir" not in st.session_state:
    st.session_state.current_run_output_dir = None  # for polling run_log.txt during run

RUNS_BASE = "/tmp/irp_runs"
RUN_LOG_FILENAME = "run_log.txt"
KEEP_RECENT_RUNS = 10


def _instance_preview_map_html(coords: np.ndarray, n: int, title: str = "Instance (OSRM locations)") -> str:
    """Build Folium map with depot + customer locations (no routes). Returns HTML string."""
    try:
        import folium
    except ImportError:
        return "<p>Folium not installed.</p>"
    # coords: (n+1, 2) [lon, lat]; Folium uses [lat, lon]
    depot_latlon = [float(coords[0, 1]), float(coords[0, 0])]
    m = folium.Map(location=depot_latlon, zoom_start=12, tiles="OpenStreetMap")
    folium.Marker(
        depot_latlon,
        popup="Depot",
        tooltip="Depot",
        icon=folium.Icon(color="red", icon="info-sign"),
    ).add_to(m)
    for i in range(1, n + 1):
        lat, lon = float(coords[i, 1]), float(coords[i, 0])
        folium.CircleMarker(
            [lat, lon],
            radius=6,
            color="blue",
            fill=True,
            fill_color="blue",
            fill_opacity=0.6,
            popup=f"Customer {i}",
            tooltip=f"C{i}",
        ).add_to(m)
    m.get_root().html.add_child(
        folium.Element(
            f'<div style="position:fixed;top:10px;left:50%;transform:translateX(-50%);z-index:9999;'
            f'background:white;padding:8px 16px;border-radius:8px;box-shadow:0 2px 6px rgba(0,0,0,0.3);'
            f'font-size:14px;font-weight:bold;">{title}</div>'
        )
    )
    return m._repr_html_()


def _run_dir_from_result(output_dir: str, scenario: str, scale: str, n: int, seed: int) -> str:
    return os.path.join(output_dir, f"{scenario}_{scale}_n{n}_seed{seed}")


def _read_run_outputs(run_dir: str) -> Tuple[dict, Optional[str], Optional[Any]]:
    import json
    result_path = os.path.join(run_dir, "result.json")
    map_path = os.path.join(run_dir, "map.html")
    conv_path = os.path.join(run_dir, "convergence.csv")
    with open(result_path, "r") as f:
        result = json.load(f)
    if not os.path.isfile(map_path):
        raise RuntimeError("Map generation failed (map.html not written). Check OSRM or logs.")
    with open(map_path, "r") as f:
        map_html = f.read()
    convergence_df = None
    if os.path.isfile(conv_path):
        import pandas as pd
        convergence_df = pd.read_csv(conv_path)
    return result, map_html, convergence_df


@st.cache_data(ttl=3600)
def _load_json_cached(file_bytes: bytes):
    from src.data.upload_loader import load_from_json
    return load_from_json(file_bytes)


@st.cache_data(ttl=3600)
def _load_csv_cached(file_bytes: bytes, depot_lon: float, depot_lat: float):
    from src.data.upload_loader import load_from_csv
    return load_from_csv(file_bytes, depot_lon, depot_lat)


def _job_upload(
    instance: Any, scenario: str, scale: str, seed: int,
    pop_size: int, generations: int, time_limit: float, output_dir: str,
) -> Tuple[dict, str, Optional[Any], str]:
    log_io = io.StringIO()
    old_stdout, old_stderr = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = log_io
    # Capture logging from runner (logger.info etc.) into the same buffer
    log_handler = logging.StreamHandler(log_io)
    log_handler.setLevel(logging.DEBUG)
    log_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s: %(message)s", datefmt="%H:%M:%S"))
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(logging.INFO)
    root.addHandler(log_handler)
    try:
        from src.experiments.runner import run_single_from_instance
        result, run_dir = run_single_from_instance(
            instance=instance, scenario=scenario, scale=scale, seed=seed,
            pop_size=pop_size, generations=generations, time_limit=time_limit,
            output_dir=output_dir,
        )
        _, map_html, convergence_df = _read_run_outputs(run_dir)
        return result, map_html, convergence_df, log_io.getvalue()
    finally:
        root.removeHandler(log_handler)
        root.setLevel(old_level)
        sys.stdout, sys.stderr = old_stdout, old_stderr


def _cleanup_old_runs(keep: int = KEEP_RECENT_RUNS):
    if not os.path.isdir(RUNS_BASE):
        return
    dirs = sorted(
        [os.path.join(RUNS_BASE, d) for d in os.listdir(RUNS_BASE) if os.path.isdir(os.path.join(RUNS_BASE, d))],
        key=os.path.getmtime,
        reverse=True,
    )
    for d in dirs[keep:]:
        try:
            shutil.rmtree(d)
        except Exception:
            pass


from src.core.constants import GA_POP_SIZE, GA_GENERATIONS, GA_TIME_LIMIT

# ========== MAIN: Title ==========
st.title("IRP-TW-DT Experiments")

# ========== Configuration (main screen) ==========
config = st.container()
with config:
    st.subheader("Configuration")
    row1 = st.columns([1, 1, 1, 1])
    with row1[0]:
        source_mode = st.radio(
            "Source",
            ["Built-in instance", "Upload file"],
            index=0,
            key="source_radio",
            horizontal=True,
        )
    st.session_state.source_mode = "builtin" if source_mode == "Built-in instance" else "upload"

    if st.session_state.source_mode == "builtin":
        # Label row so widget row aligns (button same line as inputs)
        lbl = st.columns(4)
        with lbl[0]: st.markdown("**Scenario**")
        with lbl[1]: st.markdown("**n (customers)**")
        with lbl[2]: st.markdown("**m (vehicles)**")
        with lbl[3]: st.markdown("**Action**")
        row2 = st.columns(4)
        with row2[0]:
            scenario = st.selectbox("Scenario", ["P", "A", "B", "C"], index=3, label_visibility="collapsed")
        with row2[1]:
            n_builtin = int(st.number_input("n (customers)", min_value=1, max_value=500, value=20, step=1, key="n_builtin", label_visibility="collapsed"))
        with row2[2]:
            m_builtin = int(st.number_input("m (vehicles)", min_value=1, max_value=50, value=2, step=1, key="m_builtin", label_visibility="collapsed"))
        with row2[3]:
            generate_clicked = st.button("Generate", key="generate_btn")
        uploaded_file = None
        instance_for_run = st.session_state.builtin_instance
        n, m = (st.session_state.builtin_instance.n, st.session_state.builtin_instance.m) if st.session_state.builtin_instance else (n_builtin, m_builtin)
        st.session_state.upload_preview_map = None

        if generate_clicked:
            with st.spinner("Generating instance (OSRM may take 15–30 s for n=20)…"):
                try:
                    from src.data.generator import generate_hanoi_instance
                    inst = generate_hanoi_instance(n_builtin, m_builtin, seed=random.randint(0, 2**31 - 1))
                    st.session_state.builtin_instance = inst
                    st.session_state.builtin_preview_map = _instance_preview_map_html(
                        inst.coords, inst.n, title="Built-in instance — OSRM locations (depot + customers)"
                    )
                    st.session_state.error_message = None
                except Exception as e:
                    st.session_state.error_message = str(e)
                    st.session_state.builtin_instance = None
                    st.session_state.builtin_preview_map = None
            st.rerun()

    else:
        st.session_state.builtin_instance = None
        st.session_state.builtin_preview_map = None
        row2 = st.columns(3)
        with row2[0]:
            scenario = st.selectbox("Scenario", ["P", "A", "B", "C"], index=3, key="scenario_upload")
        with row2[1]:
            uploaded_file = st.file_uploader("Upload JSON or CSV", type=["json", "csv"], key="uploader")
        instance_for_run = None
        n, m = None, None

        if uploaded_file is not None:
            fname = (uploaded_file.name or "").lower()
            # Use cached instance if same file (uploader stream is often exhausted on rerun after clicking Run)
            if (
                st.session_state.upload_instance is not None
                and st.session_state.upload_instance_filename == uploaded_file.name
            ):
                inst = st.session_state.upload_instance
                n, m = inst.n, inst.m
                instance_for_run = inst
                st.session_state.upload_preview_map = _instance_preview_map_html(
                    inst.coords, inst.n, title="Uploaded instance — OSRM locations (depot + customers)"
                )
            else:
                try:
                    file_bytes = uploaded_file.read()
                    if fname.endswith(".csv"):
                        st.caption("CSV: provide depot if not in file (n, m = from file header # m=…, depot_lon=…, depot_lat=…)")
                        c1, c2 = st.columns(2)
                        with c1:
                            depot_lon = st.number_input("Depot longitude", value=105.864567, format="%.6f", key="depot_lon")
                        with c2:
                            depot_lat = st.number_input("Depot latitude", value=20.996789, format="%.6f", key="depot_lat")
                        inst, _ = _load_csv_cached(file_bytes, depot_lon, depot_lat)
                    else:
                        inst, _ = _load_json_cached(file_bytes)
                    n, m = inst.n, inst.m
                    instance_for_run = inst
                    st.session_state.upload_instance = inst
                    st.session_state.upload_instance_filename = uploaded_file.name
                    st.session_state.upload_preview_map = _instance_preview_map_html(
                        inst.coords, inst.n, title="Uploaded instance — OSRM locations (depot + customers)"
                    )
                except RuntimeError as e:
                    st.error(str(e))
                    st.session_state.upload_preview_map = None
                    st.session_state.upload_instance = None
                    st.session_state.upload_instance_filename = None
        else:
            st.session_state.upload_instance = None
            st.session_state.upload_instance_filename = None

    # GA parameters (only for B, C)
    if scenario in ("B", "C"):
        st.caption("GA parameters")
        r3 = st.columns(4)
        with r3[0]:
            preset = st.selectbox("Preset", ["Full Defaults", "Fast Demo"], index=0, key="ga_preset")
        if preset == "Fast Demo":
            pop_size, generations, time_limit = 20, 40, 45.0
        else:
            with r3[1]:
                pop_size = st.number_input("Population size", min_value=10, max_value=300, value=GA_POP_SIZE, key="pop")
            with r3[2]:
                generations = st.number_input("Generations", min_value=10, max_value=2000, value=GA_GENERATIONS, key="gen")
            with r3[3]:
                time_limit = float(st.number_input("Time limit (s)", min_value=10, max_value=600, value=int(GA_TIME_LIMIT), key="tl"))
    else:
        pop_size, generations, time_limit = GA_POP_SIZE, GA_GENERATIONS, GA_TIME_LIMIT

    # Show whether instance is ready so user knows they can run
    instance_ready = (
        (st.session_state.source_mode == "builtin" and st.session_state.builtin_instance is not None)
        or (st.session_state.source_mode == "upload" and instance_for_run is not None)
    )
    if instance_ready and n is not None and m is not None:
        st.caption(f"Instance ready (n={n}, m={m}). Click **Run Experiment** to start the solver.")
        st.session_state.instance_for_run = instance_for_run
        st.session_state.run_params = (scenario, pop_size, generations, time_limit)
    else:
        st.caption("Load an instance first: choose **Built-in** and click **Generate**, or **Upload** a file.")
        st.session_state.instance_for_run = None
        st.session_state.run_params = None

    def _on_run_click():
        st.session_state.run_button_clicked = True

    st.button(
        "Run Experiment",
        type="primary",
        disabled=st.session_state.run_in_progress,
        key="run_btn",
        on_click=_on_run_click,
    )

# Run block: trigger from session state (on_click sets run_button_clicked before rerun)
if st.session_state.get("run_button_clicked") and not st.session_state.run_in_progress:
    st.session_state.run_button_clicked = False  # consume the click
    inst = st.session_state.instance_for_run
    params = st.session_state.run_params
    if inst is None or params is None:
        st.session_state.error_message = (
            "Load an instance first: choose **Built-in** and click **Generate**, or **Upload** a file and wait for it to load."
        )
    else:
        st.session_state.error_message = None
        scenario, pop_size, generations, time_limit = params
        scale = "builtin" if st.session_state.source_mode == "builtin" else "upload"
        output_dir = os.path.join(RUNS_BASE, str(int(time.time())))
        os.makedirs(output_dir, exist_ok=True)
        executor = ThreadPoolExecutor(max_workers=1)
        future = executor.submit(
            _job_upload,
            inst, scenario, scale, 42,
            pop_size, generations, time_limit, output_dir,
        )
        st.session_state.run_future = future
        st.session_state.run_in_progress = True
        st.session_state.current_run_output_dir = output_dir
        st.rerun()

# Poll for completion
if st.session_state.run_in_progress and st.session_state.run_future is not None:
    future = st.session_state.run_future
    if future.done():
        try:
            result, map_html, convergence_df, log = future.result()
            st.session_state.last_result = result
            st.session_state.last_map_html = map_html
            st.session_state.last_convergence = convergence_df
            st.session_state.last_run_log = log
            st.session_state.error_message = None
            _cleanup_old_runs()
        except Exception as e:
            st.session_state.error_message = str(e)
            st.session_state.last_result = None
            st.session_state.last_map_html = None
            st.session_state.last_convergence = None
            st.session_state.last_run_log = str(e)
        st.session_state.run_in_progress = False
        st.session_state.run_future = None
        st.session_state.current_run_output_dir = None
        st.rerun()
    else:
        time.sleep(2)
        st.rerun()

# ========== Error banner ==========
if st.session_state.error_message:
    st.error(st.session_state.error_message)

# ========== Instance map (OSRM — after Generate or Upload) ==========
preview_map = None
if st.session_state.source_mode == "upload" and st.session_state.get("upload_preview_map"):
    preview_map = st.session_state.upload_preview_map
elif st.session_state.source_mode == "builtin" and st.session_state.get("builtin_preview_map"):
    preview_map = st.session_state.builtin_preview_map
if preview_map and not st.session_state.run_in_progress:
    st.subheader("Instance map (OSRM — depot and customers)")
    st.components.v1.html(preview_map, height=400, scrolling=False)

# ========== While calculating ==========
if st.session_state.run_in_progress:
    st.subheader("Solver running")
    st.spinner("Calculating...")

# ========== Results (pop up on screen — no export) ==========
if st.session_state.last_result is not None and not st.session_state.run_in_progress:
    st.subheader("Results")
    r = st.session_state.last_result
    # Top-line metrics
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Total cost", f"{r['total_cost']:,.0f} VND")
    c2.metric("Inventory", f"{r['cost_pct_inventory']}%")
    c3.metric("Distance", f"{r['cost_pct_distance']}%")
    c4.metric("Travel time", f"{r['cost_pct_time']}%")
    c5.metric("Feasible", "✓" if r.get("feasible", False) else "✗")
    c6.metric("TW compliance", f"{r.get('tw_compliance_rate', 0)}%")

    # Detailed breakdown (expandable)
    with st.expander("Detailed metrics", expanded=True):
        st.markdown("**1. Cost breakdown (VND)**")
        st.write(f"- Total: **{r.get('total_cost', 0):,.0f}** | Inventory: {r.get('cost_inventory', 0):,.0f} ({r.get('cost_pct_inventory', 0)}%) | Distance: {r.get('cost_distance', 0):,.0f} ({r.get('cost_pct_distance', 0)}%) | Time: {r.get('cost_time', 0):,.0f} ({r.get('cost_pct_time', 0)}%)")
        st.markdown("**2. Feasibility**")
        st.write(f"- Feasible: **{r.get('feasible', False)}** | TW violations: {r.get('tw_violations', 0)} | Stockout: {r.get('stockout_violations', 0)} | Capacity: {r.get('capacity_violations', 0)} | Vehicle: {r.get('vehicle_violations', 0)} | TW compliance: {r.get('tw_compliance_rate', 0)}%")
        st.markdown("**3. Deliveries & distance**")
        st.write(f"- Total deliveries: **{r.get('n_deliveries', 0)}** | Avg per customer: {r.get('avg_deliveries_per_customer', 0)} | Total distance: **{r.get('total_distance_km', 0)} km**")
        st.markdown("**4. Inventory**")
        st.write(f"- Avg inventory level: **{r.get('avg_inventory_level_pct', 0)}%** of capacity")
        st.markdown("**5. Performance**")
        st.write(f"- CPU time: **{r.get('cpu_time_sec', 0)} s** | Fitness: {r.get('fitness', 0):,.0f}")
        if r.get("per_day"):
            st.markdown("**6. Per-day**")
            for day in r["per_day"]:
                st.write(f"  Day {day.get('day', '')}: {day.get('n_deliveries', 0)} deliveries, {day.get('n_routes', 0)} routes, {day.get('distance_km', 0)} km")

    # Convergence chart (B/C)
    if st.session_state.last_convergence is not None:
        import plotly.graph_objects as go
        df = st.session_state.last_convergence
        if "best_fitness" in df.columns and "avg_fitness" in df.columns:
            x = df["generation"] if "generation" in df.columns else df.index
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=x, y=df["best_fitness"], name="Best", mode="lines"))
            fig.add_trace(go.Scatter(x=x, y=df["avg_fitness"], name="Average", mode="lines", line=dict(dash="dash")))
            fig.update_layout(yaxis_title="Fitness (VND)", height=300)
            st.plotly_chart(fig, use_container_width=True)

    # Solution map (OSRM) — inline, no file export
    st.subheader("Solution map (OSRM)")
    if st.session_state.last_map_html:
        st.components.v1.html(st.session_state.last_map_html, height=500, scrolling=False)

# ========== Run log — live during run, full log after ==========
st.subheader("Run log")
if st.session_state.run_in_progress and st.session_state.current_run_output_dir:
    log_path = os.path.join(st.session_state.current_run_output_dir, RUN_LOG_FILENAME)
    if os.path.isfile(log_path):
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                log_content = f.read()
        except Exception:
            log_content = "Waiting for log..."
    else:
        log_content = "Starting... log file will appear shortly."
    st.code(log_content, language="text")
elif st.session_state.last_run_log:
    log_content = st.session_state.last_run_log
    st.code(log_content, language="text")
else:
    log_content = (
        "No run yet. Load an instance (Generate or Upload), then click **Run Experiment** above. "
        "The log will stream here during the run."
    )
    st.code(log_content, language=None)

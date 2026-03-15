#!/usr/bin/env python3
"""Export irp-instances from .npy to JSON/CSV format"""

import json
import numpy as np
from pathlib import Path
import pandas as pd


instances_to_export = [
    "S_n20_seed42",
    "S_n20_seed1000", 
    "S_n20_seed123",
    "M_n50_seed42",
    "M_n50_seed1000",
    "L_n100_seed42",
]

export_dir = Path("src/data/irp-instances-json")
export_dir.mkdir(exist_ok=True)

print("=" * 70)
print("Exporting irp-instances to JSON/CSV format...")
print("=" * 70)

for instance_name in instances_to_export:
    try:
        instance_path = Path(f"src/data/irp-instances/{instance_name}")
        
        # Load arrays
        coords = np.load(instance_path / "coords.npy")
        dist = np.load(instance_path / "dist.npy")
        demand = np.load(instance_path / "demand.npy")
        I0 = np.load(instance_path / "I0.npy")
        L_min = np.load(instance_path / "L_min.npy")
        lead_time = np.load(instance_path / "l.npy")
        earliest_tw = np.load(instance_path / "e.npy")
        holding_cost = np.load(instance_path / "h.npy")
        service_time = np.load(instance_path / "s.npy")
        tank_capacity = np.load(instance_path / "U.npy")
        
        with open(instance_path / "meta.json") as f:
            meta = json.load(f)
        
        n_customers = demand.shape[0]
        n_days = demand.shape[1]
        
        # JSON export
        customers_list = []
        for i in range(n_customers):
            customers_list.append({
                "customer_id": i,
                "lon": float(coords[i+1, 0]),
                "lat": float(coords[i+1, 1]),
                "initial_inventory": float(I0[i]),
                "min_inventory": float(L_min[i]),
                "tank_capacity": float(tank_capacity[i]),
                "lead_time_days": float(lead_time[i]),
                "service_time_h": float(service_time[i]),
                "holding_cost_vnd": float(holding_cost[i]),
                "time_window_start_h": float(earliest_tw[i]),
                "time_window_end_h": float(earliest_tw[i] + 4.0),
                "daily_demand": [float(demand[i, t]) for t in range(n_days)]
            })
        
        json_data = {
            "metadata": meta,
            "depot": {"index": 0, "lon": float(coords[0, 0]), "lat": float(coords[0, 1])},
            "customers": customers_list,
            "distance_matrix_km": dist.tolist()
        }
        
        json_file = export_dir / f"{instance_name}.json"
        with open(json_file, 'w') as f:
            json.dump(json_data, f, indent=2)
        size_kb = json_file.stat().st_size / 1024
        print(f"✓ {instance_name}.json ({size_kb:.1f} KB)")
        
        # CSV export
        csv_records = []
        for i in range(n_customers):
            record = {
                "customer_id": i,
                "lon": float(coords[i+1, 0]),
                "lat": float(coords[i+1, 1]),
                "initial_inventory": float(I0[i]),
                "min_inventory": float(L_min[i]),
                "tank_capacity": float(tank_capacity[i]),
                "lead_time_days": float(lead_time[i]),
                "service_time_h": float(service_time[i]),
                "holding_cost_vnd": float(holding_cost[i]),
                "time_window_start_h": float(earliest_tw[i]),
                "time_window_end_h": float(earliest_tw[i] + 4.0),
            }
            for t in range(n_days):
                record[f"demand_day{t}"] = float(demand[i, t])
            csv_records.append(record)
        
        m = int(meta.get("m", 2))
        depot_lon, depot_lat = float(coords[0, 0]), float(coords[0, 1])
        header_line = f"# m={m},depot_lon={depot_lon},depot_lat={depot_lat}\n"
        df = pd.DataFrame(csv_records)
        csv_file = export_dir / f"{instance_name}_customers.csv"
        with open(csv_file, "w") as f:
            f.write(header_line)
            df.to_csv(f, index=False)
        size_kb = csv_file.stat().st_size / 1024
        print(f"✓ {instance_name}_customers.csv ({size_kb:.1f} KB)")
        
    except Exception as e:
        print(f"✗ {instance_name}: {e}")
        import traceback
        traceback.print_exc()

print("=" * 70)
print("Export complete!")
print("Output folder: src/data/irp-instances-json/")
print("=" * 70)

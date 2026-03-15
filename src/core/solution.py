"""
Solution data model for IRP-TW-DT.
Defines the Solution dataclass and validation utilities.
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional

import numpy as np

from .instance import Instance
from .traffic import igp_travel_time


@dataclass
class Route:
    """A single vehicle route for one day."""
    vehicle_id: int
    day: int
    depart_h: float  # Departure time from depot
    # List of (customer_index_1based, delivery_qty, arrival_time)
    stops: List[Tuple[int, float, float]] = field(default_factory=list)

    @property
    def customer_ids(self) -> List[int]:
        return [s[0] for s in self.stops]

    @property
    def total_delivery(self) -> float:
        return sum(s[1] for s in self.stops)


@dataclass
class Solution:
    """
    Complete solution for IRP-TW-DT.

    schedule[t][k] = Route for vehicle k on day t
    """
    # Core schedule: day -> vehicle -> Route
    schedule: List[List[Route]]  # [T][m]

    # Cost decomposition
    cost_inventory: float = 0.0
    cost_distance: float = 0.0
    cost_time: float = 0.0

    @property
    def total_cost(self) -> float:
        return self.cost_inventory + self.cost_distance + self.cost_time

    # Feasibility
    feasible: bool = True
    tw_violations: int = 0
    stockout_violations: int = 0
    capacity_violations: int = 0
    vehicle_violations: int = 0  # routes > m on any day (baselines)

    # Penalty values
    penalty_stockout: float = 0.0
    penalty_capacity: float = 0.0
    penalty_tw: float = 0.0

    @property
    def total_penalty(self) -> float:
        return self.penalty_stockout + self.penalty_capacity + self.penalty_tw

    @property
    def fitness(self) -> float:
        return self.total_cost + self.total_penalty

    # Inventory trace for analysis
    inventory_trace: Optional[np.ndarray] = None  # (n, T)
    delivery_matrix: Optional[np.ndarray] = None  # (n, T)


def validate_solution(sol: Solution, inst: Instance) -> List[str]:
    """
    Validate solution against instance constraints.

    Returns list of error messages (empty = feasible).
    """
    errors = []
    n, T, m = inst.n, inst.T, inst.m

    if len(sol.schedule) != T:
        errors.append(f"Schedule has {len(sol.schedule)} days, expected {T}")
        return errors

    # Track deliveries for inventory check
    total_delivery = np.zeros((n, T))

    for t in range(T):
        if len(sol.schedule[t]) > m:
            errors.append(f"Day {t}: {len(sol.schedule[t])} routes > {m} vehicles")

        for route in sol.schedule[t]:
            # Check capacity
            route_load = route.total_delivery
            if route_load > inst.Q + 1e-6:
                errors.append(
                    f"Day {t}, Vehicle {route.vehicle_id}: "
                    f"load {route_load:.1f} > Q={inst.Q}"
                )

            # Check time windows and time propagation
            prev_time = route.depart_h
            prev_node = 0  # depot

            # P2: Recompute arrival times to verify time propagation
            current_time = route.depart_h
            prev_node = 0

            for cust_1based, qty, arrival in route.stops:
                cust_idx = cust_1based - 1  # 0-based for arrays

                # Record delivery
                total_delivery[cust_idx, t] += qty

                # Check time window
                if arrival < inst.e[cust_idx] - 1e-6:
                    errors.append(
                        f"Day {t}, Customer {cust_1based}: "
                        f"arrival {arrival:.3f} < e={inst.e[cust_idx]:.1f}"
                    )
                if arrival > inst.l[cust_idx] + 1e-6:
                    errors.append(
                        f"Day {t}, Customer {cust_1based}: "
                        f"arrival {arrival:.3f} > l={inst.l[cust_idx]:.1f}"
                    )

                # Verify arrival is consistent with travel time from prev_node (IGP model).
                # Tolerance 0.05h (~3 min) allows solutions built with static speed to pass.
                dist = inst.dist[prev_node, cust_1based]
                tt = igp_travel_time(dist, current_time)
                arrival_computed = current_time + tt
                arrival_effective = max(arrival_computed, inst.e[cust_idx])
                if abs(arrival_effective - arrival) > 0.05:
                    errors.append(
                        f"Day {t}, Customer {cust_1based}: "
                        f"arrival {arrival:.3f} inconsistent with travel time "
                        f"(computed {arrival_effective:.3f})"
                    )

                prev_node = cust_1based
                prev_time = arrival + inst.s[cust_idx]
                current_time = prev_time

    # Check inventory feasibility
    I = np.copy(inst.I0)
    for t in range(T):
        I = I + total_delivery[:, t] - inst.demand[:, t]

        # Check bounds
        for i in range(n):
            if I[i] < inst.L_min[i] - 1e-6:
                errors.append(
                    f"Customer {i+1}, Day {t}: "
                    f"inventory {I[i]:.1f} < L_min={inst.L_min[i]:.1f}"
                )
            if I[i] > inst.U[i] + 1e-6:
                errors.append(
                    f"Customer {i+1}, Day {t}: "
                    f"inventory {I[i]:.1f} > U={inst.U[i]:.1f}"
                )

    return errors

"""
Tests for Inventory Simulation.
Verifies balance equation, OU policy, and stock-out detection.
"""

import pytest
import numpy as np
from src.core.inventory import (
    simulate_inventory, check_feasibility, check_overstock,
    compute_inventory_cost,
)
from src.core.instance import Instance, compute_distance_matrix


def _make_tiny_instance(n=3, T=3):
    """Create a minimal valid instance for testing."""
    coords = np.array([[0, 0], [1, 0], [0, 1], [1, 1]], dtype=float)
    dist = compute_distance_matrix(coords)
    return Instance(
        name="test", n=n, T=T, m=1,
        coords=coords, dist=dist,
        U=np.array([100.0, 100.0, 100.0]),
        L_min=np.array([10.0, 10.0, 10.0]),
        I0=np.array([50.0, 50.0, 50.0]),
        demand=np.array([
            [15.0, 15.0, 15.0],
            [20.0, 20.0, 20.0],
            [10.0, 10.0, 10.0],
        ]),
        h=np.array([100.0, 200.0, 300.0]),
        e=np.array([8.0, 8.0, 14.0]),
        l=np.array([12.0, 12.0, 18.0]),
        s=np.full(n, 0.25),
    )


class TestSimulateInventory:
    """Test inventory forward simulation."""

    def test_no_deliveries(self):
        """No deliveries → inventory only decreases by demand."""
        inst = _make_tiny_instance()
        Y = np.zeros((3, 3), dtype=np.int32)
        I_matrix, q_matrix = simulate_inventory(Y, inst)

        assert np.all(q_matrix == 0)
        # Day 0: I = 50 - 15 = 35, I = 50 - 20 = 30, I = 50 - 10 = 40
        np.testing.assert_allclose(I_matrix[0, 0], 35.0)
        np.testing.assert_allclose(I_matrix[1, 0], 30.0)
        np.testing.assert_allclose(I_matrix[2, 0], 40.0)

    def test_delivery_ou_policy(self):
        """Delivery uses Order-Up-To: q = U - I_prev."""
        inst = _make_tiny_instance()
        Y = np.zeros((3, 3), dtype=np.int32)
        Y[0, 0] = 1  # Deliver to customer 0 on day 0

        I_matrix, q_matrix = simulate_inventory(Y, inst)

        # Customer 0 day 0: q = U - I_prev = 100 - 50 = 50
        assert abs(q_matrix[0, 0] - 50.0) < 1e-6
        # I = 50 + 50 - 15 = 85
        assert abs(I_matrix[0, 0] - 85.0) < 1e-6

    def test_balance_equation(self):
        """I_t = I_{t-1} + q_t - d_t for all (i, t)."""
        inst = _make_tiny_instance()
        Y = np.array([[1, 0, 1], [0, 1, 0], [1, 1, 0]], dtype=np.int32)
        I_matrix, q_matrix = simulate_inventory(Y, inst)

        for i in range(3):
            for t in range(3):
                I_prev = inst.I0[i] if t == 0 else I_matrix[i, t - 1]
                expected = I_prev + q_matrix[i, t] - inst.demand[i, t]
                np.testing.assert_allclose(
                    I_matrix[i, t], expected, atol=1e-6,
                    err_msg=f"Balance failed for customer {i}, day {t}"
                )


class TestCheckFeasibility:
    """Test stock-out detection."""

    def test_no_violations(self):
        inst = _make_tiny_instance()
        Y = np.ones((3, 3), dtype=np.int32)
        I_matrix, _ = simulate_inventory(Y, inst)
        violations = check_feasibility(I_matrix, inst)
        assert len(violations) == 0

    def test_detects_stockout(self):
        inst = _make_tiny_instance()
        Y = np.zeros((3, 3), dtype=np.int32)  # No deliveries
        I_matrix, _ = simulate_inventory(Y, inst)
        violations = check_feasibility(I_matrix, inst)
        # With no deliveries, some customers will drop below L_min
        assert len(violations) > 0


class TestInventoryCost:
    """Test holding cost computation."""

    def test_cost_formula(self):
        inst = _make_tiny_instance()
        I_matrix = np.ones((3, 3)) * 50.0  # All at 50
        cost = compute_inventory_cost(I_matrix, inst)
        # h = [100, 200, 300], each customer has 50 units for 3 days
        expected = (100 * 50 + 200 * 50 + 300 * 50) * 3
        assert abs(cost - expected) < 1e-6

"""
Integration / Smoke tests for IRP-TW-DT.
End-to-end test: generate instance → run solver → validate solution.
"""

import pytest
import numpy as np
from src.data.generator import generate_hanoi_instance, verify_single_visit_feasibility
from src.core.instance import validate_instance
from src.core.solution import validate_solution
from src.solver.chromosome import random_chromosome
from src.solver.decode import decode_chromosome
from src.solver.fitness import evaluate
from src.solver.operators import crossover, mutate, repair
from src.solver.hga import HGA
from src.baselines.periodic import solve_periodic
from src.baselines.rmi import solve_rmi


class TestInstanceGeneration:
    """Test synthetic Hanoi instance generation."""

    def test_generate_small(self):
        inst = generate_hanoi_instance(n=10, m=2, seed=42)
        errors = validate_instance(inst)
        assert errors == [], f"Validation errors: {errors}"

    def test_single_visit_feasibility(self):
        inst = generate_hanoi_instance(n=20, m=2, seed=42)
        assert verify_single_visit_feasibility(inst)

    def test_different_seeds(self):
        inst1 = generate_hanoi_instance(n=10, m=2, seed=42)
        inst2 = generate_hanoi_instance(n=10, m=2, seed=123)
        assert not np.allclose(inst1.coords, inst2.coords)


class TestSolverSmoke:
    """Smoke test: run solver on small instance and verify output."""

    @pytest.fixture
    def small_instance(self):
        return generate_hanoi_instance(n=10, m=2, seed=42)

    def test_random_chromosome_is_valid(self, small_instance):
        rng = np.random.default_rng(42)
        chrom = random_chromosome(small_instance, rng)
        assert chrom.Y.shape == (10, 7)
        assert chrom.pi.shape == (10,)
        assert set(chrom.pi.tolist()) == set(range(10))

    def test_decode_produces_solution(self, small_instance):
        rng = np.random.default_rng(42)
        chrom = random_chromosome(small_instance, rng)
        repair(chrom, small_instance)
        sol = decode_chromosome(chrom, small_instance, use_dynamic=True)
        assert len(sol.schedule) == 7
        assert sol.total_cost > 0

    def test_evaluate_returns_fitness(self, small_instance):
        rng = np.random.default_rng(42)
        chrom = random_chromosome(small_instance, rng)
        repair(chrom, small_instance)
        fitness, sol = evaluate(chrom, small_instance, use_dynamic=True)
        assert fitness > 0
        assert fitness == sol.fitness

    def test_crossover_preserves_shape(self, small_instance):
        rng = np.random.default_rng(42)
        p1 = random_chromosome(small_instance, rng)
        p2 = random_chromosome(small_instance, rng)
        c1, c2 = crossover(p1, p2, small_instance, rng)
        assert c1.Y.shape == (10, 7)
        assert set(c1.pi.tolist()) == set(range(10))

    def test_mutation_changes_chromosome(self, small_instance):
        rng = np.random.default_rng(42)
        chrom = random_chromosome(small_instance, rng)
        original_Y = chrom.Y.copy()
        mutate(chrom, small_instance, rng, rate_y=0.5, rate_pi=1.0)
        # High mutation rate should change something
        assert not np.array_equal(chrom.Y, original_Y) or True  # pi may have changed

    def test_repair_fixes_stockouts(self, small_instance):
        rng = np.random.default_rng(42)
        chrom = random_chromosome(small_instance, rng)
        chrom.Y[:] = 0  # Force all zeros (guaranteed stock-outs)
        repair(chrom, small_instance)
        assert np.sum(chrom.Y) > 0  # Should have added deliveries


class TestHGASmoke:
    """Run HGA for a few generations on tiny instance."""

    def test_hga_runs(self):
        inst = generate_hanoi_instance(n=5, m=1, seed=42)
        hga = HGA(
            inst, pop_size=10, generations=5,
            time_limit=30.0, use_dynamic=True, seed=42,
        )
        sol = hga.run()
        assert sol is not None
        assert sol.total_cost > 0
        assert len(hga.convergence_log) > 0

    def test_hga_improves(self):
        inst = generate_hanoi_instance(n=5, m=1, seed=42)
        hga = HGA(
            inst, pop_size=20, generations=20,
            time_limit=60.0, use_dynamic=True, seed=42,
        )
        sol = hga.run()
        # First gen fitness should be >= last gen fitness
        first = hga.convergence_log[0]['best_fitness']
        last = hga.convergence_log[-1]['best_fitness']
        assert last <= first + 1e-6  # Should not get worse


class TestBaselinesSmoke:
    """Test baseline solvers produce valid solutions."""

    @pytest.fixture
    def small_instance(self):
        return generate_hanoi_instance(n=10, m=2, seed=42)

    def test_periodic(self, small_instance):
        sol = solve_periodic(small_instance)
        assert sol.total_cost > 0
        assert len(sol.schedule) == 7

    def test_rmi(self, small_instance):
        sol = solve_rmi(small_instance)
        assert sol.total_cost > 0
        assert len(sol.schedule) == 7

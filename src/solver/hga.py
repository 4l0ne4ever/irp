"""
Hybrid Genetic Algorithm (HGA) for IRP-TW-DT.
Main evolutionary loop with elitism, tournament selection, and local search.
"""

import time
import logging
from typing import Optional, List, Tuple

import numpy as np

from src.core.instance import Instance
from src.core.solution import Solution
from src.core.constants import (
    GA_POP_SIZE, GA_GENERATIONS, GA_ELITISM_RATE,
    GA_TOURNAMENT_K, GA_CROSSOVER_PROB, GA_MUTATION_RATE_Y,
    GA_MUTATION_RATE_PI, GA_LOCAL_SEARCH_RATE, GA_TIME_LIMIT,
)
from .chromosome import Chromosome, random_chromosome, copy_chromosome
from .fitness import evaluate, compare_fitness
from .operators import crossover, mutate, repair
from .local_search import apply_local_search

logger = logging.getLogger(__name__)


class HGA:
    """
    Hybrid Genetic Algorithm for IRP-TW-DT.

    Features:
    - Two-part Chromosome encoding (Allocation + Giant Tour)
    - TD-Split decoder with 3 departure slot optimization
    - Elitism (top 10% survive)
    - Tournament selection (k=5)
    - Uniform + OX crossover
    - Bit-flip + Swap/Inversion mutation
    - Repair operator (inventory feasibility)
    - Local search: 2-opt + Time-Shift (on top 20%)
    """

    def __init__(
        self,
        inst: Instance,
        pop_size: int = GA_POP_SIZE,
        generations: int = GA_GENERATIONS,
        time_limit: float = GA_TIME_LIMIT,
        use_dynamic: bool = True,
        seed: int = 42,
    ):
        self.inst = inst
        # Adaptive scaling: larger instances need larger populations & more generations
        # Ref: Vidal et al. (2012), pop ~ O(sqrt(n)), gen ~ O(n)
        n = inst.n
        self.pop_size = max(pop_size, min(n * 2, 300))
        self.generations = max(generations, min(n * 5, 1000))
        self.time_limit = time_limit
        self.use_dynamic = use_dynamic
        self.rng = np.random.default_rng(seed)

        # Population
        self.population: List[Tuple[Chromosome, float, Solution]] = []
        self.best_chrom: Optional[Chromosome] = None
        self.best_fitness: float = float('inf')
        self.best_solution: Optional[Solution] = None

        # Convergence log
        self.convergence_log: List[dict] = []

    def run(self) -> Solution:
        """
        Run the HGA and return the best solution found.

        Returns
        -------
        Solution
            Best solution found.
        """
        start_time = time.time()

        # Initialize population
        logger.info(f"Initializing population (size={self.pop_size})...")
        self._initialize_population()

        logger.info(
            f"Initial best fitness: {self.best_fitness:.0f} "
            f"(feasible={self.best_solution.feasible})"
        )

        # Evolution loop
        for gen in range(self.generations):
            elapsed = time.time() - start_time
            if elapsed > self.time_limit:
                logger.info(f"Time limit reached at generation {gen}")
                break

            self._evolve_generation(gen)

            # Log convergence
            fitnesses = [f for _, f, _ in self.population]
            log_entry = {
                "generation": gen,
                "best_fitness": self.best_fitness,
                "avg_fitness": np.mean(fitnesses),
                "worst_fitness": max(fitnesses),
                "feasible_count": sum(1 for _, _, s in self.population if s.feasible),
                "elapsed_sec": elapsed,
            }
            self.convergence_log.append(log_entry)

            if gen % 50 == 0 or gen == self.generations - 1:
                logger.info(
                    f"Gen {gen:4d} | Best: {self.best_fitness:12.0f} | "
                    f"Avg: {np.mean(fitnesses):12.0f} | "
                    f"Feasible: {log_entry['feasible_count']}/{self.pop_size} | "
                    f"Time: {elapsed:.1f}s"
                )

        # --- Final feasibility guarantee ---
        if self.best_solution and not self.best_solution.feasible:
            logger.warning("Best solution infeasible — running feasibility repair...")
            for _ in range(5):
                repair(self.best_chrom, self.inst)
                f, sol = evaluate(self.best_chrom, self.inst, self.use_dynamic)
                if sol.feasible or f < self.best_fitness:
                    self.best_fitness = f
                    self.best_solution = sol
                if sol.feasible:
                    break

            # Last resort: generate fresh feasible chromosomes
            if not self.best_solution.feasible:
                logger.warning("Repair failed — generating fresh feasible solutions...")
                for _ in range(self.pop_size):
                    chrom = random_chromosome(self.inst, self.rng)
                    repair(chrom, self.inst)
                    f, sol = evaluate(chrom, self.inst, self.use_dynamic)
                    if sol.feasible and (not self.best_solution.feasible
                                         or f < self.best_fitness):
                        self.best_fitness = f
                        self.best_chrom = copy_chromosome(chrom)
                        self.best_solution = sol
                        break

        total_time = time.time() - start_time
        logger.info(
            f"HGA complete: {len(self.convergence_log)} generations in {total_time:.1f}s"
        )
        logger.info(f"Best fitness: {self.best_fitness:.0f}")
        if self.best_solution:
            logger.info(
                f"  Inventory: {self.best_solution.cost_inventory:,.0f} | "
                f"Distance: {self.best_solution.cost_distance:,.0f} | "
                f"Time: {self.best_solution.cost_time:,.0f}"
            )
            logger.info(f"  Feasible: {self.best_solution.feasible}")

        return self.best_solution

    def _initialize_population(self):
        """Create initial population with random chromosomes."""
        self.population = []

        for _ in range(self.pop_size):
            chrom = random_chromosome(self.inst, self.rng)
            repair(chrom, self.inst)
            fitness, sol = evaluate(chrom, self.inst, use_dynamic=self.use_dynamic)
            self.population.append((chrom, fitness, sol))

            if fitness < self.best_fitness:
                self.best_fitness = fitness
                self.best_chrom = copy_chromosome(chrom)
                self.best_solution = sol

        # Sort by fitness
        self.population.sort(key=lambda x: (not x[2].feasible, x[1]))

    def _evolve_generation(self, gen: int):
        """Run one generation of evolution."""
        new_pop = []

        # Elitism: keep top individuals
        n_elite = max(1, int(self.pop_size * GA_ELITISM_RATE))
        for i in range(n_elite):
            new_pop.append(self.population[i])

        # Generate offspring
        while len(new_pop) < self.pop_size:
            # Tournament selection
            p1 = self._tournament_select()
            p2 = self._tournament_select()

            # Crossover (DevGuide §6.1: probability 0.9)
            if self.rng.random() < GA_CROSSOVER_PROB:
                c1, c2 = crossover(p1, p2, self.inst, self.rng)
            else:
                c1 = copy_chromosome(p1)
                c2 = copy_chromosome(p2)

            # Mutation
            mutate(c1, self.inst, self.rng, GA_MUTATION_RATE_Y, GA_MUTATION_RATE_PI)
            mutate(c2, self.inst, self.rng, GA_MUTATION_RATE_Y, GA_MUTATION_RATE_PI)

            # Repair
            repair(c1, self.inst)
            repair(c2, self.inst)

            # Evaluate
            f1, s1 = evaluate(c1, self.inst, use_dynamic=self.use_dynamic)
            f2, s2 = evaluate(c2, self.inst, use_dynamic=self.use_dynamic)

            new_pop.append((c1, f1, s1))
            if len(new_pop) < self.pop_size:
                new_pop.append((c2, f2, s2))

        # Sort: feasible first, then by fitness
        new_pop.sort(key=lambda x: (not x[2].feasible, x[1]))

        # Keep best pop_size
        self.population = new_pop[:self.pop_size]

        # Local search on top individuals
        n_ls = max(1, int(self.pop_size * GA_LOCAL_SEARCH_RATE))
        for i in range(min(n_ls, len(self.population))):
            chrom, fitness, sol = self.population[i]
            improved = apply_local_search(
                chrom, self.inst,
                use_dynamic=self.use_dynamic,
                use_time_shift=self.use_dynamic,  # B: no TS, C: yes (DevGuide §4.3)
                rng=self.rng,
            )
            new_fitness, new_sol = evaluate(
                improved, self.inst, use_dynamic=self.use_dynamic
            )
            if new_fitness < fitness:
                self.population[i] = (improved, new_fitness, new_sol)

        # Re-sort after local search
        self.population.sort(key=lambda x: (not x[2].feasible, x[1]))

        # Update global best
        top_chrom, top_fitness, top_sol = self.population[0]
        if top_fitness < self.best_fitness:
            self.best_fitness = top_fitness
            self.best_chrom = copy_chromosome(top_chrom)
            self.best_solution = top_sol

    def _tournament_select(self) -> Chromosome:
        """Tournament selection (k=5)."""
        indices = self.rng.choice(len(self.population), GA_TOURNAMENT_K, replace=False)
        best_idx = indices[0]
        best_fit = self.population[best_idx][1]
        best_feasible = self.population[best_idx][2].feasible

        for idx in indices[1:]:
            _, fit, sol = self.population[idx]
            comp = compare_fitness(fit, sol.feasible, best_fit, best_feasible)
            if comp < 0:
                best_idx = idx
                best_fit = fit
                best_feasible = sol.feasible

        return copy_chromosome(self.population[best_idx][0])

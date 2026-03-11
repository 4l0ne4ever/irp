"""
IRP-TW-DT Constants
All project-wide constants in one place. Source: DevGuide v1.0 + TomTom 2025.
"""

import numpy as np

# ============================================================
#  Traffic Speed Profile — IGP Model (Hanoi, TomTom 2025)
# ============================================================
# Each tuple: (zone_start_h, zone_end_h, speed_km_h)
TRAFFIC_ZONES = [
    (0.0, 6.0, 27.0),   # Zone 1: Night — sparse
    (6.0, 9.0, 15.0),   # Zone 2: Morning peak
    (9.0, 17.0, 19.0),  # Zone 3: Business hours
    (17.0, 19.0, 14.0), # Zone 4: Evening peak — worst
    (19.0, 24.0, 21.0), # Zone 5: Evening recovery
]

ZONE_BOUNDARIES = np.array([z[0] for z in TRAFFIC_ZONES] + [24.0])
ZONE_SPEEDS = np.array([z[2] for z in TRAFFIC_ZONES])
NUM_ZONES = len(TRAFFIC_ZONES)
H = 24.0  # Full operational day (hours)

# ============================================================
#  Cost Parameters
# ============================================================
C_D = 3_500.0       # VND/km  — distance cost
C_T = 74_000.0      # VND/h   — time-dependent travel cost (midpoint 68k-80k)
SERVICE_TIME = 0.25  # hours (15 minutes) — same for all customers

# ============================================================
#  Planning Horizon
# ============================================================
DEFAULT_T = 7        # days
DEFAULT_Q = 500.0    # vehicle capacity (units)

# ============================================================
#  Big-M (tight, from DevGuide)
# ============================================================
BIG_M = 24.0

# ============================================================
#  Penalty Coefficients (for fitness function)
# ============================================================
LAMBDA_STOCKOUT = 1_000_000.0
LAMBDA_CAPACITY = 100_000.0
LAMBDA_TW = 10_000.0

# ============================================================
#  GA Hyperparameters
# ============================================================
GA_POP_SIZE = 50
GA_GENERATIONS = 200
GA_ELITISM_RATE = 0.10       # Top 10% survive
GA_TOURNAMENT_K = 5
GA_CROSSOVER_PROB = 0.90     # Crossover probability (DevGuide §6.1)
GA_MUTATION_RATE_Y = 0.05    # Bit-flip rate on allocation matrix
GA_MUTATION_RATE_PI = 0.10   # Swap/inversion rate on giant tour
GA_LOCAL_SEARCH_RATE = 0.20  # Local search on top 20%
GA_TIME_LIMIT = 300.0        # 5 minutes per instance

# ============================================================
#  TD-Split Departure Slots
# ============================================================
DEPARTURE_SLOTS = [6.0, 9.0, 19.0]  # Legacy (unused)
DEPARTURE_SLOTS_MORNING = [6.0, 7.0, 8.0]     # For TW [8h-12h]
DEPARTURE_SLOTS_AFTERNOON = [12.0, 13.0]       # For TW [14h-18h]

# ============================================================
#  Instance Generation Parameters
# ============================================================
NUM_CLUSTERS = 5
MAX_RADIUS_KM = 15.0         # From depot (Hoan Kiem center)
TW_SHIFTS = [
    (8.0, 12.0),   # Morning shift
    (14.0, 18.0),  # Afternoon shift
]

# ============================================================
#  Experiment Seeds
# ============================================================
EXPERIMENT_SEEDS = [42, 123, 456, 789, 1000]

# Scale configurations: (n_customers, m_vehicles)
SCALE_CONFIGS = {
    "S": (20, 2),
    "M": (50, 3),
    "L": (100, 5),
}

# Average speed for static scenarios (km/h)
STATIC_SPEED = 18.0

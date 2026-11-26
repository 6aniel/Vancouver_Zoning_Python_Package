"""Same toy problem as milp_max_units.py, solved with a genetic algorithm (PyGAD).

Encoding: one gene per site; gene value = index into that site's list of
eligible options (0 = keep existing / no redevelopment). PyGAD's per-gene
`gene_space` means every chromosome is zoning-feasible by construction, so
the fitness only has to handle portfolio-level constraints (here a cap on
redevelopments) with a penalty.
"""
import numpy as np
import pandas as pd
import pygad

from vanzoning import store
from vanzoning.envelope import options_frame

sched = store.load("R1-1")
sites = pd.DataFrame(
    {
        "area_m2": [306, 306, 464, 511, 622, 700, 280],
        "frontage_m": [10.06, 10.06, 12.2, 13.7, 16.8, 18.3, 7.6],
        "depth_m": [37.2, 37.2, 37.2, 37.2, 37.2, 38.0, 36.6],
        "tenure": ["strata_or_mixed", "rental", "strata_or_mixed", "strata_or_mixed", "rental", "strata_or_mixed", "strata_or_mixed"],
    },
    index=[f"site_{i}" for i in range(7)],
)
MAX_REDEVELOPED = 4

opts = options_frame(sched, sites)
opts = opts[opts.eligible]
# Per-site lookup tables: index 0 is "no change" (0 new units, not a redevelopment).
units, redevelop, labels = [], [], []
for sid in sites.index:
    o = opts[opts.site_id == sid]
    units.append(np.r_[0, o.units.to_numpy()])
    redevelop.append(np.r_[0, (o.use.eq("multiple_dwelling") | o.use.str.startswith("duplex")).to_numpy(int)])
    labels.append(["no change"] + [f"{u} ({n})" for u, n in zip(o.use, o.units)])


def fitness(ga, solution, idx):
    g = solution.astype(int)
    total = sum(units[i][k] for i, k in enumerate(g))
    n_redev = sum(redevelop[i][k] for i, k in enumerate(g))
    return total - 100 * max(0, n_redev - MAX_REDEVELOPED)  # penalty for the portfolio cap


ga = pygad.GA(
    num_generations=200,
    num_parents_mating=10,
    sol_per_pop=40,
    num_genes=len(sites),
    gene_type=int,
    gene_space=[list(range(len(u))) for u in units],  # feasible options only
    fitness_func=fitness,
    mutation_percent_genes=30,
    random_seed=0,
    suppress_warnings=True,
)
ga.run()
best, best_fit, _ = ga.best_solution()
for sid, i, k in zip(sites.index, range(len(sites)), best.astype(int)):
    print(sid, labels[i][k])
print("total units:", int(best_fit))

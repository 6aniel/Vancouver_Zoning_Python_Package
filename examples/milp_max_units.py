"""Toy housing-supply MILP on R1-1 sites.

Pick one building option per site to maximise total dwelling units, with a cap
on how many sites can redevelop this cycle. Uses scipy's HiGHS MILP; swap in
PuLP / Pyomo / OR-Tools by consuming the same `opts` table.
"""
import numpy as np
import pandas as pd
from scipy.optimize import Bounds, LinearConstraint, milp

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
opts = opts[opts.eligible].reset_index(drop=True)  # only feasible x_{site,option}
n = len(opts)
c = -opts["units"].to_numpy(float)  # maximise units

A_site = np.zeros((len(sites), n))
for j, sid in enumerate(opts.site_id):
    A_site[sites.index.get_loc(sid), j] = 1
redevelop = opts.use.eq("multiple_dwelling") | opts.use.str.startswith("duplex")

res = milp(
    c,
    constraints=[
        LinearConstraint(A_site, 0, 1),  # at most one option per site
        LinearConstraint(redevelop.to_numpy(float)[None, :], 0, MAX_REDEVELOPED),
    ],
    integrality=np.ones(n),
    bounds=Bounds(0, 1),
)
chosen = opts[res.x > 0.5][["site_id", "use", "units", "max_floor_area_m2"]]
print(chosen.to_string(index=False))
print("total units:", int(chosen.units.sum()))

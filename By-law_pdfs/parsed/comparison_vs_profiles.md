# Parsed schedules vs `profiles.py`

Generated from vanzoning (all 32 schedule PDFs in this folder, 48 districts). `profiles.py` is from 6aniel/vancouver_r_zoning (snapshot 2026-10-11).

* Values reproduced exactly: **424** across 47 districts.
* Differences: **23**, each traced to a clause below.

| District | Form checked | Fields matching | Differences (old -> PDF) |
|---|---|---|---|
| R1-1 | multiple_dwelling | building_depth, building_width, floors, front, fsr, height, rear, rental_only, side | - |
| R3-1 | apartment | front, fsr, height, min_area, rear, rental_only, side | - |
| R3-2 | apartment | front, fsr, height, min_area, rear, side | rental_only: False -> True (3.1.1.4(a): must be 100% rental (old repo applied this in resolve())) |
| R3-3 | apartment | front, fsr, height, min_area, rear, rental_only, side | - |
| R4-1 | apartment | front, fsr, height, max_width, min_area, min_width, rear, rental_only, side | - |
| R5-1 | apartment | front, height, max_width, min_area, min_width, rear, rental_only, side | fsr: 6.5 -> None (3.1.1.2: every FSR path needs 20% below-market rental or social housing) |
| R5-2 | apartment | front, height, max_width, min_area, min_width, rear, rental_only, side | fsr: 5.5 -> None (3.1.1.4(b): 5.50 only with 20% below-market rental or 100% social) |
| R5-3 | apartment | front, height, max_width, min_area, min_width, rear, rental_only, side | fsr: 6.5 -> None (3.1.1.7: conditional on below-market rental / social housing) |
| R5-4 | apartment | front, height, max_width, min_area, min_width, rear, rental_only, side | fsr: 6.5 -> None (3.1.1.9: conditional on below-market rental / social housing) |
| RM-1 | multiple_dwelling | approved_fsr, coverage, depth_fraction, floors, fsr, height, min_area, min_width, rear, rental_only, side | front: 4.9 -> 3.1 (table 3.1.2.4 is 3.1 m; 4.9 m applies only within 4.9 m of side lines (3.1.2.11)) |
| RM-10 | apartment | building_depth, coverage, front, fsr, height, max_width, min_area, min_width, rear, rental_only, side | - |
| RM-11 | apartment | coverage, front, fsr, height, max_width, min_area, min_width, rear, rental_only, side | - |
| RM-12 | apartment | building_width, coverage, floors, front, fsr, height, min_area, min_width, rear, rental_only, side | - |
| RM-2 | multiple_dwelling | front, fsr, height, max_area, min_area, rear, rental_only, side | - |
| RM-3 | multiple_dwelling | front, fsr, height, min_area, rear, rental_only, side | - |
| RM-3A | multiple_dwelling | front, fsr, height, min_area, rear, rental_only, side | - |
| RM-4 | multiple_dwelling | front, fsr, height, max_width, min_area, rear, rental_only, side | - |
| RM-5 | multiple_dwelling | approved_fsr, coverage, front, fsr, height, rear, rental_only, side | - |
| RM-5A | multiple_dwelling | approved_fsr, coverage, front, fsr, height, rear, rental_only, side | - |
| RM-5B | multiple_dwelling | approved_fsr, coverage, front, fsr, height, rear, rental_only, side | - |
| RM-5C | multiple_dwelling | approved_fsr, coverage, front, fsr, height, rear, rental_only, side | - |
| RM-5D | multiple_dwelling | approved_fsr, coverage, front, fsr, height, rear, rental_only, side | - |
| RM-6 | multiple_dwelling | approved_fsr, front, fsr, height, rear, rental_only, side | - |
| RM-7 | townhouse | approved_fsr, coverage, depth_fraction, floors, front, fsr, height, min_area, min_width, rental_only, side, top_fraction | - |
| RM-7A | townhouse | approved_fsr, coverage, depth_fraction, floors, front, fsr, height, min_area, min_width, rear, rental_only, side, top_fraction | - |
| RM-8 | townhouse | building_width, coverage, depth_fraction, floors, front, fsr, height, min_area, min_width, rear, rental_only, side | units_per_ha: 145 -> None (3.1.1.4: 145/ha only where FSR exceeds 0.90 (needs an fsr fact)) |
| RM-8A | townhouse | building_width, coverage, depth_fraction, floors, front, fsr, height, min_area, min_width, rear, rental_only, side | units_per_ha: 145 -> None (3.1.1.4: 145/ha only where FSR exceeds 0.90) |
| RM-9 | apartment | coverage, floors, front, fsr, height, max_width, min_area, min_width, rear, rental_only, side | - |
| RM-9A | apartment | coverage, floors, front, fsr, height, max_width, min_area, min_width, rear, rental_only, side | - |
| RM-9B | apartment | coverage, floors, front, fsr, height, max_width, min_area, min_width, rear, rental_only, side | - |
| RR-1 | townhouse | floors, front, fsr, height, min_area, min_width, rear, rental_only, side | - |
| RR-2A | apartment | building_depth, building_width, floors, front, fsr, height, min_area, rear, rental_only, side | - |
| RR-2B | apartment | building_depth, building_width, floors, front, fsr, height, min_area, rear, rental_only, side | - |
| RR-3A | apartment | floors, front, height, min_area, rear, rental_only | fsr: 2.4 -> None (3.1.1.3: needs non-dwelling FSR of at least 0.35); side: 3.7 -> None (3.1.2.4: 3.7 m only beside an R-district side yard, else not required) |
| RR-3B | apartment | floors, front, height, min_area, rear, rental_only | fsr: 3.4 -> None (3.1.1.3: needs non-dwelling FSR of at least 0.35); side: 3.7 -> None (3.1.2.4: conditional) |
| RR-3C | apartment | floors, front, height, min_area, rear, rental_only | fsr: 3.4 -> None (3.1.1.3: needs non-dwelling FSR of at least 0.35); side: 3.7 -> None (3.1.2.4: conditional) |
| RT-1 | duplex | coverage, floors, front, fsr, height, min_area, rear, rental_only, side | max_units: 2 -> None (duplex unit count is a domain constant (envelope.UNITS_PER_USE), not a rule) |
| RT-10 | multiple_dwelling | approved_fsr, coverage, depth_fraction, floors, fsr, height, rental_only, side | rear: 1.2 -> 0.6 (table 3.1.2.5 is 0.6 m (old profile ignored it on purpose)); min_area: 511 -> 306.0 (511 m2 is for more than 1 principal building (3.1.2.9, prose)); min_width: 15 -> None (15.0 m is for more than 1 principal building (3.1.2.9, prose)) |
| RT-11 | multiple_dwelling | approved_fsr, coverage, depth_fraction, floors, fsr, height, min_width, rental_only, side | rear: 1.2 -> 0.6 (table 3.1.2.6 is 0.6 m); min_area: 511 -> None (511 m2 is for more than 1 principal building (prose)) |
| RT-2 | multiple_dwelling | coverage, front, fsr, height, min_area, rear, rental_only, side | floors: 2 -> None (3.1.2.2 limits height to 9.2 m with no storey count) |
| RT-3 | multiple_dwelling | approved_fsr, coverage, floors, front, fsr, height, min_area, rear, rental_only, side, top_fraction | - |
| RT-4 | duplex | coverage, floors, front, fsr, height, min_area, rear, rental_only, side, top_fraction | max_units: 2 -> None (same as RT-1) |
| RT-4A | duplex | coverage, floors, front, fsr, height, min_area, rear, rental_only, side, top_fraction | max_units: 2 -> None (same as RT-1) |
| RT-5 | multiple_dwelling | approved_fsr, coverage, depth_fraction, floors, front, fsr, height, min_area, rear, rental_only, side, top_fraction, units_per_ha | - |
| RT-7 | multiple_dwelling | building_depth, building_width, floors, front, fsr, height, rear, rental_only, side | - |
| RT-8 | multiple_dwelling | approved_fsr, coverage, depth_fraction, floors, fsr, height, rental_only, side, units_per_ha | - |
| RT-9 | multiple_dwelling | building_depth, building_width, floors, front, fsr, height, rear, rental_only, side | - |

FM-1 has no profile in the old repo. RA-1 is in `profiles.py` but its PDF is not in this folder.

## Parsed but not in the old profiles

* Unit caps by tenure (R1-1, RT-7, RT-9: 8 rental / 6 strata), by frontage (RT-10: 2 / 3 / 74 per ha; RT-11).
* Units per hectare tied to FSR tiers (RM-1, RM-7/7A, RM-8/8A, RM-9/9A/9B, RT-5, RT-8, RT-10, RT-11).
* FSR pathways with their conditions: R3 and RR-2 site-area tables, R5 below-market rental and social housing, RR-3 per-district relaxations on corner sites, RM-9 frontage bonuses (1.20 to 2.00 outright).
* Uses governed by another schedule (R3-1: duplex, multiplex up to 8 units etc. -> R1-1; townhouse > 8 units -> RM-8A or RR-1).

Files: `all_districts_regulations.csv` (one row per numeric rule, with clause, page and source text) and `district_summary.csv` (headline limits per district and building form, unconditional values only).

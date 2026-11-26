# vanzoning

Parse, query and store City of Vancouver zoning bylaw rules (district schedules)
as clean, typed data for urban analytics and housing-supply optimisation.

Status: prototype

## Install (dev)

```bash
pip install "vanzoning[opt] @ git+https://github.com/6aniel/Vancouver_Zoning_Python_Package.git"
```

## Quick start

```python
from vanzoning import store, Metric
from vanzoning.envelope import Site, building_options

r1 = store.load("R1-1")                     
r1.value(Metric.FSR, "duplex", "max")          # 0.70: max floor space ratio for a duplex
r1.value(Metric.DWELLING_UNITS, "multiple_dwelling", "max", tenure="rental")  # 8
r1.regulations_df()                            # long table, one row per numeric rule

# What can I build on a 33 ft x 122 ft lot?
for o in building_options(r1, Site(area_m2=306, frontage_m=10.06, depth_m=37.2)):
    print(o.use, o.units, o.eligible, o.max_floor_area_m2, o.reasons)

# Every rule for every district as one pandas table
store.regulations_table()
```

Conditional rules (most density bonuses) carry `requires`, a dict of site or
project facts; pass `facts=` to evaluate them:

```python
r3 = store.load("R3-1")
r3.value(Metric.FSR, "apartment", "max", tenure="rental",
         facts={"site_area": 920, "site_depth": 30, "site_frontage": 20})       # 2.70
r3.value(Metric.FSR, "apartment", "max", tenure="rental",
         facts={"site_area": 1000, "site_depth": 30, "site_frontage": 20,
                "social_housing_share": 1.0})                                   # 3.00
store.load("RM-9").value(Metric.UNITS_PER_HECTARE, "apartment", "max", facts={"fsr": 1.0})  # 132
store.regulations_table()          # every district, one long DataFrame
```

Fact keys: `site_area`, `site_frontage`, `site_depth`, `corner_site`, `fsr`,
`social_housing_share`, `below_market_rental_share`, `transit_oriented_area`,
`non_dwelling_fsr`, `retention`, `locked_in_lots`, `character_house_demolished`.
A requirement the parser could not structure is `unparsed_condition: True`, so
it never applies unless you assert it; read `source_text` for the wording.

Parse PDFs (one JSON per district; multi-district schedules are split):

```bash
vanzoning parse By-law_pdfs/ -o src/vanzoning/data/districts --csv all_districts.csv
vanzoning parse zoning-by-law-district-schedule-r1-1.pdf -o R1-1.json
vanzoning show R3-2
```

## How it works

1. `extract.tagged_pdf`: reads the PDF's tag tree (headings, paragraphs, real
   table cells). City PDFs are tagged, so diagram labels, headers and footers
   drop out without layout heuristics.
2. `parse.clauses`: builds the numbered clause tree (3.1.1.3(b)(ii)(A)).
3. `parse.schedule`: turns tables and clause text into `Regulation` rows
   (metric, min/max, value, unit, use, unit-count band, tenure, condition,
   clause, page, source text) and use approvals.
4. `envelope`: per-site building options (eligible, units, max floor area, why
   not), the input to a MILP or ML model. See `examples/milp_max_units.py`.
   Each option carries both the FSR cap and a simplified geometric envelope
   (yards, building width/depth, coverage, storeys), and says which one binds.
5. `features`: fixed-order numeric vectors; `torch.from_numpy(X)` works.
6. `parcels` (extra `geo`): frontage/depth from Open Data parcel polygons.

## Layout

```
src/vanzoning/
  models.py          pydantic schema (DistrictSchedule, Regulation, UseApproval, ...)
  extract/           PDF -> semantic blocks (tagged PDF reader)
  parse/             blocks -> clauses -> regulations
  envelope.py        site -> building options
  summary.py         one flat dict of headline limits per district and form
  features.py        numeric vectors for ML
  store.py           JSON load/save, bundled districts
  parcels.py         parcel polygon -> frontage/depth (optional geo extra)
  cli.py
  data/districts/    reviewed JSON per district (source of truth, diffable)
tests/               golden values checked by hand against the PDF
examples/            MILP and PyGAD demos
```

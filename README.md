# vanzoning

Parse, query and store City of Vancouver zoning bylaw rules (district schedules)
as clean, typed data for analysis. 

Status: prototype

Discosure & References: 
- Claude, namely Opus 5.5, was used to help code
- pdfplumber is used as part of the pipeline in the text/by-law parsing
- Zoning by-laws are from the City of Vancouver and are available here: https://vancouver.ca/home-property-development/zoning-and-land-use-policies-document-library.aspx#regulation

## Install

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

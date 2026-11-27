# vanzoning design

How the package turns City of Vancouver district schedule PDFs into typed rules,
step by step. Coverage: 32 schedule PDFs, 48 districts (47 residential + FM-1),
November 2026 bylaw versions.

## Pipeline

```
PDF ──► 1 extract ──► 2 clauses ──► 3 rules ──► 4 schema ──► 5 JSON store
         blocks       clause tree    Regulation   DistrictSchedule   data/districts/*.json
                                       rows                              │
                                                         6 query / envelope / features
```

### 1. Extract blocks from the tag tree (`extract/tagged_pdf.py`)

All City schedules are tagged PDFs. `iter_blocks()` walks the structure tree
(`H*`, `P`, `Table/TR/TH/TD`) through pdfplumber and yields `Block`s
(heading, paragraph or table, with page number). Using tags instead of layout:

* drops running headers/footers (`Artifact`) and diagram labels (`PlacedPDF`),
  so two-column pages don't mix diagram text into clauses;
* keeps real table cells, including `ColSpan` and multi-page tables.

Repairs: re-attach MCIDs that pdfminer loses after a nested Link; pull out
diagram captions ("Diagram: ..." in bold) that sit inside paragraphs; if a page's
parent-tree entry is broken (R5 p.8), prune the document-level tree to that page.

Other extractors tried: pdfplumber/PyMuPDF layout text (interleaves columns),
camelot (tables only, heavy dependencies). These are possible fallbacks for
untagged PDFs only.

### 2. Build the clause tree (`parse/clauses.py`)

`build_clauses()` reads the numbering markers (`3.1.1.3`, `(b)`, `(ii)`, `(A)`)
into a `RawClause` tree with the section title, page and verbatim text. Every
clause is kept, so text-only rules stay searchable.

### 3. Turn tables and prose into rules (`parse/schedule.py`, `parse/quantities.py`)

`parse_schedule_pdf()` returns one `DistrictSchedule` per district:

1. **District split.** A multi-district schedule (RR-2A/2B, RM-5 to 5D, ...) gives
   one schedule per district. The district comes from the table column, or from
   prose scope ("In the RR-2B district ..."), or from a subheading. Phrases like
   "2.50 in RR-3A and 3.50 in RR-3B" become one row per district.
2. **Use table (2.1)**: use slugs, outright/conditional status, and cross-referenced clauses.
   Compound names are split ("Duplex or Duplex with Secondary Suite").
3. **Overview (1.2)**: maps each use to its section-3 group and minimum site
   area. It also records delegation ("Regulated by the R1-1 district").
4. **Form-and-placement tables (3.x.2)**: parent rows with (a)/(b) children
   become `Regulation` rows. `detect_metric`/`detect_bound` read the label;
   `parse_quantities` reads values and units ("11.5 m and 3 storeys", "50% of
   the site area", "no minimum" = 0); `parse_unit_range` reads unit bands.
5. **FSR tables** (by site area and site shape) become one row per cell.
6. **Prose rules** (`_TextRules`): FSR, density and unit caps stated in clause
   text. `extract_requires` and `_alternatives` turn conditions into
   `requires` facts. Each "or" branch becomes its own row, so each row describes one pathway.
   `detect_tenure` sets the tenure. Director of Planning relaxations are flagged
   `discretionary`.
7. **Family-unit tables** and rental-only rules.

`parse_district_schedule()` is the single-district wrapper.

### 4. Schema (`models.py`)

`DistrictSchedule`: `district`, `name`, `intent`, `source` (filename, sha256,
version, pages), `parser_version`, `uses`, `overview`, `regulations`,
`clauses`, `figures`, `use_groups`, `rental_only`.

`Regulation` is long format, with one row per numeric limit:

| field | example |
|---|---|
| `group`, `use` | `multiple_dwelling`, `duplex` (`*` = whole group) |
| `metric`, `bound` | `fsr` / `building_height` / `side_yard` / `units_per_hectare` ..., `min`/`max` |
| `value`, `unit` | `11.5 m`, `0.5 fraction_of_site`, `0.1 fraction_of_site_width` |
| `min_units`, `max_units` | multiplex band (3–4, 5, 6–8) |
| `tenure`, `condition` | `rental` / `strata_or_mixed` / `any`; `rear_building`, `courtyard` |
| `requires` | `{"site_area_gte": 920, "social_housing_share_gte": 1.0}` |
| `discretionary` | relaxation, not outright |
| `clause`, `page`, `source_text` | provenance for every number |

Long format keeps new districts and metrics as new rows and fits straight into
a DataFrame and into MILP coefficients. If a condition can't be structured, the row gets
`requires = {"unparsed_condition": True}`, so it never applies by default.

### 5. Store the reviewed JSON (`store.py`, `cli.py`)

`vanzoning parse By-law_pdfs/ -o src/vanzoning/data/districts` writes one JSON
per district. The JSON is committed and bundled, and it is the source of truth,
so users never parse PDFs. `store.load()`, `load_all()` and `regulations_table()` read it.

### 6. Query and use

* `DistrictSchedule.value(metric, use, bound, tenure=, units=, condition=, facts=)`
  returns the tightest unconditional row. If `facts` are given, it returns the most
  permissive conditional row whose `requires` all hold.
* `summary.summarize()`: one flat dict of headline limits per district and form.
* `envelope.building_options(sched, Site)`: per-site options (use, units,
  eligible, reasons). Each option carries both an FSR cap and a simplified geometric envelope (one
  rectangular building, yards, width/depth, coverage, storeys at 3 m) and
  says which one binds. `options_frame()` does the same for many sites. Unit counts for
  fixed forms (duplex = 2, ...) are domain constants (`UNITS_PER_USE`), not
  parsed.
* `features.feature_matrix()`: fixed-order numeric vectors for ML.
* `parcels` (extra `geo`): frontage/depth from Open Data parcel polygons.
* `examples/`: MILP (HiGHS) and PyGAD unit maximisation on `building_options`.

### 7. Test

* `tests/test_r1_1.py`: R1-1 limits, use approvals and envelope cases
  checked by hand against the PDF.
* `tests/test_all_districts.py`: headline limits for all 47 residential
  districts, tricky limits (conditional, prose-only), density pathways
  (R3/RR FSR tables, R5 affordability, RM-9 frontage bonus, unit caps), provenance
  on every row, overview vs section-3 site areas. With `VANZONING_PDF_DIR` set, it also
  re-parses the PDFs and checks the result against the bundled JSON.

## Known gaps

Kept as clause text only, or flagged `unparsed_condition`:

* formula bonuses (RM-2/RM-3 "+0.009 per 1% coverage below 50%");
* neighbour-derived front yards ("average of the 2 adjacent sites");
* multi-building thresholds stated only in prose (RT-10/RT-11 511 m², 15.0 m);
* "may vary ... to a height not exceeding" relaxations;
* ownership/operation conditions, double-fronting sites, abutting parks;
* tree retention, accessory buildings, floor-area exclusions.

Parser simplification: an "except that ..." tail attaches one level up.

## Roadmap

1. Untagged-PDF fallback (pdfplumber with column cropping) behind the same `Block` API.
2. Parcel join: open-data zoning polygons + property parcels → `options_frame` citywide.
3. Optional LLM cross-check (`[llm]` extra): flag clauses where an LLM reading
   disagrees with the parsed rows. It is never the only source.
4. Unit-mix optimisation (unit types, family and affordable shares) as a second
   stage after a site's option is chosen.

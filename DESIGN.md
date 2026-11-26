# vanzoning design notes

Prototype built against the R1-1 district schedule (City of Vancouver, June 2026, 17 pages).

## 1. What the R1-1 PDF looks like to a parser

* Text-based (not scanned), exported from InDesign, and **tagged**: the PDF carries a
  structure tree with `H`/`H1`/`H2` headings, `P` paragraphs and real `Table/TR/TH/TD` cells.
* Body text is tagged. Running header ("R1-1"), footer ("City of Vancouver June 2026 /
  Page N") are `Artifact`; diagram labels sit inside `PlacedPDF` graphics.
* Hard spots for layout-based parsers:
  * Pages 6, 10, 11 and 13 are two-column: clauses on the left, diagrams on the right.
    Plain text extraction interleaves diagram labels into clauses (for example 2.2.13(a)
    reads "no accessory building exceeds a Diagram: Building placement for accessory
    building height of 4.6 m").
  * Diagram captions are anchored inside body paragraphs.
  * The use table (2.1) and the form-and-placement tables (3.1.2, 3.2.2) span pages, use
    parent rows ("3.1.2.5 Maximum building height for:") with (a)/(b) children, and wrap
    long cells over several lines.
  * Merged cells (1.2 overview: "306 m2" spans three rows).
  * Values carry units and compound values ("11.5 m and 3 storeys", "50% of the site area").

## 2. Extraction approaches compared

All "tested" rows were run on this PDF in this prototype.

| Approach | Tested? | Result on R1-1 | Verdict |
|---|---|---|---|
| **Tag tree via pdfplumber** (`page.structure_tree` + char `mcid`) | Yes | Clean reading order, real table cells, captions and diagram labels separable, ~1 s for 17 pages. Needed two small repairs: pdfminer drops the outer MCID after a nested Link (re-attach), and captions anchored in paragraphs (pull out by "Diagram:" + bold font). | **Chosen primary path.** |
| pdfplumber layout (`extract_text`, `find_tables`) | Yes | Regulation tables come out well (`find_tables` found all of them). Prose on two-column pages is interleaved with diagram labels; diagrams also produce 3 to 4 junk "tables". | Fallback for untagged PDFs (older schedules), with column cropping. |
| PyMuPDF (`get_text("blocks")`, `find_tables`) | Yes | Block-level output keeps diagram labels in separate blocks (better than pdfplumber lines), tables equivalent. ~5x slower than pdfplumber here; AGPL licence matters if collaborators ship closed code. | Good alternative fallback; not needed for tagged PDFs. |
| camelot (lattice/stream) | Yes (p.9) | Same 23x2 table as pdfplumber. Pulls in OpenCV/Ghostscript. Tables only, no prose. | Not worth the dependency. |
| docling / unstructured (ML layout models) | No (heavy: torch + model downloads) | Expected to handle columns and figures well and emit Markdown/JSON. Non-deterministic across model versions; slower. | Worth a benchmark later for schedules that are scanned or untagged. |
| LLM structured extraction (Claude with a JSON schema = our pydantic models) | No (needs an API key) | Best at conditional prose (3.1.1.3 tenure rules, 2.2.7 site conditions, 5.1 relaxations). Risks: silent number errors, cost per run, needs review. | Use as a **cross-checker and for clauses regex can't handle**, never as the only source. Planned `[llm]` extra. |
| City HTML bylaw pages / open data | Not yet | Vancouver publishes zoning-district polygons on its open data portal; joining them to parcels gives `district` per lot. Bylaw text itself is PDF-first. | Use open data for geography, PDFs for rules. |

Recommended pipeline: **tag tree (deterministic) → regex/rules into the schema → golden
tests per district → optional LLM diff report** that flags clauses where an LLM reading
disagrees with the parser. The reviewed JSON is committed, so users never need to parse
PDFs themselves.

## 3. Data schema (`src/vanzoning/models.py`)

`DistrictSchedule` (one per district per bylaw version)

* `district`, `name`, `intent`, `source` (filename, sha256, title, version label, pages),
  `parser_version`
* `uses: list[UseApproval]`: use slug, bylaw name, category, outright/conditional,
  cross-referenced use-specific clauses
* `regulations: list[Regulation]`: the numeric rules in long format
* `clauses: list[Clause]`: every clause verbatim with id, page, section title (for search,
  review, RAG)
* `figures`, `use_groups` (section 3.x → use group)

`Regulation` (one numeric limit)

| field | example |
|---|---|
| `group` | `multiple_dwelling` (s.3.1) / `other_uses` (s.3.2) |
| `use` | `duplex`, or `*` for the whole group |
| `metric` | `fsr`, `dwelling_units`, `site_area`, `site_frontage`, `site_depth`, `building_height`, `storeys`, `front_yard`, `side_yard`, `rear_yard`, `building_depth`, `building_width`, `building_separation`, `site_coverage`, `impermeable_area`, `family_units` |
| `bound` | `min` / `max` |
| `value`, `unit` | `11.5`, `m`; `0.5`, `fraction_of_site`; `1.0`, `ratio` |
| `min_units`, `max_units` | multiplex size band the rule applies to (3–4, 5, 6–8) |
| `tenure` | `rental` / `strata_or_mixed` / `any` |
| `condition` | `rear_building`, `courtyard`, `frontage_to_rear`, ... |
| `discretionary` | `True` for Director of Planning relaxations (5.1) |
| `clause`, `page`, `source_text` | provenance for every number |

Why long format: it is one `DataFrame` for analysis, it maps directly to MILP
coefficients (filter rows, read `value`), and new districts or metrics add rows, not
columns. `features.py` pivots it into fixed-order vectors when a model wants a matrix.

R1-1 result: 47 uses, 58 numeric rules, 158 clauses, 7 figure captions.

## 4. Covered vs not yet structured (R1-1)

Structured: FSR (incl. duplex exception and relaxations), max units by tenure, multiplex
site area/frontage bands, site depth, height and storeys, yards, building depth/width,
separations, site coverage, impermeability, 2+ bedroom unit minimums, use approvals.

Kept as text only (next candidates): tree retention (2.2.1), multiplex site conditions
(2.2.7: lot of record, lane access, flood plain; currently flags on `Site`), 5% social
housing trigger (3.1.1.3(b)(ii): 623 m², 17.1 m, west of Ontario/Carrall), accessory
building limits (2.2.13), floor area exclusions (4.1.2), third storey 50% rule
(3.2.2.10), Director of Planning variances (3.2.2.9, 3.2.2.11).

Known parser simplifications: "except that ..." tails attach one level up, which is right
for 2.2.1 and 4.1.2(c) but slightly off for 4.3.2; units per non-multiplex form
(duplex with suite = 4) are domain constants in `envelope.py`, not parsed.

## 5. Reuse from 6aniel/vancouver_r_zoning

| Old repo piece | Status here |
|---|---|
| `profiles.py` hand-coded R1-1 values | Used as an independent check: all 8 R1-1 limits and both 2+ bedroom tables match the parser (`test_matches_previous_repo_profile`). Keep the other 47 profiles as golden values when each schedule is parsed. |
| `zoning.capacity()` footprint/storey envelope | Ported as `envelope.geometric_envelope`, now driven by parsed rules instead of a dict. |
| `preprocess_properties.dimensions()` / `infer_street_axes()` | Ported as `vanzoning.parcels`. |
| `preprocess_properties.main()` tax/parcel/cadastral join and quality report | Next port, as a `vanzoning.data` pipeline producing a `sites` DataFrame for `options_frame`. |
| `zoning.linear_rows()` / `solve()` unit-mix MILP (unit types, family and affordable shares) | Next port, as a second stage after a site's option is chosen. |
| `zoning.resolve()` per-district `if` chains | Replaced by parsed rules; district quirks it encodes (RT-5 rear yard formula, R3 FSR tables) are a checklist for those schedules. |
| `ASSUMPTIONS.md`, `METHODS.md` | Carry over the assumptions table (3 m floor height, 85% efficiency, one rectangular building) into these docs. |

## 6. All residential schedules (November 2026)

32 PDFs, 48 districts (47 residential + FM-1). All are tagged; R5 page 8 has a
parent-tree entry without `/P`, which breaks pdfminer's per-page structure
parse, so `extract.tagged_pdf` falls back to the document-level tree pruned to
that page.

What changed in the parser:

* **Multi-district schedules** are split into one `DistrictSchedule` per
  district. Table columns ("Regulations | RR-2A | RR-2B") give the district of
  each value; a value cell with `ColSpan` applies to every column it spans. In
  prose, "In the RR-2B district ..." (in the clause, a parent, or a subheading
  like "R3-1 District") scopes the rule; "2.50 in the RR-3A district and 3.50 in
  the RR-3B and RR-3C districts" becomes one row per district. A section whose
  table is headed by only some districts (RM-7A courtyard townhouse) is scoped
  to those.
* **Conditions as data**: `Regulation.requires` holds the facts a row needs
  (`site_area_gte`, `site_depth_lte`, `corner_site`, `social_housing_share_gte`,
  `fsr_gt`, ...). Nested "if: (i) ... or (ii) ... and ..." lists are expanded
  into alternatives (one row per OR branch), so each row is a single MILP
  pathway. `value(..., facts=...)` returns the tightest unconditional row, or
  the most permissive conditional row whose requirements hold.
* **FSR tables** ("Maximum Floor Space Ratio by Minimum Site Area", R3 and RR-2)
  become one row per site-shape x site-area cell.
* **New metrics**: units per hectare (with FSR tiers), unit caps by frontage and
  tenure, prose site limits (R5 max frontage 60.7 m), "% of the site width/depth"
  units, "no minimum" = 0.
* **Overview table** (section 1.2) is parsed into `overview` (use -> min site
  area -> section, or "Regulated by the R1-1 district"); `regulated_by(use)`
  exposes the delegation, and the overview is used to map uses to section-3
  groups. Its min site areas are tested against the section-3 tables.
* Uses: "Low-Rise Apartment containing more than 8 dwelling units" -> slug
  `apartment` with `min_units=9`; "Duplex or Duplex with Secondary Suite" splits
  into two uses, "Seniors Supportive or Independent Living Housing" does not.

### Check against `profiles.py`

`tests/test_all_districts.py` reproduces 424 hand-coded values from the old
repo across 47 districts. The 23 differences are all listed in that test with
the clause that explains them: mostly rules the old repo applied in `resolve()`
(R3-2 rental only, duplex = 2 units) or simplified on purpose (RM-1 4.9 m front
yard, RT-10/RT-11 1.2 m rear yard), and density that the PDF makes conditional
(R5 needs below-market rental or social housing; RR-3 needs 0.35 non-dwelling
FSR; RM-8 145 units/ha only above FSR 0.90). One finding the other way: RM-9,
RM-9A and RM-9B allow FSR 1.20 to 2.00 outright on wider frontages (3.1.1.1),
which the old profiles did not encode.

### Known gaps (kept as text in `clauses`, or flagged `unparsed_condition`)

* Formula bonuses (RM-2/RM-3 "+0.009 per 1% coverage below 50%").
* Neighbour-derived front yards ("average of the 2 adjacent sites").
* Multi-building thresholds stated only in prose (RT-10/RT-11 511 m2, 15.0 m).
* Height relaxations worded "may vary ... to a height not exceeding".
* Conditions about ownership/operation (government or non-profit housing),
  double-fronting sites, abutting parks.

## 7. Roadmap

1. Done: all residential schedules (section 6).
2. Untagged-PDF fallback (pdfplumber with column cropping) behind the same `Block` API.
3. Parcel join: open-data zoning polygons + property parcels → `options_frame` for the
   whole city.
4. LLM cross-check extra: send each clause plus the parsed rows, get back disagreements.
5. Port the useful parts of the old LP repo onto `options_frame` (one binary per
   site x option).

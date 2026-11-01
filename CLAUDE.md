# ha-bom-warnings

Bureau of Meteorology warnings as Home Assistant entities and events (domain `bom_warnings`).
Private custom component, official sources only. General HA rules are in `../CLAUDE.md`.

## Source of truth

- `../ha-bom-warnings-plan.md`: read its "Settled" findings before changing the design.
- `../bom-docs/`: BoM user guides (warnings, spatial data, text forecasts).

## Architecture

- Warnings come from anonymous FTP: `LIST *.cap.xml` in `/anon/gen/fwo/`, then fetch only new or
  changed files. Location matching uses the static shapefiles in `/anon/home/adfd/spatial/`;
  the `AAC` field equals the CAP `AMOC-AreaCode`.
- `cap.py` and `areas.py` must not import Home Assistant. Blocking work (FTP, shapefile reads)
  runs in an executor.
- The unofficial `api.weather.bom.gov.au/v1/` JSON API is banned. `tests/fixtures/api/` is
  reference data only, and no code may depend on it.
- RSS is a fallback only.

## BoM gotchas

- CAP files can be empty (0 bytes) or missing. A 550 on a missing file is normal, because warning
  files exist only while the hazard is current.
- Phase is not a CAP field. It comes from `msgType` plus headlines ("Final", "Cancellation of").
  Flood "final" is unconfirmed: `IDQ20827` has no "Final" headline.
- Force `cp1252` when reading shapefiles: `IDM00014` ships a `.cpg` labelled "ansi 1252".
- Marine zones (`IDM00003`) are water areas, so a land point never falls inside one.
- One CAP file can hold several `<info>` blocks. Geocodes include non-AMOC names (e.g. `AU-WA`).

## Commands

- Tests: `.venv/bin/python -m pytest -q`
- Include the real-shapefile tests: `BOM_SPATIAL_DIR=<dir with unzipped IDM*> .venv/bin/python -m pytest -q`
- Tests use recorded fixtures only and never touch the network.

## Workflow

Write the test first. Add new fixtures by capturing real BoM output, never by hand-writing it.

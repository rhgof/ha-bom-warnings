# Interfaces, decisions and BoM source facts

Shared reference for all tickets. `docs/plan.md` has the history and reasoning. Where this file
and a ticket disagree, ask; where this file and the plan disagree, this file wins.

## Decisions (defaults, change only with the owner's agreement)

- Official sources only: anonymous FTP (CAP files and shapefiles). The unofficial JSON API is banned.
  RSS is a later fallback, not part of v1.
- Python 3.14, Home Assistant 2026.10.4 (matches the live instance).
- Polling is about every 10 minutes and is not user-configurable.
- A "current" warning is one for which `CapWarning.is_active(now)` is true.
- Severity order for ranking and colour: minor < moderate < unknown < severe < extreme. This
  replaces the earlier unknown < minor order: BoM sends CAP `unknown` for Severe Weather and Severe
  Thunderstorm, which must not rank below a minor flood. The count and most-severe sensors cover
  only warnings covering the location, not the state.
- The user's **state** is the prefix of the district area code (the `*_PW###` code) found when
  the entry is created, for example `QLD_PW011` gives `QLD`. ACT areas return `ACT`.
- A config entry's `unique_id` is the latitude and longitude rounded to 3 decimals. Its title is
  the home zone name, or `lat, lon` for manual entry. Users cannot name entries.
- Refresh failure threshold for the repair issue: 3 consecutive failed refreshes.
- Dev-only override: environment variable `BOM_WARNINGS_FTP_HOST`, `host` or `host:port`.
  Unset means `ftp.bom.gov.au:21`. It is read once at setup, never shown in the UI, and the fake
  server must serve the same directory layout as BoM (below).

## Existing code (pure Python, no Home Assistant imports)

Written before the Home Assistant layer existed. `architecture.md` describes the system as built.

- `custom_components/bom_warnings/cap.py`: `parse_cap(bytes) -> CapWarning | None`.
  `CapWarning` has `product_id`, `identifier`, `sent`, `phase`, `infos`, `area_codes`,
  `is_active(now)`. `Info` has `event`, `headline`, `severity`, `effective`, `expires`,
  `area_desc`, `area_codes`, `phase`. `Phase` and `Severity` are `StrEnum`s.
- `custom_components/bom_warnings/areas.py`: `resolve_area_codes(layers, *, lat, lon) -> set[str]`
  takes shapefile paths and reads files (blocking; call from an executor).
- Tests: `.venv/bin/python -m pytest -q`; real-shapefile tests need `BOM_SPATIAL_DIR`.

## Proposed FTP interface (ticket A1 creates it; B1, B2, C0c and later tickets use it)

One small class or protocol, so tests can fake it and only one FTP client exists:

- `list_files(pattern) -> list[FileEntry]` where `FileEntry` has `name`, `size`, `raw` (the whole
  listing line, used for change detection).
- `fetch(name) -> bytes | None` (None for a missing file or a 0-byte file).
- `modified(name) -> datetime | None` (the `MDTM` command).
- `download(remote_path, local_path)` for the shapefile zips.
- All methods are blocking; callers use an executor. Errors map to one error type.

## BoM source facts (verified 2026-11-01 and 2026-11-02)

The files beside a CAP file (`.txt`, product `.xml`, `.pdf`), what each holds, which to prefer for
which field and the codes seen are in `docs/warning-products.md`.

- Host `ftp.bom.gov.au`, anonymous login, passive mode.
- Warnings: directory `/anon/gen/fwo/`. `LIST *.cap.xml` returns only the CAP files, about 1 KB,
  one line per file with size and month/day/time (no year). `NLST` works too. `MDTM <file>` works.
  `MLSD` is not supported. Name pattern is `ID<state letter><digits>.cap.xml`.
- Warning files exist only while the hazard is current. A missing file (550) is normal; a 0-byte
  file has been seen.
- Shapefiles: directory `/anon/home/adfd/spatial/`, files `IDM000NN.zip` (each also available
  unzipped). Layers used for location matching in v1:
  `IDM00001` forecast districts (`*_PW###`), `IDM00014` metro areas (`*_ME###`),
  `IDM00017` flood warning catchments (`*_RC###`), `IDM00020` flood watch catchments (`*_FL###`),
  `IDM00007` fire weather districts (`*_FW###`). `IDM00003` marine zones (`*_MW###`) are water-only
  and out of scope for v1 (ticket D2). The shapefile `AAC` field equals the CAP `AMOC-AreaCode`.
- Layers change rarely and without notice for anonymous users. Server modification time is the
  change signal.
- Some layers ship a `.cpg` file labelled "ansi 1252"; always force `cp1252` (already done).
- CAP semantics: `msgType` Alert/Update/Cancel gives the phase; headlines starting
  "Cancellation of" or "Final" mark finished blocks; thunderstorm, severe weather, marine, surf
  and coastal end with `Cancel`; heatwave and fire end when `expires` passes. One file can hold
  several `<info>` blocks. Flood "final" detection is unconfirmed (ticket D1).
- Reference guides (public, not in this repo): warning products user guide, spatial data user guide
  and text forecasts user guide at
  `https://reg.bom.gov.au/catalogue/Bureau_of_Meteorology_<name>_user_guide.pdf`
  with `<name>` = `warning_products`, `spatial_data`, `text_forecasts`.

## Fixtures

Recorded files live under `tests/fixtures/`: `cap/` (real CAP files), `rss/` (unused in v1),
`api/` (reference only, nothing may depend on it).

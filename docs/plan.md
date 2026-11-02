# Plan: Home Assistant integration for BoM warnings

Status: planning. No repo exists yet. Read `bom-api-session-summary.md` in this directory first; it holds the API findings this plan rests on. None of them have been re-verified since that session.

## Goal

A custom Home Assistant integration (HACS-style, `custom_components/`) that exposes Bureau of Meteorology warnings as entities and events, usable in automations. This is likely the first of several integrations, so the repo setup should be reusable.

## Constraints and risks

- **Decision (2026-11-01): the unofficial `api.weather.bom.gov.au/v1/` JSON API is dropped.** Its responses say "You must not use, copy or share it" and it can change without notice. The integration uses only official sources: anonymous FTP (`fwo/` listing and `cap.xml`, plus static shapefiles in `anon/home/adfd/spatial/`) and the RSS feeds. Our JSON captures stay in `tests/fixtures/api/` as reference only; nothing depends on them.
- HA core would likely reject it, so the target is a **custom component for personal use**. Decide on public publishing only after reading BoM's copyright page.
- The "FTP data is personal or in-organisation use only" claim is an unverified forum quote.
- Official sources: RSS feeds (personal, non-commercial use permitted) and anonymous FTP at `ftp://ftp.bom.gov.au/anon/gen/`.

## Repo approach

- **One repo per integration**, built from a shared template. HACS expects one integration per repo, so a monorepo would break HACS installs.
- `~/Documents/GitHub/HA/` stays a plain workspace folder, not a repo.
- Proposed first repo: `ha-bom-warnings`, **private** to start.
- Build the BoM integration first, then extract a template repo from it (`ha-integration-template`). Don't design the template up front.
- The API client lives inside the integration repo as `api.py` with no HA imports. Extract it to a separate PyPI package only when a second integration needs it.
- If forecasts and observations are wanted later, consider one broader `bom` integration with multiple platforms rather than a second repo.

### Repo contents

- `custom_components/<domain>/`: `manifest.json`, `config_flow.py`, `coordinator.py`, `api.py`, `diagnostics.py`, `strings.json`, `translations/en.json`
- `hacs.json`
- `pyproject.toml` with ruff, mypy, pytest, `pytest-homeassistant-custom-component`
- GitHub Actions: lint and tests, `hassfest`, HACS validation, release
- `CLAUDE.md` with project conventions (written), plus `cap.py` and `areas.py` (pure Python, no HA imports). Python target is 3.14, HA core's minimum.
- A way to run a throwaway HA instance for manual testing
- Recorded JSON fixtures under `tests/fixtures/`

## Design

1. **Client (`api.py`)**
   - Uses HA's shared aiohttp session, a descriptive `User-Agent`, and a timeout.
   - Lists `ftp://ftp.bom.gov.au/anon/gen/fwo/` to discover current warnings (`*.cap.xml`), fetches each, and parses CAP 1.2 into typed models. FTP runs in an executor. Tolerate 0-byte files, missing files (550) and multiple `<info>` blocks.
   - RSS (`IDZ000xx.warnings_*.xml`) is a secondary source: cross-check, and a fallback if FTP is unavailable.
   - `phase` is derived per hazard (see settled finding 5): `msgType=Cancel`, headlines starting "Final" or "Cancellation of", or `expires` passed. Keep an unknown fallback.
   - "Active" is defined once: not cancelled/final and not past `expires`. This avoids the sort and hide bug in the Tesserae widget (`server.py:112`) by design.
2. **Config flow**
   - Location comes from the HA home location or a manually entered latitude/longitude (no place search; that was the JSON API's only unique feature).
   - Point-in-polygon against the cached shapefiles (`IDM00001`, `IDM00017`, `IDM00020`, `IDM00007`, plus the thunderstorm area layer once identified) resolves the AAC codes for that point; store them with the name and state.
   - Options: hide `final` or `cancelled`, select warning types.
3. **Coordinator**
   - One `DataUpdateCoordinator`, polling about every 10 minutes (not user-configurable, per HA guidelines). Each cycle is `LIST *.cap.xml` (about 1 KB), then fetches of only new or changed files; files no longer listed are dropped (see settled finding 8).
   - One shared FTP listing and CAP fetch across config entries; each entry filters by its stored AAC codes and state.
   - "At my location" = any current CAP area code intersects the entry's AAC codes.
4. **Entities**
   - Avoid one entity per warning, since they come and go.
   - `binary_sensor`: warning active at my location; optionally one per category (flood, fire, marine, severe weather).
   - `sensor`: count of active warnings for the state; title of the most recent or most severe warning; full list in attributes.
   - Events: fire an HA event (or use an `event` entity) when a warning ID first appears or changes phase, for automations and notifications.
5. **Reliability**
   - Raise `UpdateFailed` on errors.
   - Tolerate unknown fields and phases.
   - Raise a repair issue after repeated failures.
   - Provide a diagnostics download.
6. **Testing**
   - `pytest-homeassistant-custom-component` with recorded fixtures.
   - Include a payload containing `renewal` and `final` phases.

## Phases

- **Phase 0: setup and research (done).** Repo scaffolded (private, local, committed), fixtures captured, sources chosen (FTP CAP plus shapefiles, RSS as fallback), `cap.py` and `areas.py` built test-first (22 tests passing, 4 more with the real shapefiles via `BOM_SPATIAL_DIR`). `CLAUDE.md` files and the two HA skills are in place.
- **Phase 1: v1 (next).**
  1. FTP client: glob listing, fetch new or changed, tolerate empty or missing files; test with a fake FTP object.
  2. Shapefile manager: download, cache in HA storage, weekly modification-time check, re-resolve stored codes on change, keep the cache if a refresh fails.
  3. Config flow: HA home location or typed latitude/longitude resolved to area codes.
  4. Coordinator, entities and events, reliability (repairs, diagnostics).
  5. Home Assistant tests: install `pytest-homeassistant-custom-component`, run hassfest, then read the HA developer docs for the exact current APIs before writing HA-facing code.
- **Phase 2 (optional):** RSS fallback, full warning text from `<id>.txt`, a marine sensor (needs a design decision: marine zones are water-only).
- **Phase 3: template.** Extract `ha-integration-template` from the working repo.
- **Later:** forecasts and observations (see `../bom-docs/ (workspace, not in this repo; see URLs in docs/interfaces.md) Bureau_of_Meteorology_text_forecasts_user_guide.pdf`), same location setup. Link a private GitHub repo and replace the `OWNER` placeholders in `manifest.json`.

## Settled (2026-11-01, fresh curl captures)

1. **Types.** Seen today: `flood_warning`, `severe_thunderstorm_warning`, `heatwave_warning`, `marine_wind_warning`. The list is incomplete (fire, surf, cyclone etc. appear only when active), so keep `type` an open string with an "other" fallback. No `severity` field; use `warning_group_type` (`major`/`minor`) as the severity signal. All five phases seen.
2. **Per-location endpoint is location-scoped.** Quilpie, Blackall, Hungerford, Condamine, Isisford, Eulo, Toowoomba, Darwin and Broome return their own warnings; Cairns and Hobart return empty. Shape differs from national: prefixed `id` (`QLD_RC126_IDQ20855`, national ID is the suffix after the last `_`), extra `area_id`, more specific `title`, no `states`. Gaps: state-wide marine warnings do not reach land locations (Hobart empty despite a TAS marine warning), and matching follows BoM area definitions, not place names (Chinchilla empty despite a warning naming "Chinchilla Weir TW"). Plan: per-location endpoint for the "at my location" binary sensor, national feed for state counts.
3. **Domain: `bom_warnings`.** Narrow name avoids shadowing a core `bom` integration (from memory, not checked) and overlap with the `bureau_of_meteorology` HACS integration.
4. **RSS feeds are the baseline source (decided).** Official per-state land/marine/combined feeds listed at https://www.bom.gov.au/rss/ (e.g. `https://www.bom.gov.au/fwo/IDZ00063.warnings_land_qld.xml`), `ttl` 10 minutes. The page says RSS is "a free service ... for personal and non-commercial use only", which settles open question 4 for this source. Items carry only `title`, `link`, `pubDate`, `guid` (a page URL, stable per river basin; thunderstorm items link to `/products/IDQ21035.shtml`, which contains the real warning ID). Severity and phase are only in the title text ("Final Flood Warning for ...", "Moderate ..."), titles can contain embedded newlines, and times are local. No expiry, type, area or geohash, so RSS cannot answer "warning at my location". Plan: RSS drives the state-level sensors and new-warning events; the JSON API is an optional enhancement for the location binary sensor, phase and expiry. Both sit behind one coordinator interface; if the JSON API breaks, the RSS sensors keep working.
5. **CAP on anonymous FTP is the best official source (from `../bom-docs/ (workspace, not in this repo; see URLs in docs/interfaces.md) Bureau_of_Meteorology_warning_products_user_guide.pdf`, v2.8, 30 Jul 2026).** `ftp://ftp.bom.gov.au/anon/gen/fwo/<id>.cap.xml` (CAP 1.2, CAP-AU profile) carries what RSS lacks: `msgType` (Alert/Update/Cancel), `severity`, `expires`, `event`, `headline`, and area codes (`AMOC-AreaCode`, e.g. `QLD_RC126`, which are the same as the JSON API's `area_id`). Verified: `IDQ21013.cap.xml` (heatwave) and `IDQ20855.cap.xml` (flood, two info blocks with Moderate and Minor) both download, saved under `tests/fixtures/cap/`. Caveats: warning files exist only while the hazard is current (absent otherwise, so 550 is normal); `IDQ21033.cap.xml` returned an empty file; no availability guarantee on anonymous FTP; phase is not a field, it is encoded per hazard: thunderstorm, severe weather, marine, surf and coastal end with `msgType=Cancel`; heatwave and fire end by `expires` passing; flood ends per info block via headlines starting "Final" or "Cancellation of" (severity Unknown); one file can hold several info blocks. Severity mapping is in Table 24 of the guide. Needs an FTP client in an executor, and there is no directory-wide feed, so fetch per known product ID (from RSS links, which contain the ID for thunderstorm items).
6. **Official location matching works; JSON API not needed for it (verified 2026-11-01).** Static shapefiles are on anonymous FTP at `ftp://ftp.bom.gov.au/anon/home/adfd/spatial/` (guide: `../bom-docs/ (workspace, not in this repo; see URLs in docs/interfaces.md) Bureau_of_Meteorology_spatial_data_user_guide.pdf`): `IDM00001` forecast districts (`QLD_PW011`), `IDM00017` flood warning catchments (`QLD_RC126`), `IDM00020` flood watch catchments, `IDM00007` fire weather districts, `IDM00013` point places. Each zip is about 4 MB, `AAC` field equals CAP `AMOC-AreaCode`. Point-in-polygon on `IDM00017` reproduced the JSON API: Quilpie -> `QLD_RC126` and Toowoomba -> `QLD_RC167` match their warnings' `area_id`; Chinchilla -> `QLD_RC168`/`RC171`, which is why it had no warning; Hobart -> no catchment. Plan: resolve the user's coordinates to AAC codes once (config flow, cached), then match against CAP `AMOC-AreaCode`s. Needs a polygon library (pyshp is enough to read; ray-casting worked, shapely is optional). Open: thunderstorm CAP uses `QLD_ME###` codes (metropolitan areas), whose shapefile is not yet identified, and `IDQ21033.cap.xml` is listed but 0 bytes. The `fwo/` directory listing works (5,152 files, 17 `cap.xml` today, one per current warning), so warnings can be discovered by listing instead of RSS.
7. **Thunderstorm metro codes solved; shapefiles do change, so refresh them.** `QLD_ME###` codes come from `IDM00014` (Metropolitan and Other Forecast Areas). Verified against `IDQ21035.cap.xml` (codes ME008-ME020): Toowoomba -> `QLD_ME010` and Chinchilla -> `QLD_ME008` match; Brisbane CBD, Ipswich, Sydney and Quilpie do not. `IDM00014` ships a `.cpg` labelled "ansi 1252" that Python cannot decode, so `areas.py` forces `cp1252`. Marine warnings use `NSW_MW001`-style codes from `IDM00003` (Marine Zones); these are water zones, so a land point will not fall inside them (design question for a marine sensor: nearest or chosen zone). Layers used so far: `IDM00001` (districts), `IDM00014` (metro), `IDM00017` (flood catchments), `IDM00020` (flood watch), `IDM00007` (fire weather), `IDM00003` (marine). Update behaviour: files are static but not frozen. Server modification dates: `IDM00001` Jan 2022, `IDM00017`/`IDM00020` 2 Jul 2026, `IDM00007`/`IDM00013` 19 Aug 2026. BoM warns registered users by email and puts samples in `anon/home/adfd/spatial/pending/`; anonymous users get no notice. Design: download on first setup and cache in HA storage; check the zips' modification time about weekly and re-download only on change; re-resolve stored AAC codes when a layer changes; keep using the cached copy if a refresh fails.
8. **Wildcard FTP listing works (verified 2026-11-02).** `LIST *.cap.xml` (and `NLST`) in `/anon/gen/fwo/` returns only the CAP files: about 1 KB and 0.18 s, against about 400 KB and 0.6 s for the full 5,152-entry listing. Each line carries size and modification time (month, day, time, no year), so key change detection on the whole line. `MDTM <file>` works and gives a full timestamp; `MLSD` is not supported (501). Count varies with the weather: 17 CAP files on 2026-11-01, 14 on 2026-11-02, about 55 KB in total. Do not filter by state in the request: product codes encode only the issuing state, and warnings like `IDQ20850` span states, so list all and use the area codes inside. Wildcard support is server behaviour, so fall back to the full listing if the glob errors. Refresh cycle: glob listing, fetch new or changed, drop unlisted, cache parsed area codes.
9. **Throttling (JSON API only; now moot).** A rapid burst of about 8 calls returned empty bodies; 1 s pauses were fine. The client must back off and tolerate empty or non-JSON responses.

## Decisions (2026-11-02): zones as locations (#27) and marine warnings (#26)

Owner answers, recorded with the reason.

1. **A location can be a Home Assistant zone.** The zone is the thing users already manage (Home,
   Work, a holiday house), it has a radius, and changing it should not mean deleting and re-adding
   an entry. One entry per zone, titled with the zone name, `unique_id` is the zone entity id, so
   two zones at one place are allowed and one zone cannot be added twice. The entry mirrors the
   zone's centre and radius and re-resolves its areas when they change.
2. **Radius means distance to the area.** An area counts if the circle's centre is inside it or the
   distance from the centre to its boundary is at most the radius. A radius of 0 is the old
   point-in-polygon test, so Home and manual entries are unchanged. Chosen over "area centroid in
   circle" because a district can be huge and its centroid far away, which would miss a warning
   that applies right next to the user.
3. **Cap of 50 km, clamped with a notice.** A larger circle lists most of a state. A zone above the
   cap is clamped and a non-fixable `radius_clamped` repair issue says why and how to clear it
   (shrink the zone). Measured worst case at the cap: about 0.6 s on real shapefiles, against 0.33 s
   for a point, because reading the shapefiles dominates (see `docs/architecture.md`).
4. **Marine through the radius, not a separate mapping.** `IDM00003` (coastal waters, `MW` codes) is
   a sixth layer. A land point is never inside a water zone, but a circle can touch one, so the user
   controls how far out to look with the zone's radius. Chosen over a district-to-coast table or a
   nearest-zone distance because it needs no extra data, is explainable ("everything within X km of
   here"), and reuses the circle test. Local zones (harbours, bays, e.g. `NSW_MW009` Sydney Enclosed
   Waters) match along with Coastal ones; high seas are not added.
5. **Marine is opt-in, in the existing entities.** The option `include_marine` (default off) counts
   marine wind and hazardous surf warnings in the binary sensor, ranked list and event entity. All
   resolved codes, marine included, are stored, so toggling the option reloads the entry but never
   re-resolves. The option is offered to every entry, because a typed location can sit on the water
   (a mooring). Marine severity does not gate anything: a gale warning (Moderate) alerts like a storm
   warning (Severe).
6. **Deleting a zone does not break the entry.** It keeps working on its last areas and raises a
   `zone_removed` repair issue, which clears if a zone with the same entity id is created again.
7. **Still out of scope.** `PT` cyclone place codes and `TW` tsunami zones have no layer (#25, #14);
   cyclones keep matching through their `PW` codes.

## Decisions (2 Nov 2026): one sensor per warning type (#30, C10)

Automations need to name the hazard they care about ("close the blinds on a severe thunderstorm
warning") and a position in a ranked list cannot do that, so slot sensors were rejected.

1. **A table of rows, one binary sensor each.** `WARNING_TYPE_SENSORS` in `const.py` holds
   (CAP event, translation key); the icon comes from `EVENT_ICONS`, which is already the single
   place an event gets one. #31 and #32 add rows and names, nothing else. Only Thunderstorm ships
   in #30.
2. **Disabled by default.** A user enables the types an automation needs, which keeps the entity
   list short. Enabling reloads the entry (Home Assistant does this after a registry change), so no
   restart is needed.
3. **The event-type filter does not apply.** That option narrows the dashboard list and the count.
   Applying it here would silently quiet an automation sensor because someone tidied a card.
   Hide-final and `include_marine` do apply, as for every other entity.
4. **Same matching, one pass.** The coordinator filters the entry's covering warnings once
   (`by_event`), before the event-type filter narrows the list that `data` holds, so no matching
   logic is duplicated.
5. **Severity is an attribute only.** The highest level among warnings still in force, using the
   list's ranking (so BoM's `unknown`, sent for Severe Thunderstorm, ranks above moderate). A
   cancelled or final warning listed for reference never sets it. No "severe or above" variants.

## Open questions to verify first

4. Public or private. RSS terms allow personal non-commercial use; republishing publicly still needs BoM's copyright page read, and the JSON API remains "must not use".
5. Whether HTTP access to the FTP text files exists (unverified); otherwise use FTP.
6. Radar: list `ftp://ftp.bom.gov.au/anon/gen/radar/`, and read the FTP user guide's warnings section for XML and CAP formats. Both are out of scope for v1.

## Reference docs

`../bom-docs/ (workspace, not in this repo; see URLs in docs/interfaces.md) ` holds downloaded BoM documents. `Bureau_of_Meteorology_warning_products_user_guide.pdf` (v2.8) covers every warning type, product codes, formats (txt, xml, amoc.xml, cap.xml), CAP behaviour (Appendix A) and severity tables. `Bureau_of_Meteorology_text_forecasts_user_guide.pdf` (v2.1, 24 Apr 2026) covers product codes, `IDXnnnnn.ext` naming and issue times for FTP forecasts only. It has no XML schema and no warnings products. For forecast XML structure, fetch real files from `ftp://ftp.bom.gov.au/anon/gen/fwo/`.

## Home Assistant MCP server

The `home-assistant` MCP server is configured only for the `AuInData` project in `~/.claude.json`, so it is not available in this directory. To add it here:

```
claude mcp add --transport http --scope user home-assistant <url>
```

The URL is in `~/.claude.json` under `projects` > `/Users/richard/Documents/GitHub/AuInData` > `mcpServers` > `home-assistant`. It contains a private token, so keep it out of this file and out of any repo. Servers only load at session start, so add it before starting the new session. It lets us check entities and test against the live HA instance.

## Next session

1. Read this file, `ha-bom-warnings/CLAUDE.md` and `CLAUDE.md`.
2. Build the FTP client (Phase 1, step 1), test-first.
3. Unresolved: how flood warnings end in CAP (`IDQ20827` has no "Final" headline), the marine sensor design, and whether tropical cyclone and tsunami warnings need special handling.

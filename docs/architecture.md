# Architecture

What is built and how it fits together. Start here; `interfaces.md` has the decisions and BoM
source facts, `plan.md` has the history, `ha-apis.md` has the Home Assistant APIs in use.
Written from the code on `main` after epic #3 (PR #23); if they disagree, the code wins.

## What it does

For each location a user adds, the integration shows whether a Bureau of Meteorology warning is
current there. Data comes only from BoM's anonymous FTP: CAP warning files for what is current,
and static shapefiles for turning a latitude/longitude into BoM area codes. The unofficial JSON
API is banned.

Entities per location (all on one device, `unique_id` is `"lat,lon"` at 3 decimals):

| Entity | State | Reads |
| --- | --- | --- |
| `binary_sensor.<title>_warning` | on while a current warning covers the location | `coordinator.data` |
| `sensor.<title>_warning_count` | number of current warnings in the location's state | `state_warnings` |
| `sensor.<title>_most_severe_warning` | headline of the most severe one, or `none` | `state_warnings` |
| `event.<title>_warning_event` | fires `new`, `update`, `final`, `cancelled` | `states` |

## Data flow

```
BoM FTP  ──LIST/RETR──▶  WarningReader  ──▶  SharedFeed  ──listener──▶  BomWarningsCoordinator ──▶ entities
(/anon/gen/fwo/)         (changed files      (one per HA;                (one per config entry:
                          only, parse_cap)    polls every 10 min;         area codes, options,
                                              layer check every 6 h)     state, per-entry filter)
BoM FTP  ──zip──▶  spatial cache  ──▶  resolve_area_codes  ──▶  entry.data["area_codes"]
(/anon/home/adfd/spatial/)  (<config>/bom_warnings/spatial)       (config flow, and on layer change)
```

1. `SharedFeed` (`coordinator.py`) is the only thing that polls. One refresh runs in an executor
   inside a single FTP session: optionally check shapefile layers, then `WarningReader.refresh()`.
   Its result is `FeedSnapshot(warnings, layer_generation)`: every current warning nationwide.
2. `WarningReader` (`feed.py`) lists `*.cap.xml`, compares each whole listing line with the last
   one (BoM's listing has no year, so the whole line is the change signal), fetches only new or
   changed files, and drops files no longer listed. If the wildcard listing fails it falls back
   to `LIST *`. An empty, vanished (550) or unparseable file is skipped, and a changed file whose
   re-fetch fails keeps its previous parse.
3. Each entry's `BomWarningsCoordinator` never polls. It listens to the feed and re-derives its
   own view with `_covering` / `_in_state` / `_states`, using its area codes and options.
4. Entities read the entry coordinator.

## Modules

Pure Python, no Home Assistant imports (usable as a standalone package):

| File | Role |
| --- | --- |
| `cap.py` | `parse_cap(bytes) -> CapWarning \| None`. `Phase` and `Severity` enums. Rejects DOCTYPE/entities, treats offset-less times as UTC. |
| `areas.py` | `resolve_area_codes(layer paths, lat, lon)` point-in-polygon over shapefiles (cp1252 forced); `state_of(codes)`. |
| `ftp.py` | The one FTP client: `BomFtp`, `FileEntry`, `BomFtpError`, `BomFtpClient` protocol, `parse_host`, `client_from_env`. |
| `feed.py` | `WarningReader` (incremental refresh) and `read_current_warnings`. |
| `spatial.py` | Layer cache: `resolve_coordinate` (downloads missing layers once), `refresh_layers` (re-download only layers whose server `MDTM` changed). |

Home Assistant layer:

| File | Role |
| --- | --- |
| `__init__.py` | Entry setup/unload/remove. `PLATFORMS = [BINARY_SENSOR, EVENT, SENSOR]`. `runtime_data = BomWarningsData(coordinator)`. |
| `coordinator.py` | `SharedFeed`, `BomWarningsCoordinator`, feed lifecycle helpers, `ActiveWarning`, `WarningState`. |
| `config_flow.py` | Menu: home zone or manual lat/lon. Resolves the location, stores `latitude`, `longitude`, `state`, `area_codes`. Options flow. |
| `binary_sensor.py`, `sensor.py`, `event.py` | The entities above. |
| `diagnostics.py` | Download with coordinates, name, title and `unique_id` redacted. |
| `const.py`, `strings.json`, `translations/en.json` | Constants and text. The two JSON files must match (`tests/test_strings.py`). |

`api.py` is an empty leftover with a stale docstring and can be deleted.

## Behaviour worth knowing

- **FTP clients.** Every `BomFtp` is built by `client_from_env(os.environ)`. That is the only construction site, and it reads the dev-only
  `BOM_WARNINGS_FTP_HOST`. The feed and each entry have their own client because
  `BomFtp.session()` (one login reused across calls) is not thread-safe.
- **Shared feed lifecycle.** Created by the first entry, kept in `hass.data[FEED]`, polls only
  while an entry listens, shut down by the last entry to unload or be removed. A failed setup
  keeps the feed so its failure count survives Home Assistant's setup retries.
- **Matching is per `<info>` block, not per file.** One CAP file can mix areas and blocks; a
  file-level match could report an inactive block.
- **Current vs listed.** A warning is current if `Info.is_active(now)`: not cancelled/final and
  not past `expires`. With the option `hide_final_cancelled` off, ended warnings are only added to
  attribute lists; they never turn the binary sensor on or count (`ActiveWarning.is_current`).
- **Event entity.** Diffs `coordinator.states` (every covering product in any phase, one per
  product, represented by its most severe block) against the previous refresh. Baseline is taken
  when the entity is added, so startup and reload fire nothing. The `event_types` option filters
  events; `hide_final` deliberately does not, because final/cancelled are the events. A product that
  vanishes from the feed or expires without a cancel fires nothing. Chosen over bus events because
  HA guidance models momentary occurrences as `event` entities.
- **Severity order:** unknown < minor < moderate < severe < extreme; ties go to the most recent
  `sent`. The count and most-severe sensors cover the whole state (`state_warnings`), the binary
  sensor only the location.
- **Layer changes.** Every 6 hours the feed compares each layer's server `MDTM` with the cached
  one. If any changed it bumps `layer_generation`; each entry then re-resolves its own point once
  (advancing its seen generation only on success, so failures retry). If the point now resolves to
  nothing, the entry keeps its old codes and raises a `no_area_<entry_id>` repair issue.
- **Reliability.** Three consecutive failed feed refreshes create one shared, non-fixable repair
  issue `refresh_failing`; the next success or the last entry leaving clears it. All entities go
  unavailable together on a failed refresh.
- **Options (no restart):** hide final/cancelled warnings (default on), and filter by event type
  (default all). The options flow reloads the entry. Polling intervals are not configurable.
- **Identity.** `unique_id` and title come from the rounded coordinates (title is the home zone
  name, or `lat, lon`). Users cannot name entries; a second entry for the same place is rejected.

## Testing

`.venv/bin/python -m pytest -q` runs everything offline. Real-shapefile tests need
`BOM_SPATIAL_DIR` pointing at a directory with one folder per layer
(`IDM00001/IDM00001.shp`, ...); see `CLAUDE.md`.

- Recorded CAP files live in `tests/fixtures/cap/`. Add new ones by capturing real BoM output.
- `tests/fake_ftp.py`: in-memory `FakeFtp` for pure-Python tests. It counts fetches and can change,
  remove and fail files.
- `scripts/fake_bom/`: a real local FTP server (pyftpdlib) laid out like BoM, with scenarios
  (`baseline`, `warning_appears`, `warning_updated`, `warning_cancelled`, `warning_removed`,
  `file_empty`, `unavailable`). Used by the Home Assistant tests through `BOM_WARNINGS_FTP_HOST`,
  and by hand against the dev instance.
- Home Assistant tests run through `hass` with `pytest-homeassistant-custom-component`; the
  config flow tests patch `resolve_coordinate` rather than ship shapefiles. Time is frozen because
  the recorded warnings expire in early November 2026, so refresh them if tests start failing
  after that.
- `scripts/ha-dev.sh` runs a throwaway Home Assistant on `127.0.0.1:8124` (README "Dev instance");
  `docs/live-verification-c1.md` has the walkthrough and the recorded result.

## Known gaps

- If entry A unloads while entry B is stuck in setup retry, the feed is torn down and the failure
  count resets.
- A warning that expires between polls stays on for up to 10 minutes.
- The `no_area` repair issue is informational; there is no fix flow.
- `KNOWN_EVENT_TYPES` is hand-written, not taken from live BoM data.
- `areas.py` does not guard against null or non-polygon shapes in a shapefile.
- The `warning_updated` scenario does not reissue a new identifier, so it cannot produce an
  `update` event live.
- Not verified live: update events, the repair-issue path, a changed shapefile layer, two
  locations at once. Tests cover them.
- Open questions in tickets: how flood warnings end in CAP (#9), cyclone and tsunami handling
  (#14), marine warnings (#19), and the human-gated live checklist (#20).

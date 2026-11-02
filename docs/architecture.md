# Architecture

What is built and how it fits together. Start here; `interfaces.md` has the decisions and BoM
source facts, `plan.md` has the history, `ha-apis.md` has the Home Assistant APIs in use.
Written from the code on `main` after epic #3 (PR #23) plus the zone branch (#27); if they disagree,
the code wins.

## What it does

For each location a user adds (Home, a typed latitude/longitude, or a Home Assistant zone), the
integration shows whether a Bureau of Meteorology warning is current there. Data comes only from BoM's anonymous FTP: CAP warning files for what is current,
and static shapefiles for turning a latitude/longitude into BoM area codes. The unofficial JSON
API is banned.

Entities per location (all on one device; `unique_id` is `"lat,lon"` at 3 decimals, or the zone
entity id for a zone entry):

| Entity | State | Reads |
| --- | --- | --- |
| `binary_sensor.<title>_warning` | on while a current warning covers the location | `coordinator.data` |
| `sensor.<title>_warning_count` | number of current warnings covering the location; attribute `warnings` is the ranked list (icon and colour per item) | `coordinator.data` |
| `sensor.<title>_most_severe_warning` | headline of the top-ranked one (cut to 255 characters), or `none`; attributes are the top item's fields plus `warnings` | `coordinator.data` |
| `binary_sensor.<title>_<type>_warning` (one per row of `WARNING_TYPE_SENSORS`: thunderstorm, fire weather, extreme heat, frost, hazardous road conditions, flood, sheep grazier, exposure, tropical cyclone, severe weather, marine wind, hazardous surf) | on while a current warning of that CAP event covers the location. Disabled by default; enabling it in the entity registry reloads the entry. Attributes: `severity` (highest of the current ones, by the list's ranking, `None` when off) and `warnings` (product, event, headline, severity, phase, effective, expires). Ignores the event-type filter; honours hide-final and `include_marine`. The severe weather one adds a `note` that it is for display (the Weather event is also the Coastal Hazard Warning). | `coordinator.by_event` |
| `event.<title>_warning_event` | fires `new`, `update`, `final`, `cancelled` | `states` |
| `sensor.<title>_fire_danger_today`, `sensor.<title>_fire_danger_tomorrow` | enum: `no_rating`, `moderate`, `high`, `extreme`, `catastrophic` (unseen text: unknown). Only for entries whose stored codes include a fire district present in a fetched fire danger product. | `coordinator.fire_danger` |

## Data flow

```
BoM FTP  ──LIST/RETR──▶  WarningReader  ──▶  SharedFeed  ──listener──▶  BomWarningsCoordinator ──▶ entities
(/anon/gen/fwo/)         (changed files      (one per HA;                (one per config entry:
                          only, parse_cap)    polls every 10 min;         area codes, options,
                                              layer check weekly,
                                              in the background)     state, per-entry filter)
BoM FTP  ──LIST/RETR IDN10016.xml etc.──▶  FireDangerReader ──▶ SharedFeed (same snapshot)
(optional step after the warnings read; one exact-name listing per needed product)
BoM FTP  ──zip──▶  spatial cache  ──▶  resolve_area_codes  ──▶  entry.data["area_codes"]
(/anon/home/adfd/spatial/)  (<config>/bom_warnings/spatial)       (config flow, and on layer change)
```

1. `SharedFeed` (`coordinator.py`) is the only thing that polls. One refresh runs in an executor
   inside a single FTP session and does only `WarningReader.refresh()`. Its result is
   `FeedSnapshot(warnings, layer_generation)`: every current warning nationwide. After a
   successful refresh, if the shapefile layer check is due, it is started as a background task
   (see "Layer changes").
2. `WarningReader` (`feed.py`) lists `*.cap.xml`, compares each whole listing line with the last
   one (BoM's listing has no year, so the whole line is the change signal), fetches only new or
   changed files, and drops files no longer listed. If the server refuses the wildcard listing
   (`BomFtpRejectedError`) it falls back to `LIST *`; a timeout does not, it fails the refresh. An empty, vanished (550) or unparseable file is skipped, and a changed file whose
   re-fetch fails keeps its previous parse.
3. Each entry's `BomWarningsCoordinator` never polls. It listens to the feed and re-derives its
   own view with `_covering` / `_states`, using its area codes and options.
4. Entities read the entry coordinator.
5. Fire danger (`FireDangerReader` in `feed.py`) is a separate, optional step in the same FTP
   session, run after the warnings read. For each product some entry needs (a stored `_FW` code
   whose state prefix is in `fire_danger.PRODUCTS`) it lists the exact file name (`LIST IDN10016.xml`),
   fetches it only when the listing line changed, and parses it. It never raises: a timeout, 550,
   missing, empty or unparseable file is logged at debug and the previous parse (or none) stays. It
   cannot touch `consecutive_failures`, the repair issue or the layer check. `FeedSnapshot.fire_danger`
   carries the parsed products (default empty, so existing constructors still work). Each entry
   coordinator picks its district by exact code (`match_district`) into `coordinator.fire_danger`.

## Modules

Pure Python, no Home Assistant imports (usable as a standalone package):

| File | Role |
| --- | --- |
| `cap.py` | `parse_cap(bytes) -> CapWarning \| None`. `Phase` and `Severity` enums. Rejects DOCTYPE/entities, treats offset-less times as UTC. |
| `areas.py` | `resolve_area_codes(layer paths, lat, lon, radius_m=0)`: point-in-polygon, plus any area whose boundary is within `radius_m` (bbox prefilter, flat-plane distance); shapefiles read as cp1252. `state_of(codes)`, `is_marine(code)`. |
| `ftp.py` | The one FTP client: `BomFtp`, `FileEntry`, `BomFtpError`, `BomFtpRejectedError`, `BomFtpClient` protocol, `parse_host`, `client_from_env`. |
| `feed.py` | `WarningReader` (incremental refresh), `read_current_warnings`, and `FireDangerReader` (optional fire danger step). |
| `fire_danger.py` | `parse_fire_danger(bytes) -> FireDangerProduct \| None`, the `PRODUCTS` table (state prefix to product id), `match_district`, `fire_product_ids`, `LEVEL_KEYS`. Reuses `cap._safe_parse`. |
| `spatial.py` | Layer cache (`LAYERS` has six, including the marine `IDM00003`): `resolve_coordinate(..., radius_m)` (downloads missing layers once), `refresh_layers` (re-download only layers whose server `MDTM` changed). |

Home Assistant layer:

| File | Role |
| --- | --- |
| `__init__.py` | Entry setup/unload/remove. `PLATFORMS = [BINARY_SENSOR, EVENT, SENSOR]`. `runtime_data = BomWarningsData(coordinator)`. |
| `coordinator.py` | `SharedFeed`, `BomWarningsCoordinator`, feed lifecycle helpers, `ActiveWarning`, `WarningState`. |
| `config_flow.py` | Menu: Home Assistant home location, a zone (only if any exist), or manual lat/lon. Resolves the location, stores `latitude`, `longitude`, `state`, `area_codes`, and for a zone `zone` and `radius`. Options flow. |
| `zone.py` | `ZoneFollower`: watches the zone state, mirrors its centre and radius into the entry (radius clamped to `MAX_RADIUS_M`), raises or clears the `zone_removed` and `radius_clamped` repair issues. |
| `binary_sensor.py`, `sensor.py`, `event.py` | The entities above. |
| `diagnostics.py` | Download with coordinates, name, title, zone entity id and `unique_id` redacted (the radius stays). |
| `const.py`, `strings.json`, `translations/en.json` | Constants and text. The two JSON files must match (`tests/test_strings.py`). |

`api.py` is an empty leftover with a stale docstring and can be deleted.

## Behaviour worth knowing

- **FTP clients.** Every `BomFtp` is built by `client_from_env(os.environ)`, which reads the
  dev-only `BOM_WARNINGS_FTP_HOST`. The feed has two (warnings, and layer check) and each entry
  has one, because `BomFtp.session()` (one login reused across calls) is not thread-safe and these
  run concurrently in executors.
- **Flaky server.** BoM's control login works while the passive data transfer sometimes stalls,
  then works a second later. So `TIMEOUT` is 10 s, and `list_files`, `fetch`, `modified` and
  `download` each try up to `ATTEMPTS` (3) times, `RETRY_DELAY` (1 s) apart, on a plain
  `BomFtpError` (timeout, reset, 4xx). A permanent 5xx reply raises `BomFtpRejectedError`, which is
  never retried; 550 on a fetch or `MDTM` (missing) and 550 on `LIST *` (empty) are not errors.
  Inside `session()` a dropped connection is re-opened, so the retry and later calls still share
  one. A refresh therefore fails only after those retries. Setup blocks on the first warnings
  refresh only, never on the layer check.
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
- **Ranking.** Both sensors read only warnings covering the location (never the whole state, which
  would list, say, a western NSW sheep graziers alert for a Sydney home). `rank_warnings` in
  `sensor.py` sorts by level, most recent `sent`, undated last, then product id. Level order is
  minor < moderate < unknown < severe < extreme: CAP `unknown` is what BoM sends for Severe Weather
  and Severe Thunderstorm, so it must outrank a minor flood. The list holds current warnings, then
  (with `hide_final_cancelled` off) ended ones, marked by `phase`. Each item has `level`, an `icon`
  chosen per CAP event (`EVENT_ICONS`, default `DEFAULT_EVENT_ICON`) and a hex `color` per level
  (`LEVEL_COLORS`), all in `const.py`. The two sensors' `icon` follows the top warning, or
  `NO_WARNING_ICON`. The binary sensor is unchanged. `docs/dashboard.md` has card examples. The
  event entity still orders a product's blocks with the enum order (unknown lowest); it only picks
  one block per product, and was left alone.
- **Layer changes.** Weekly (`LAYER_CHECK_INTERVAL`), in a background task started after a
  successful warnings refresh, on the feed's second client, the feed compares each layer's server
  `MDTM` with the cached one. The next check is set when it is scheduled, so it cannot start
  twice. Its errors are logged at debug and never fail a refresh or count towards the repair
  issue. A check that reached the server records its time in `<spatial cache>/.last_layer_check`,
  so a restart within a week does not repeat it; a missing, corrupt or old record means check
  after the first refresh, and a check where every layer failed is not recorded, so it retries on
  a later poll. If any layer changed the feed bumps `layer_generation` and publishes a new
  `FeedSnapshot`; each entry then re-resolves its own point once
  (advancing its seen generation only on success, so failures retry). If the point now resolves to
  nothing, the entry keeps its old codes and raises a `no_area_<entry_id>` repair issue.
- **Reliability.** Three consecutive failed feed refreshes (each already retried inside `BomFtp`) create one shared, non-fixable repair
  issue `refresh_failing`; the next success or the last entry leaving clears it. All entities go
  unavailable together on a failed refresh.
- **Options (no restart):** hide final/cancelled warnings (default on), filter by event type
  (default all), and include coastal waters (default off). The options flow reloads the entry. A zone entry is also
  asked about coastal waters in the config flow's zone step, which stores it as an option.
  Polling intervals are not configurable.
- **Identity.** For Home and typed locations `unique_id` is the rounded coordinates and the title
  is the home location name, or `lat, lon`; a second entry for the same place is rejected. For a
  zone, `unique_id` is the zone entity id and the title is the zone's name. Users cannot name
  entries.
- **Zones.** `coordinator.attach()` starts a `ZoneFollower` for entries with a `zone` key. It
  compares the zone state with the stored centre and radius at start and on every state change of
  that entity (a person entering the zone changes the state but not the shape, so nothing happens).
  A difference updates the entry data and sets `_reresolve`, so the next derivation re-resolves the
  circle on the entry's own FTP client and updates the stored codes; a failed attempt keeps the flag
  and retries on the next poll. A circle that resolves to nothing keeps the old codes and raises
  `no_area`. A deleted zone raises `zone_removed` and leaves the entry on its last circle.
  `dependencies: ["zone"]` in the manifest makes sure zone states exist before setup.
- **Radius and cost.** `radius_m` is capped at `MAX_RADIUS_M` (50 km). Each shape is skipped if its
  bounding box, widened by the radius, cannot contain the centre. Otherwise the centre is tested
  inside the shape, then every edge is tested for distance on a flat plane scaled by cos(latitude)
  (error well under 1% at these distances), with a cheap reject for edges wholly beyond the radius
  on one side. Measured on the real layers, a 50 km circle resolves in 0.33 to 0.37 s in the
  capital cities and 0.56 s at the least favourable place tried (central Australia, huge polygons),
  against about 0.33 s for a point: reading the shapefile records dominates. It runs in an
  executor.
- **Marine.** `IDM00003` is resolved with the other layers, so a circle that touches a coastal or
  local water zone stores its `*_MW###` code with the rest. The coordinator counts those codes only
  when the `include_marine` option is on (`_counted`), so toggling it reloads without re-resolving.
  A point is never inside a water zone, so Home and typed entries get marine codes only if the
  typed point is on the water. Nothing about severity gates marine warnings. The marine per-type sensors (marine wind, hazardous
  surf) read the same counted codes, so they follow the option with no extra logic.

## Testing

`.venv/bin/python -m pytest -q` runs everything offline. Real-shapefile tests need
`BOM_SPATIAL_DIR` pointing at a directory with one folder per layer
(`IDM00001/IDM00001.shp`, ...); see `CLAUDE.md`.

- Location matching (`areas.py`, `spatial.py`, zones) is tested in two tiers:
  - Synthetic polygons written with pyshp (`tests/test_areas.py`) run everywhere. They cover
    holes, multipart shapes, a radius reaching a neighbour, and the 0 m radius equalling the point
    test.
  - Real-shapefile tests are skipped unless `BOM_SPATIAL_DIR` is set. It needs all six layers
    (`IDM00001`, `IDM00003`, `IDM00007`, `IDM00014`, `IDM00017`, `IDM00020`), each unzipped into
    its own folder. Fetch the zips read-only from `ftp://ftp.bom.gov.au/anon/home/adfd/spatial/`
    into an empty directory outside the repo. They use central Sydney: 100 m equals the point
    result, 2 km reaches `NSW_MW009`, 12 km adds `NSW_MW004`, 50 km reaches `NSW_MW003` but not
    `NSW_MW008`.
  - The speed test only guards against an accidental quadratic (bound 5 s). Matching costs about
    0.33 s for any point, because every shape is parsed before the bounding box is checked, and
    about 0.6 s in central Australia (huge polygons) at the 50 km cap. To re-measure, time
    `resolve_area_codes` on the real layers at `-25.0, 135.0` with `radius_m=50_000`.
  - The config flow tests patch `resolve_coordinate`, so they never need shapefiles. Zone edits,
    deletion and `include_marine` are tested through Home Assistant in `tests/test_zones.py`.
- Recorded CAP files live in `tests/fixtures/cap/`. Add new ones by capturing real BoM output.
- `tests/fake_ftp.py`: in-memory `FakeFtp` for pure-Python tests. It counts fetches and listings
  and can change, remove and fail files (a rejected or timed-out wildcard listing).
- `scripts/fake_bom/`: a real local FTP server (pyftpdlib) laid out like BoM, with scenarios
  (`baseline`, `warning_appears`, `warning_updated`, `warning_cancelled`, `warning_removed`,
  `file_empty`, `unavailable`, `all_types`: the baseline plus one real sample of every warning
  type with dates shifted to now). Every scenario also serves the seven recorded fire danger
  products unchanged (`layout.put_fire_danger`). Used by the Home Assistant tests through `BOM_WARNINGS_FTP_HOST`,
  and by hand against the dev instance.
- Home Assistant tests run through `hass` with `pytest-homeassistant-custom-component`; the
  config flow tests patch `resolve_coordinate` rather than ship shapefiles. Time is frozen because
  the recorded warnings expire in early November 2026, so refresh them if tests start failing
  after that.
- `scripts/ha-dev.sh` runs a throwaway Home Assistant on `127.0.0.1:8124` (README "Dev instance");
  `docs/live-verification-c1.md` has the walkthrough and the recorded result.

## Fire danger ratings

Product and states. Every state publishes the same shape of file in `/anon/gen/fwo/`, with
`fire-district` areas keyed by the `IDM00007` fire weather district code: `IDN10016` (NSW and the
ACT, as `NSW_FW008`), `IDD10731` (NT), `IDQ13016` (QLD), `IDS10070` (SA), `IDT13151` (TAS),
`IDV18555` (VIC), `IDW15100` (WA). Each has a real capture in `tests/fixtures/fire_danger/` and every
district code in them was checked against the real `IDM00007` layer. Adding a state is one line in
`fire_danger.PRODUCTS` plus a fixture. The captures are from 1 to 2 November 2026; none of this
has been run against the dev instance.

- **Today and tomorrow** come from the period dates against the local date, where "local" is the
  offset in the product's `issue-time-local` (a fixed offset, so a daylight-saving change between
  issue and read can be off by an hour around midnight). The morning issue starts today, the
  afternoon issue starts tomorrow. The coordinator remembers every period it has seen for the
  entry's district and persists them in a per-entry `Store` (`bom_warnings.fire_danger.<entry_id>`,
  saved when they change, loaded before the first refresh, deleted with the entry). A period is
  shown only on its own local date, so a remembered rating is valid until the end of that local day
  and is replaced as soon as a newer issue covers the day; periods older than yesterday are
  pruned from the store. So today's rating survives the afternoon issue and a restart. Gap: if HA
  was down for the whole morning issue and starts after the afternoon one, today is unknown. After a
  restart the entities still wait for a fetched product, as before. When no period covers a day, the state is unknown.
- **Entities** are created when the entry's codes match a fetched product, or later when one
  arrives (a listener adds them once). After that they go unavailable, never removed, if the
  district leaves the product. A failed or missing file keeps the previous data, so they stay
  available (with a stale `issued`) rather than flap.
- **Attributes**: `level` (stored text), `color`, `icon`, `fire_behaviour_index` for the day,
  `forecast` (all periods of the latest issue), `issued`, `district`, `source` (product id) and the
  BoM attribution. An unseen level is state unknown with its text in `level`.
- **Colours and icons** are defined once in `const.py` (`FIRE_DANGER_COLORS`, `FIRE_DANGER_ICONS`).
  The colours come from the `fireDanger` palette in BoM's own front-end bundle (read 2026-11-02);
  no standalone AFDRS style guide was reachable (afdrs.com.au answered 403).
- **Which products are fetched** follows the stored codes at each refresh, so a new entry in a
  state not yet fetched gets its entities after the next poll (up to 10 minutes).

## Known gaps

- Fire danger: the midnight rollover of today/tomorrow happens at the next feed update (up to 10
  minutes late); nothing persists across a restart; the timezone is a fixed offset (see above).
- Fire danger not verified in the dev instance or a browser. The two icons `mdi:fire-circle` and
  `mdi:fire-off` were checked against the frontend icon list in a separate virtualenv.

- If entry A unloads while entry B is stuck in setup retry, the feed is torn down and the failure
  count resets.
- A failed setup retry still counts towards the repair issue, but a refresh now fails only after
  `BomFtp`'s own retries, so a brief stall no longer adds to it.
- A warning that expires between polls stays on for up to 10 minutes.
- The `no_area` repair issue is informational; there is no fix flow.
- `KNOWN_EVENT_TYPES` now lists every `<event>` in the recorded CAP files (`tests/test_cap_types.py`
  fails if a fixture uses one that is missing). It is still only what the samples show.
- The tsunami sample is named `IDY68027_cap.xml` (underscore), so `LIST *.cap.xml` does not list it
  and a tsunami warning is never seen. Kept as is; the `all_types` scenario reproduces it.
- Area codes of kind TW (tsunami) and PT (cyclone place) are never matched to a location, because
  no shapefile layer produces them (#25, #14). Cyclones match only through their PW codes. MW
  (coastal water) codes now match, but only for an entry that has `include_marine` on and whose
  circle (or typed point) reaches the water; high seas zones are not in the layer used.
- A zone entry does not rename itself when the zone is renamed, and the device keeps its first name.
- The `zone_removed` and `radius_clamped` repair issues are informational; there is no fix flow.
- Severity grades inside headlines (Catastrophic, Extreme, Minor or Moderate flood) are not parsed; only the CAP `severity` ranks. Severe Weather and Severe Thunderstorm arrive as `unknown` and rank by the unknown rule, between moderate and severe.
- A headline over 255 characters is cut for the `most_severe_warning` state (HA would otherwise show `unknown`); the attributes keep it whole.
- The CAP event `Weather` is ambiguous: it is used for both severe weather and coastal hazard
  warnings, so filtering on it keeps both.
- `areas.py` does not guard against null or non-polygon shapes in a shapefile.
- The `warning_updated` scenario does not reissue a new identifier, so it cannot produce an
  `update` event live.
- Not verified live: update events, the repair-issue path, a changed shapefile layer, two
  locations at once. Tests cover them.
- Open questions in tickets: how flood warnings end in CAP (#9), cyclone and tsunami handling
  (#14), marine warnings (#19), and the human-gated live checklist (#20).

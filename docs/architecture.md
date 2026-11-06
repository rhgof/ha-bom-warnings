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
| `sensor.<title>_warning_count` | number of current warnings covering the location; attribute `warnings` is the ranked list (icon and colour per item) and `areas` the names of the areas the location covers, in code order (see "Area names") | `coordinator.data` |
| `sensor.<title>_most_severe_warning` | headline of the top-ranked one (cut to 255 characters), or `none`; attributes are the top item's fields plus `warnings` | `coordinator.data` |
| `sensor.<title>_<type>_warning` (one per row of `warning_types.WARNING_TYPES`: thunderstorm, fire weather, extreme heat, frost, hazardous road conditions, flood, sheep grazier, exposure, tropical cyclone, severe weather, marine wind, hazardous surf) | enum level sensor: the highest level among the type's current warnings (`none`, `minor`, `moderate`, `unrated`, `severe`, `extreme`; BoM's CAP `unknown` is shown as `unrated`). Created only for a type that is on in the options checklist; a type that is off has no sensor (its registry entry is removed when the entry loads). Attributes: the top warning's `headline`, `expires`, `product_id`, `event`, plus `warnings` (product, event, headline, severity, phase, effective, expires). Honours hide-final. The marine ones match only a location whose circle reaches a water zone. The severe weather and marine wind ones add a `note`. The marine wind one also has `strength` (the Wind row's `strength` rule, `warning_types.wind_strength`: the class read from the headline), as does each Wind entry in any `warnings` list. | `coordinator.by_event` |
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
BoM FTP  ──LIST/RETR IDN20400.xml etc.──▶  ProductSummaryReader ──▶ SharedFeed (fills Info.xml_summary)
(optional step after the warnings read; only for a current block with no CAP description)
BoM FTP  ──zip──▶  spatial cache  ──▶  resolve_area_codes  ──▶  entry.data["area_codes"]
(/anon/home/adfd/spatial/)  (<config>/bom_warnings/spatial)       (config flow, and on layer change)
```

1. `SharedFeed` (`shared_feed.py`) is the only thing that polls. One refresh runs in an executor
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
   own view with `covering` / `product_states` (`active_warnings.py`), using its area codes and
   options.
4. Entities read the entry coordinator.
4a. `ProductSummaryReader` (`product_xml.py`) is a separate, optional step in the same FTP session,
   run after the warnings read and before fire danger. It reads a product's XML for two reasons. A
   marine wind CAP file has no `description`, so each block takes the `warning_phenomena for
   warning_areas` text and the severity code (`GALE`, `STR`) of the XML hazard whose area codes
   overlap it (`Info.xml_summary` and `Info.xml_severity`, used by `covering` and by the strength
   rule). A flood block is marked `Phase.FINAL` when its hazard says `FIN`, because a final flood
   warning has CAP severity `Unknown` and no "Final" in its headline (`XML_PHASE_EVENTS`). For
   each product with such a current block it lists `<ID>.xml` by exact name and fetches it. It is keyed on the CAP issue's identifier, so an unchanged product costs no
   request at all, and a product with no XML is remembered the same way. An XML that fails, is
   empty or unreadable, or is older than its CAP file (the CAP landed first) leaves the summary out
   and is tried again on the next poll. It never raises, so it cannot touch `consecutive_failures`,
   the repair issue or the layer check.
5. Fire danger (`FireDangerReader` in `fire_danger.py`) is a separate, optional step in the same FTP
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
| `cap.py` | `parse_cap(bytes) -> CapWarning \| None`, and `parse_xml(bytes) -> Element \| None`, the one XML parse both CAP and fire danger use (rejects DOCTYPE/entities; None for empty, malformed or unknown-encoding input). `Phase` and `Severity` enums. Treats offset-less times as UTC. |
| `areas.py` | `resolve_areas(layer paths, lat, lon, radius_m=0)`: point-in-polygon, plus any area whose boundary is within `radius_m` (bbox prefilter, flat-plane distance), as `{AAC: name}`; the name is the layer's `DIST_NAME` field, or empty when a layer has none. `resolve_area_codes` is its codes. Shapefiles read as cp1252. `state_of(codes)`, `is_marine(code)`. |
| `ftp.py` | The one FTP client: `BomFtp`, `FileEntry`, `BomFtpError`, `BomFtpRejectedError`, `BomFtpClient` protocol, `parse_host`, `client_from_env`. |
| `feed.py` | `WarningReader` (incremental refresh) and `read_current_warnings`. |
| `fire_danger.py` | Everything about fire danger that needs no Home Assistant. `parse_fire_danger(bytes) -> FireDangerProduct \| None` (through `cap.parse_xml`), the `PRODUCTS` table (state prefix to product id), `match_district`, `fire_product_ids`, `LEVEL_KEYS`. `FireDangerReader` is the optional fetch step. `FireMemory` is the immutable record of ratings from earlier issues (`to_dict` and `from_dict`), `derive(memory, products, area_codes, now, default_tz)` returns the new memory and the entry's `FireDangerView`, and `view.period(day_offset, now)` answers "today" or "tomorrow". |
| `product_xml.py` | BoM's product XML beside a CAP file. `parse_product(data)` reads the product (identifier, sent time, phase) and each `<hazard>` (type, phase and severity codes exactly as written, its areas with code, description, kind and phase, and its `warning_phenomena`, `warning_areas` and `warning` text) into `Product`/`Hazard`/`HazardArea`, or None for anything that is not a product XML; the rest of the file, including any embedded map image, is parsed past and never kept. `ProductSummaryReader.enrich(warnings, now)` fills `Info.xml_summary` for blocks the CAP gives no description, from the hazard whose codes overlap the block; it is keyed on the CAP issue identifier, skips a file over `MAX_XML_BYTES` (400,000), and never raises. No Home Assistant import. |
| `spatial.py` | Layer cache (`LAYERS` has six, including the marine `IDM00003`): `resolve_coordinate(..., radius_m)` gives `{AAC: name}` (downloads missing layers once), `refresh_layers` (re-download only layers whose server `MDTM` changed). |
| `location.py` | The one entry point from a coordinate to a place: `resolve_location(ftp, cache_dir, lat=, lon=, radius_m=0)` returns a frozen `ResolvedLocation(area_codes, state, area_names)`; `area_names` is `{code: name}` for the areas that have a name. It opens the FTP session itself, so callers never write `with ftp.session()`. A point no area covers is an empty result (empty `state`), which callers report as `no_area`. Anything that stops it being worked out (BoM unreachable, a corrupt or incomplete layer, an `OSError`) raises the one `LocationUnavailable`; any other exception propagates. Blocking: call from an executor. |
| `layer_check.py` | When the weekly layer check is due. `LayerSchedule` is an immutable value (`due`, `started`, `unreached`, `loaded`), and `read_record` / `write_record` handle the `.last_layer_check` record that survives a restart. |
| `warning_types.py` | The one table of warning types. `WARNING_TYPES` has a `WarningType` row (event, icon, optional note and strength rule) for every CAP event BoM is known to send. A `SensorType` row adds the key, label and marine flag for the 12 types with a level sensor and a checklist toggle. Tsunami is a plain row: an icon but no sensor, so it falls under "Other warnings". The views derive from the table each time they are called (`sensor_types`, `type_of`, `label_of`, `type_keys`, `key_of`, `event_is_on`, `enabled_keys`, `keys_from_legacy_options`), so a test removes a type by patching `WARNING_TYPES` alone. A new type is a new row plus its name in `strings.json` and `translations/en.json`, which `tests/test_strings.py` checks. `wind_strength` is the one strength rule, read from the Wind headline. |
| `active_warnings.py` | What one location sees of the parsed warnings, with no Home Assistant import. `covering(...)` gives the `ActiveWarning`s that cover it (per `<info>` block, with hide-final and the type filter), and `product_states(...)` gives the per-product `WarningState`s the event entity compares. `SEVERITY_ORDER` is the one severity order. `rank_warnings`, `highest_level`, `current_then_ended`, `LEVEL_OPTIONS` and `STATE_NONE` rank and name the levels. `warning_attributes(w, ranked=...)` builds a list item, `type_attributes(...)` a type sensor's attributes, and `event_icon` the icon. A warning's strength comes from its row's `strength` rule in `warning_types.py`. Its `summary` is `summary_of(info.description)`: the first CAP description paragraph on one line, at most 300 characters, None when there is none (every list item and each type sensor's top level carry it only when set). |

Home Assistant layer:

| File | Role |
| --- | --- |
| `__init__.py` | Entry setup/unload/remove. `PLATFORMS = [BINARY_SENSOR, EVENT, SENSOR]`. `runtime_data = BomWarningsData(coordinator)`. |
| `shared_feed.py` | `SharedFeed` and `FeedSnapshot`, the `FEED` key, and the lifecycle helpers (acquire, abandon, release, release-removed, shutdown). The layer check's async wiring (executor job, background task, new snapshot) lives here; its timing rules are in `layer_check.py`. |
| `coordinator.py` | `BomWarningsCoordinator`: listens to the feed, re-resolves the entry's location through `location.resolve_location` (a `LocationUnavailable` is retried on the next poll), and derives its warnings and fire danger. |
| `fire_store.py` | `FireStore`: loads, saves and removes one entry's `FireMemory` in Home Assistant storage. The only place that knows the storage key, version and shape. |
| `config_flow.py` | Menu: Home Assistant home location, a zone (only if any exist), or manual lat/lon. Resolves the location through `location.resolve_location`, stores `latitude`, `longitude`, `state`, `area_codes`, and for a zone `zone` and `radius`. Options flow. |
| `zone.py` | `ZoneFollower`: watches the zone state, mirrors its centre and radius into the entry (radius clamped to `MAX_RADIUS_M`), raises or clears the `zone_removed` and `radius_clamped` repair issues. |
| `binary_sensor.py`, `sensor.py`, `event.py` | The entities above. |
| `diagnostics.py` | Download with coordinates, name, title, zone entity id, `unique_id` and the stored area names redacted (the radius and the area codes stay). |
| `const.py`, `strings.json`, `translations/en.json` | Constants and text. The two JSON files must match (`tests/test_strings.py`). |

## Behaviour worth knowing

- **FTP client.** Every `BomFtp` is built by `client_from_env(os.environ)`, which reads the
  dev-only `BOM_WARNINGS_FTP_HOST`. The feed builds the one runtime client (`feed.client`), and the
  warnings refresh, the layer check and every entry's location resolver share it. The config flow
  builds its own, because it can run before any feed exists. A `BomFtp` is safe to share between
  threads: `session()` (one login reused across calls) belongs to the thread that opened it, and a
  call from another thread opens its own connection.
- **Area names.** Each entry stores `area_names`, `{code: name}`, beside its `area_codes`. The names are
  the `DIST_NAME` field of the shapefile layers (BoM's spatial data guide lists it as the district,
  catchment or sub-catchment name; it is the one name field, but it has not been checked against
  every real layer, so an area without one is simply left out). They come from the layers and not the
  CAP files, because one CAP `<area>` has a single description for several district codes, so it cannot
  say which of them matched. A warning's `area` is the names of the codes it shares with the entry, in
  code order, each name once; `areas` on the count sensor is all the entry's names the same way. They
  are written whenever the entry resolves: at set-up, when a zone is edited, and after a layer change,
  and a changed name is stored even if the codes are the same. An entry without `area_names` (made
  before they existed) sets the coordinator to resolve once on its first refresh; until that succeeds
  it shows none, and it retries on each poll. Diagnostics redact them.
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
- **In force vs issued (#70).** `is_active` ignores `effective`, on purpose: a warning counts from
  the moment BoM issues it, so the binary sensor, count and levels give advance notice of, say, a
  marine wind warning sent a day early. `ActiveWarning.in_force` (set in `covering`:
  `effective` is None or not after `now`) tells those from warnings already started. It is an
  attribute on every list item and on the Most severe and type sensors' top level (the type
  sensor's is None when it has no warning). No state, count or event changes with it. It is fixed
  when the feed is read, so it can lag a start time by up to one refresh (10 minutes).
- **Sensor names and ids.** A type sensor is named after BoM's own product ("Heatwave warning",
  "Road weather alert", "Severe thunderstorm warning"), not after its CAP event, because a name such
  as "Extreme heat" reads as a level beside a state that may be `severe`. `SensorType.sensor_name`
  is the label plus " warning" unless the row sets `name`, and `strings.json` must match it. Home
  Assistant builds an entity id from the name, so the type sensor overrides `suggested_object_id`
  to return its translation key with spaces. That keeps `sensor.<title>_extreme_heat_warning` for
  the Heatwave warning on every setup, new or old; remove the override and a new setup's ids would
  differ from an old one's.
- **Event entity.** Diffs `coordinator.states` (every covering product in any phase, one per
  product, represented by its most severe block) against the previous refresh. Baseline is taken
  when the entity is added, so startup and reload fire nothing. A type that is off in the
  checklist raises no events; `hide_final` deliberately does not, because final/cancelled are the events. A product that
  vanishes from the feed or expires without a cancel fires nothing. Chosen over bus events because
  HA guidance models momentary occurrences as `event` entities.
- **Ranking.** Both sensors read only warnings covering the location (never the whole state, which
  would list, say, a western NSW sheep graziers alert for a Sydney home). `rank_warnings` in
  `active_warnings.py` sorts by level, most recent `sent`, undated last, then product id. Level order is
  minor < moderate < unknown < severe < extreme, defined once as `SEVERITY_ORDER` in
  `active_warnings.py` (CAP `unknown` is what BoM sends for Severe Weather and Severe Thunderstorm,
  so it must outrank a minor flood). The list holds current warnings, then
  (with `hide_final_cancelled` off) ended ones, marked by `phase`. Each item has `level`, an `icon`
  chosen per CAP event (the row's `icon` in `warning_types.WARNING_TYPES`, default
  `DEFAULT_EVENT_ICON`) and a hex `color` per level (`LEVEL_COLORS` in `const.py`). The two sensors' `icon` follows the top warning, or
  `NO_WARNING_ICON`. The binary sensor is unchanged. `docs/dashboard.md` has card examples. The
  event entity picks one block per product with the same order, so the block that stands for a
  product is the one the ranked list puts first.
- **Layer changes.** Weekly (`layer_check.LAYER_CHECK_INTERVAL`), in a background task started
  after a successful warnings refresh, on the feed's second client, the feed compares each layer's
  server `MDTM` with the cached one. The feed holds a `LayerSchedule`, whose next check is set when
  the check is started, so it cannot start twice. Its errors are logged at debug and never fail a refresh or count towards the repair
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
- **Options (no restart):** hide final/cancelled warnings (default on) and the warning types
  checklist (`warning_types`, a list of the keys that are on; absent means all). The keys are the
  `key` of each row of `warning_types.WARNING_TYPES` plus `other_warnings` (any event with no row). One helper,
  `warning_types.event_is_on`, answers "is this event on" for the list, count, most severe, event
  entity, any-warning sensor and the per-type sensors. The options flow reloads the entry. Config
  entry version 2: `async_migrate_entry` turns the version 1 `event_types` filter and
  `include_marine` switch into the checklist (`warning_types.keys_from_legacy_options`). Version 3
  removes the old per-type `binary_sensor` registry entries, because the type sensors changed
  domain (the level sensors reuse the same unique ids); version 1 entries pass through both steps.
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
  local water zone stores its `*_MW###` code with the rest, and every stored code always counts.
  Whether a marine warning shows is the Marine wind and Hazardous surf toggles' business, like any
  other type, so toggling them reloads without re-resolving. A point is never inside a water zone,
  so Home and typed entries only match marine warnings if the typed point is on the water. Nothing
  about severity gates marine warnings.

## Testing

`.venv/bin/python -m pytest -q` runs everything offline. Real-shapefile tests need
`BOM_SPATIAL_DIR` pointing at a directory with one folder per layer
(`IDM00001/IDM00001.shp`, ...); see `CLAUDE.md`.

- Location matching (`areas.py`, `spatial.py`, zones) is tested in two tiers:
  - Synthetic polygons written with pyshp (`tests/test_areas.py`) run everywhere. They cover
    holes, multipart shapes, a radius reaching a neighbour, and the 0 m radius equalling the point
    test.
  - Real-shapefile tests (in `tests/test_spatial.py`, `tests/test_areas.py` and, for
    `resolve_location`, `tests/test_location.py`) are skipped unless `BOM_SPATIAL_DIR` is set. It needs all six layers
    (`IDM00001`, `IDM00003`, `IDM00007`, `IDM00014`, `IDM00017`, `IDM00020`), each unzipped into
    its own folder. Fetch the zips read-only from `ftp://ftp.bom.gov.au/anon/home/adfd/spatial/`
    into an empty directory outside the repo. They use central Sydney: 100 m equals the point
    result, 2 km reaches `NSW_MW009`, 12 km adds `NSW_MW004`, 50 km reaches `NSW_MW003` but not
    `NSW_MW008`.
  - The speed test only guards against an accidental quadratic (bound 5 s). Matching costs about
    0.33 s for any point, because every shape is parsed before the bounding box is checked, and
    about 0.6 s in central Australia (huge polygons) at the 50 km cap. To re-measure, time
    `resolve_area_codes` on the real layers at `-25.0, 135.0` with `radius_m=50_000`.
  - The resolver itself (`tests/test_location.py`) runs everywhere: it drives `resolve_location`
    through `FakeFtp` with a tiny generated shapefile (`tests/shapefiles.py`), covering the result,
    the empty case, the one error, and the session being closed.
  - Every other test that needs a location uses the one `resolve` fixture in `tests/conftest.py`,
    which patches `location.resolve_location`, so they never need shapefiles. `tests/locations.py`
    builds the `ResolvedLocation` a test wants. Zone edits,
    deletion and the marine toggles are tested through Home Assistant in `tests/test_zones.py`, and the
    checklist and its migration in `tests/test_type_checklist.py`.
- Module boundaries are declared in `docs/architecture.json` and checked by
  `tests/test_architecture.py`, so they hold on every test run. The model has domains that own
  file-name patterns, four layers (`platforms`, `runtime`, `readers`, `foundation`, a module may
  import its own layer or below), and the layers that must not import Home Assistant (`readers` and
  `foundation`). The test also fails on a private name imported across modules, on `BomFtp` built
  anywhere but `client_from_env`, and on a module no domain owns. Imports under `TYPE_CHECKING`
  are exempt from the layer rule. A known violation goes in `allow` with the change that removes
  it, and the test fails when an entry stops being true. Add, move or rename a module by editing
  the model first.
- Recorded CAP files live in `tests/fixtures/cap/`. Add new ones by capturing real BoM output.
- `tests/fake_ftp.py`: in-memory `FakeFtp` for pure-Python tests. It counts fetches, listings and
  sessions, and can change, remove and fail files (a rejected or timed-out wildcard listing).
- `scripts/fake_bom/`: a real local FTP server (pyftpdlib) laid out like BoM, with scenarios
  (`baseline`, `warning_appears`, `warning_updated`, `warning_cancelled`, `warning_removed`,
  `file_empty`, `unavailable`, `all_types`: the baseline plus one real sample of every warning
  type with dates shifted to now). Every scenario also serves the seven recorded fire danger
  products unchanged (`layout.put_fire_danger`). Used by the Home Assistant tests through `BOM_WARNINGS_FTP_HOST`,
  and by hand against the dev instance.
- Home Assistant tests run through `hass` with `pytest-homeassistant-custom-component`; the
  tests patch `location.resolve_location` (the `resolve` fixture) rather than ship shapefiles. Time is frozen because
  the recorded warnings expire in early November 2026, so refresh them if tests start failing
  after that.
- `scripts/ha-dev.sh` runs a throwaway Home Assistant on `127.0.0.1:8124` (`docs/development.md`, "Dev instance");
  the fake server section there is the walkthrough.
- The first end-to-end run (2026-11-02, dev instance on 2026.10.4, real shapefile layers served by
  the fake server, location `-21.5, 142.0` in `QLD_PW003`, config flow driven over REST):

  | Step | Fake server | binary sensor | count | most severe |
  | --- | --- | --- | --- | --- |
  | 1 | `baseline` | off | 0 | none |
  | 2 | `warning_appears` (IDQ21013 Extreme Heat) | on, lists Extreme Heat | 1 | Severe heatwave warning for Queensland |
  | 3 | `baseline` again (warning removed) | off | 0 | none |
  | 4 | server stopped | unavailable (all four entities) | | |

  A `new` event fired on the event entity in step 2. Each step forced a refresh with
  `homeassistant.update_entity`, because the poll interval is 10 minutes. Step 3 removes the warning
  from the feed rather than serving a cancel message, because no recorded `Cancel` file covers this
  district.
- The single location resolver (`location.py`) was checked on 3 November 2026 without booting Home
  Assistant: the old route (open a session, `resolve_coordinate`, then `state_of`) and
  `resolve_location` were run on the same eight points, with the real `BomFtp` client against the
  fake BoM server and a copy of the dev instance's real layer cache. The points were the two
  configured entries (a home point and a 50 km zone), central Sydney with and without a 2 km radius,
  Hobart, Quilpie and a spot at sea with and without a radius. All eight gave the same area codes
  and state, and the two entries matched the codes they have stored (7 areas in NSW, 18 in QLD).
  A point at sea gave an empty result with no error. The coordinator's re-resolve and repair-issue
  wiring were not run live. They are covered through Home Assistant by `tests/test_options.py` and
  `tests/test_zones.py`, with the resolver replaced by the shared `resolve` fixture. A comparison
  that booted two copies of the dev instance was started and stopped, because it was slow and its
  first attempt failed on a port clash.
- The split of the coordinator (shared feed, layer schedule, active warnings) was checked on the dev
  instance on 3 November 2026, from a copy of its config on another port, against the fake BoM
  server serving the shapefile zips (not BoM's real server, not a browser). With the layer-check
  record removed, the first refresh ran one layer check and wrote the record. Both entries kept
  their area codes and fire districts, their sensors and events were written, and no repair issue
  appeared. A restart left the record unchanged, so no second check ran. Removing one entry and then
  the last one deleted their stored fire ratings, removed their entities and logged no error from
  this integration.
- The warning view (one severity order, ranking and attribute builders in `active_warnings.py`) was
  checked on the dev instance on 3 November 2026 against BoM's real server, by running a copy of its
  config on another port from the new code and comparing every warning entity's state and
  attributes with the instance still running the old code. 31 entities were identical, among them
  a real Severe Thunderstorm warning with BoM's `unknown` severity: the type sensor said `unrated`
  and the ranked list kept `level: unknown` with the same colour and icon. The one difference was
  the event entity, which had fired a live `new` event on the old instance while the copy, started
  later, correctly fired nothing at startup. The event entity's payload is covered by the HA tests.
- The warning-type table (`warning_types.WARNING_TYPES`, with icons, notes and the strength rule in
  its rows) was checked the same way on 3 November 2026: a copy of the dev config on another port,
  running the new code against BoM's real server, compared with the instance still running the old
  code. 31 entities were identical, among them the marine wind sensor (icon, note and `strength`
  attribute), the Severe Weather sensor (its note), a real Severe heatwave warning at Cairns and a
  real Severe Thunderstorm warning at Sydney, which the type sensor calls `unrated`. The one
  difference was again the event entity: the old instance had fired a live `update` that the copy,
  started later, restored as an earlier event. The options form's labels are covered by the HA
  tests, not compared live.

## Fire danger ratings

Product and states. Every state publishes the same shape of file in `/anon/gen/fwo/`, with
`fire-district` areas keyed by the `IDM00007` fire weather district code: `IDN10016` (NSW and the
ACT, as `NSW_FW008`), `IDD10731` (NT), `IDQ13016` (QLD), `IDS10070` (SA), `IDT13151` (TAS),
`IDV18555` (VIC), `IDW15100` (WA). Each has a real capture in `tests/fixtures/fire_danger/` and every
district code in them was checked against the real `IDM00007` layer. Adding a state is one line in
`fire_danger.PRODUCTS` plus a fixture. The captures are from 1 to 2 November 2026.

Checked on the dev instance on 3 November 2026, after the fire danger module was deepened, against
the fake BoM server serving the recorded products (the Home entry in `NSW_FW004`, Cairns in two QLD
districts):

- The today and tomorrow sensors showed the capture's levels and attributes (Greater Sydney Region:
  moderate, moderate; Cairns Peninsula: its own forecast).
- A value stored by the earlier code loaded unchanged and was not rewritten.
- After the NSW product was replaced by an issue that started a day later, restarting the instance
  left today at moderate (from storage, with no 3 November in the forecast attribute), and the
  store then held the 3rd beside the new issue's days.
- Removing an entry deleted its stored ratings.

- **Today and tomorrow** come from the period dates against the local date, where "local" is the
  offset in the product's `issue-time-local` (a fixed offset, so a daylight-saving change between
  issue and read can be off by an hour around midnight). The morning issue starts today, the
  afternoon issue starts tomorrow. `derive` keeps every period seen for the entry's district in a
  `FireMemory`, which the coordinator holds and passes back in on the next refresh. `FireStore`
  persists it per entry (`bom_warnings.fire_danger.<entry_id>`, saved when it changed, loaded before
  the first refresh, deleted with the entry). A period is
  shown only on its own local date, so a remembered rating is valid until the end of that local day
  and is replaced as soon as a newer issue covers the day; periods older than yesterday are
  pruned from the memory, and so from the store. Switching district forgets the old district's
  days. So today's rating survives the afternoon issue and a restart. Gap: if HA
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

- The ranked list's `level` attribute shows BoM's severity `unknown` as is, while the type sensors'
  state calls it `unrated` (`unknown` is Home Assistant's own no-value state). Both are kept as
  they are so dashboards do not change.
- Fire danger: the midnight rollover of today/tomorrow happens at the next feed update (up to 10
  minutes late); the timezone is a fixed offset (see above).
- Fire danger was checked on the dev instance against the fake BoM server only, not against BoM's
  real server and not in a browser. The two icons `mdi:fire-circle` and `mdi:fire-off` were checked
  against the frontend icon list in a separate virtualenv.

- If entry A unloads while entry B is stuck in setup retry, the feed is torn down and the failure
  count resets.
- A failed setup retry still counts towards the repair issue, but a refresh now fails only after
  `BomFtp`'s own retries, so a brief stall no longer adds to it.
- A warning that expires between polls stays on for up to 10 minutes.
- The `no_area` repair issue is informational; there is no fix flow.
- `warning_types.WARNING_TYPES` has a row for every `<event>` in the recorded CAP files
  (`tests/test_cap_types.py` fails if a fixture uses one that is missing). It is only what the
  samples show. Tsunami has a row with an icon but no sensor or toggle, so it falls under "Other
  warnings".
- The tsunami sample is named `IDY68027_cap.xml` (underscore), so `LIST *.cap.xml` does not list it
  and a tsunami warning is never seen. Kept as is; the `all_types` scenario reproduces it.
- Area codes of kind TW (tsunami) and PT (cyclone place) are never matched to a location, because
  no shapefile layer produces them (#25, #14). Cyclones match only through their PW codes. MW
  (coastal water) codes now match, for an entry whose circle (or typed point) reaches the water
  while the Marine wind or Hazardous surf type is on; high seas zones are not in the layer used.
- A zone entry does not rename itself when the zone is renamed, and the device keeps its first name.
- The `zone_removed` and `radius_clamped` repair issues are informational; there is no fix flow.
- Severity grades inside headlines (Catastrophic, Extreme, Minor or Moderate flood) are not parsed; only the CAP `severity` ranks. Severe Weather and Severe Thunderstorm arrive as `unknown` and rank by the unknown rule, between moderate and severe.
- A headline over 255 characters is cut for the `most_severe_warning` state (HA would otherwise show `unknown`); the attributes keep it whole.
- The CAP event `Weather` is ambiguous: it is used for both severe weather and coastal hazard
  warnings, so its toggle and sensor cover both.
- `areas.py` does not guard against null or non-polygon shapes in a shapefile.
- The `warning_updated` scenario does not reissue a new identifier, so it cannot produce an
  `update` event live.
- Not verified live: update events, the repair-issue path, a changed shapefile layer, two
  locations at once. Tests cover them.
- Open questions in tickets: how flood warnings end in CAP (#9), cyclone and tsunami handling
  (#14), marine warnings (#19), and the human-gated live checklist (#20).

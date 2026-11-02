# ha-bom-warnings

Bureau of Meteorology warnings as Home Assistant entities and events (domain `bom_warnings`).

## Locations

Add a location from Settings > Devices & services. There are three kinds:

- **Home Assistant home location**, or **typed latitude/longitude**: warnings for the areas the
  point is inside.
- **A Home Assistant zone** (Settings > Areas, labels & zones > Zones; Home, Work, a holiday
  house): warnings for every forecast district, metro area, flood catchment and fire weather
  district that the zone's circle touches. The entry follows the zone, so moving or resizing it
  needs no delete and re-add. The radius is used up to 50 km; a larger one is clamped and a repair
  notice says so. Deleting the zone leaves the entry on its last areas and raises a repair notice.

Each zone is its own entry, so Home, Work and a holiday house each get their own entities.

### Coastal waters

Marine wind and hazardous surf warnings apply to coastal water zones, which a point on land is
never inside. Turn on **Include coastal waters** in the entry's options and a zone whose circle
reaches the sea (a few kilometres out from the coast is enough for a Sydney zone; a harbour is
closer) also counts those warnings in the binary sensor, list sensor and event entity. It is off by
default. Tsunami and tropical cyclone place warnings are not matched yet.

## Dev instance

A throwaway Home Assistant (2026.10.4, the live version) that loads this integration straight
from the working tree. No Docker. It listens on `http://127.0.0.1:8124`. Its config, database and
token live in `config/`, and its virtualenv in `.ha-venv/`; both are gitignored.

```
scripts/ha-dev.sh start    # first run creates .ha-venv and installs HA (a few minutes)
scripts/ha-dev.sh stop
scripts/ha-dev.sh status   # also: logs, setup
```

`config/custom_components/bom_warnings` is a symlink to `custom_components/bom_warnings`, so
edits are live. Code changes need `stop` then `start`; a config entry can also be reloaded from
Settings > Devices & services > BoM Warnings > ... > Reload. The integration appears under
"Add integration" once HA has started.

To point the integration at a fake FTP server, start with
`BOM_WARNINGS_FTP_HOST=127.0.0.1:2121 scripts/ha-dev.sh start`.

### One-time human steps

1. `scripts/ha-dev.sh start`, then open `http://127.0.0.1:8124`.
2. Complete onboarding: create a user (any name and password), set the location, decline analytics.
3. Click your name (bottom left) > Security tab > "Long-lived access tokens" > Create token.
   Copy it immediately; it is shown once.
4. Save it, with nothing else in the file, to `config/.ha-token`
   (for example `pbpaste > config/.ha-token`). Never commit it or paste it into other files.

### Reading state through the REST API

```
.venv/bin/python -m scripts.ha_api sensor.some_entity
```

`scripts/ha_api.py` reads `config/.ha-token` and calls `/api/states/<entity_id>`.

# Development

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

## One-time human steps

1. `scripts/ha-dev.sh start`, then open `http://127.0.0.1:8124`.
2. Complete onboarding: create a user (any name and password), set the location, decline analytics.
3. Click your name (bottom left) > Security tab > "Long-lived access tokens" > Create token.
   Copy it immediately; it is shown once.
4. Save it, with nothing else in the file, to `config/.ha-token`
   (for example `pbpaste > config/.ha-token`). Never commit it or paste it into other files.

## Reading state through the REST API

```
.venv/bin/python -m scripts.ha_api sensor.some_entity
```

`scripts/ha_api.py` reads `config/.ha-token` and calls `/api/states/<entity_id>`.

# Development

## Where to start

- [architecture.md](architecture.md): what is built, the data flow, the module map and known gaps.
- [warning-products.md](warning-products.md): what the CAP, `.txt` and product XML files each hold,
  from real captures. Read it before touching anything beside the CAP file.
- [interfaces.md](interfaces.md) and [ha-apis.md](ha-apis.md): the BoM and Home Assistant
  interfaces this relies on.
- Warnings come from the Bureau's anonymous FTP server and location matching uses its static
  shapefiles. The unofficial `api.weather.bom.gov.au` JSON API is banned: nothing may depend on it.

## Setup and checks

Python 3.14 and [uv](https://docs.astral.sh/uv/). `uv sync` creates `.venv` with the test tools
(`.ha-venv` below is a separate environment for the dev instance).

```
.venv/bin/python -m pytest -q
.venv/bin/ruff check . && .venv/bin/ruff format --check .
.venv/bin/mypy --explicit-package-bases custom_components
```

CI (`.github/workflows/ci.yml`) runs ruff, mypy and pytest, plus Home Assistant's hassfest and the
HACS check. It does not run `ruff format --check`, so run that yourself.

Tests use recorded fixtures only and never touch the network. The tests that read real BoM
shapefiles are skipped unless `BOM_SPATIAL_DIR` points at a folder holding the six unzipped layers,
one folder each (see "Testing" in [architecture.md](architecture.md)):

```
BOM_SPATIAL_DIR=<dir> .venv/bin/python -m pytest -q
```

## Rules for changes

- **Write the test first.**
- **Fixtures are captured, never hand-written.** Record real BoM output (see below). The 13 files in
  `tests/fixtures/cap_samples/` are BoM's own samples, one per warning type, and are old, so tests
  pick a time inside each file's window.
- **Module boundaries are a model.** `architecture.json` declares them and
  `tests/test_architecture.py` enforces them. When you add, move or rename a module, edit the model
  first. `cap.py`, `areas.py` and everything in the `readers` and `foundation` layers must not
  import Home Assistant. A known violation goes in the model's `allow` list with the change that
  removes it.
- **Blocking work runs in an executor.** That means FTP and shapefile reads.
- Home Assistant conventions (comments say why, no user-configurable polling interval, standard
  config flow error keys, diagnostics never expose coordinates) are listed in the workspace
  `CLAUDE.md`, and come from Home Assistant core's `AGENTS.md`.
- Never commit a token or the Home Assistant MCP URL.

## Fake BoM server

A local FTP server laid out like BoM's, for trying scenarios without waiting for real warnings.

```
.venv/bin/python -m scripts.fake_bom list
.venv/bin/python -m scripts.fake_bom serve warning_appears --port 2121 --spatial-dir <dir of IDM000NN.zip>
.venv/bin/python -m scripts.fake_bom apply <name>   # switch scenario while a server runs
```

Without `--spatial-dir` the spatial directory is served empty. Every scenario resets to the baseline
first, so the end state is known. To add one, drop a module in `scripts/fake_bom/scenarios/` with
`apply(root)`, using recorded CAP fixtures. Point the dev instance at it with
`BOM_WARNINGS_FTP_HOST` (below). That variable is read once, in `ftp.client_from_env`, and must never
become a UI or config flow option.

## Capturing real products

```
.venv/bin/python -m scripts.capture_products
```

Saves every current CAP file with its XML and text siblings, unmodified, under
`tests/fixtures/products/<UTC stamp>/`. It uses BoM's real server, ignores
`BOM_WARNINGS_FTP_HOST`, pauses between fetches and stops after three failures in a row, because the
server starts timing out after about a hundred requests in a few minutes.

## Dev instance

A throwaway Home Assistant (the version pinned as `HA_VERSION` in `scripts/ha-dev.sh`, kept equal
to the live instance) that loads this integration straight
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

## Live verification and release

- [live-verification-c6.md](live-verification-c6.md) is the step-by-step checklist for trying the
  integration on a real Home Assistant. Take a full backup first. It is human-gated (ticket #20);
  delete it when #20 closes.
- The release and HACS checks are not set up yet (ticket #38), so installing through HACS has not
  been tried. The README tells users to fall back to the manual install.
- Tsunami and tropical cyclone place warnings are not matched (no zone layer; tickets #25 and #14,
  see [plan.md](plan.md)).

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

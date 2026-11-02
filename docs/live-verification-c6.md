# Live verification checklist for ticket #20 (owner runs this)

Trying BoM Warnings on the real Home Assistant OS instance. **You** do the install; agents do not.
Anything an agent does here is read-only, through the Home Assistant MCP server. Never put a token
or the MCP URL in a file, a commit or a ticket comment.

The throwaway instance already proved the warning scenario with real shapefiles
(`live-verification-c1.md`). This checklist only answers what that could not: does it install and
run on the real host, can the host reach BoM, and does it behave with your real data.

## Before you start

- [ ] The version you will install is the one on `main` (`git log -1` shows the merge of PR #23 or
      later). CI on that commit is green.
- [ ] `BOM_WARNINGS_FTP_HOST` is **not** set anywhere on the live host. It is a dev-only redirect to
      a fake server; if it is set, the integration never talks to BoM.
- [ ] Pick a quiet moment where you can restart Home Assistant and watch the first refresh.
- [ ] Decide the install route:
  - SSH or Samba add-on: works today. Use this.
  - HACS: not possible yet. The repo is private, and the HACS CI job was removed until it goes
    public.

## 1. Check the host can reach BoM (optional but quick)

From the Terminal or SSH add-on, which runs inside the Home Assistant OS network:

```
curl -sS -m 30 -l ftp://ftp.bom.gov.au/anon/gen/fwo/ | grep -c 'cap.xml'
```

- [ ] A number (usually under 50, possibly 0 on a quiet day) means the host reached the server and
      listed the directory. An error, `timed out` or `Could not resolve host` means the host cannot
      reach BoM's FTP: stop and note it (passive FTP needs outbound port 21 and high ports).
- [ ] Note the result below.

## 2. Back up

- [ ] Settings > System > Backups > Create backup (full, or at least Home Assistant Core). Wait for
      it to finish and note its name below. This is your rollback of last resort.

## 3. Copy the integration in

The folder to copy is `custom_components/bom_warnings/` from this repo, without `__pycache__`.

- [ ] Via Samba: map the `config` share, create `custom_components` if it does not exist, and copy
      the `bom_warnings` folder into it.
- [ ] Or via SSH: from this repo,
      `rsync -av --exclude __pycache__ custom_components/bom_warnings/ <ha-host>:/config/custom_components/bom_warnings/`.
- [ ] Check the files are there: `ls /config/custom_components/bom_warnings` shows `manifest.json`,
      `__init__.py`, `coordinator.py`, `config_flow.py`, `translations/` and the rest.
- [ ] Restart Home Assistant (Settings > System > Restart). The first start installs the `pyshp`
      requirement, so the host needs internet access for pip. Watch Settings > System > Logs.
- [ ] The log has no errors mentioning `bom_warnings` or `pyshp`.

## 4. Add the integration

- [ ] Settings > Devices & services > Add integration > "BoM Warnings".
- [ ] Choose the home location, or enter latitude and longitude if the home zone is outside
      Australia. The first add downloads about 29 MB of shapefile layers from BoM, so allow a
      minute. Outcomes:
  - Entry created: reached BoM, found an area. Good.
  - `cannot_connect`: the host cannot reach BoM FTP. Note it and go to Rollback.
  - `no_area`: the point is not inside any forecast district. Try a point in Australia.
- [ ] The entry title is your home zone name (or `lat, lon`), and there is no name field.

## 5. Confirm the entities

The entity ids are the entry title slug plus a suffix. Check each exists and has a sensible state:

- [ ] `binary_sensor.<title>_warning`: `on` only if a warning currently covers you, otherwise `off`.
- [ ] `sensor.<title>_warning_count`: a number (0 is fine).
- [ ] `sensor.<title>_most_severe_warning`: a headline, or `none`.
- [ ] `event.<title>_warning_event`: `unknown` until a warning changes. It must not have fired at
      startup.
- [ ] None of them is `unavailable`. If they are, check the log and Settings > Repairs.

A quiet day proves less: all `off` / `0` / `none` shows the data path works, not that a real
warning shows up. If a warning is current in your state, the count sensor should be above 0 even
when your own location is not covered.

## 6. Read-only checks through the MCP server

Ask the agent to run these; it changes nothing. Tools (names as exposed by the `home-assistant`
MCP server):

- [ ] `ha_get_state` on the four entities: states and attributes. With a warning present, the
      `warnings` attribute lists it; check `expires` is in the future.
- [ ] `ha_get_logs`: no `bom_warnings` errors or tracebacks, and no repeated warnings.
- [ ] `ha_get_integration` for `bom_warnings`: the entry is loaded, not `setup_retry` or `failed`.
- [ ] Repairs: Settings > Repairs shows nothing for BoM Warnings (no `refresh_failing`, no
      `no_area`).
- [ ] Diagnostics: Settings > Devices & services > BoM Warnings > the three dots > Download
      diagnostics. Open the file and confirm it contains **no latitude, longitude, name or title**
      before sharing it with anyone.
- [ ] After 20 to 30 minutes (two or three polls), states are still sensible and the log is quiet.

## 7. Rollback

Preferred order, which leaves nothing behind:

1. [ ] Settings > Devices & services > BoM Warnings > the three dots > Delete. This removes the
       entities, the device and any repair issue.
2. [ ] Delete `/config/custom_components/bom_warnings/`.
3. [ ] Delete the shapefile cache `/config/bom_warnings/` (about 29 MB).
4. [ ] Restart Home Assistant.
5. [ ] Check Settings > Devices & services > Entities (filter "warning") for leftovers and remove
       any orphans.

If the integration will not load at all and step 1 is impossible: do steps 2 to 4, then remove the
orphaned entities and the integration entry in step 5. As a last resort restore the backup from
step 2.

## Result (paste on ticket #20)

```
Date / HA version:
Install route:
Host reaches BoM FTP (step 1):            yes / no  (note)
Backup name:
Entry created (step 4):                   yes / cannot_connect / no_area
Entities present and not unavailable:     yes / no  (which)
A warning was current at the time:        yes / no
Read-only checks clean (log, repairs):    yes / no  (note)
Diagnostics free of coordinates / name:   yes / no
Rolled back:                              yes / no / not needed
Anything unexpected:
```

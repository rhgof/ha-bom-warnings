# Live verification checklist for ticket #20 (owner runs this)

Trying BoM Warnings on the real Home Assistant OS instance. **You** do the install; agents do not.
Anything an agent does here is read-only, through the Home Assistant MCP server. Never put a token
or the MCP URL in a file, a commit or a ticket comment.

The throwaway instance already proved the warning scenario with real shapefiles
(`architecture.md`, "Testing"). This checklist only answers what that could not: does it install and
run on the real host, can the host reach BoM, and does it behave with your real data and locations.

Written for the build on `main` at `5abe6cd` (5 Nov 2026). It covers the three kinds of location, the
options checklist, the level sensors (including `in_force`), the repair issues and the entry
migration (entry version 3).

## Before you start

- [ ] The version you will install is the one on `main` (`git log -1` shows `5abe6cd` or later). CI on
      that commit is green.
- [ ] Note the host's Home Assistant version (Settings > About). The integration has been run on
      2026.10.4 only; if yours is older, expect problems and note them. No lower version has been
      tested.
- [ ] `BOM_WARNINGS_FTP_HOST` is **not** set anywhere on the live host. It is a dev-only redirect to
      a fake server; if it is set, the integration never talks to BoM.
- [ ] Pick a quiet moment where you can restart Home Assistant and watch the first refresh.
- [ ] Decide the install route:
  - SSH or Samba add-on: works today. Use this.
  - HACS: not possible yet. The repo is private, and the HACS CI job was removed until it goes
    public (ticket #38).
- [ ] If you ever installed an earlier build on this host, say so in the results. Its entries are
      converted to version 3 on first load, and **there is no downgrade**: the backup in step 2 is
      the only way back to the old shape. A first install has nothing to migrate.

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
      it to finish and note its name below. This is your rollback of last resort, and the only
      rollback for the entry migration.

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

## 4. Add a location of each kind

Each location is its own entry. Add them one at a time through Settings > Devices & services > Add
integration > "BoM Warnings". The menu offers up to three choices (the zone choice appears only when
a zone exists).

**First add: expect a wait.** The first add downloads the six shapefile layers from BoM
(`IDM00001`, `IDM00003`, `IDM00007`, `IDM00014`, `IDM00017`, `IDM00020`), roughly 30 MB or more
compressed and about 60 MB unpacked in `/config/bom_warnings/spatial/` (measured on the throwaway
instance; the marine layer's download size was not measured separately). Allow a minute or more
and note how long it took. Later adds reuse the cache and are fast.

Outcomes of any add:

- Entry created: reached BoM and found an area. Good.
- `cannot_connect`: the host cannot reach BoM FTP. Note it and go to Rollback.
- `no_area`: the point is not inside any forecast district. Try a point in Australia.

- [ ] **Home location** ("Use my Home Assistant home location"): the entry is titled with your home
      zone name, and there is no name field. A home point is a point: it reaches only the areas it
      is inside.
- [ ] **A Home Assistant zone** ("Use a Home Assistant zone"): first create a zone in Settings >
      Areas, labels & zones > Zones with a radius (try 20 km, which covers several districts), then
      add it. The entry is titled with the zone name. Adding the same zone twice is refused.
- [ ] **Typed coordinates** ("Enter latitude and longitude"): the form starts with your home
      coordinates; the entry is titled with the rounded coordinates.
- [ ] Each entry creates its own device and entities, and none is `unavailable`.

## 5. The options checklist

Open each entry's three-dot menu > Configure. The form is titled "Warnings I care about".

- [ ] One switch per warning type (Thunderstorm, Fire weather, Extreme heat, Frost, Hazardous road
      conditions, Flood, Sheep grazier, Exposure, Tropical cyclone, Severe weather, Marine wind,
      Hazardous surf), then "Other warnings", then "Hide final and cancelled warnings". Everything is
      on for a new entry.
- [ ] What **on** means: the type counts everywhere (the warning sensor, the count, the most severe
      warning, the warning lists and the events) and has its own sensor, already enabled.
- [ ] What **off** means: the type is ignored everywhere and its sensor disappears from the entity
      list. Switch one off, save, and check that its sensor is gone and the warning count dropped
      if a warning of that type was current. Switch it on again and the sensor comes back with its
      history.
- [ ] Saving reloads the entry; no restart is needed.
- [ ] "Hide final and cancelled warnings" is about a warning's phase, not its type. It is on by
      default.
- [ ] A zone that reaches the sea: Marine wind and Hazardous surf only matter where the circle
      touches coastal or local waters. A home or typed point on land never sees them.

## 6. Confirm the entities

The entity ids are the entry title slug plus a suffix. Check each exists and has a sensible state:

- [ ] `binary_sensor.<title>_warning`: `on` (Unsafe) only if a warning currently covers you,
      otherwise `off` (Safe).
- [ ] `sensor.<title>_warning_count`: a number (0 is fine).
- [ ] `sensor.<title>_most_severe_warning`: a headline, or `none`.
- [ ] `event.<title>_warning_event`: `unknown` until a warning changes. It must not have fired at
      startup.
- [ ] One **level sensor** per type that is on, `sensor.<title>_<type>_warning` (for example
      `sensor.<title>_thunderstorm_warning`). The state is the highest level among the type's
      current warnings, one of `none`, `minor`, `moderate`, `unrated`, `severe`, `extreme`. `unrated`
      is BoM's `unknown` severity (sent for Severe Thunderstorm and Severe Weather warnings); it
      ranks between `moderate` and `severe`.
- [ ] With a warning of that type current: the sensor's attributes `headline`, `expires`,
      `product_id` and `event` are filled in, `expires` is in the future, and all four are empty
      when the state is `none`. The `warnings` attribute lists every current warning of the type.
- [ ] **Marine wind** (needs a zone that reaches the sea and a current marine wind warning): the
      sensor also has a `strength` attribute (`strong`, `gale`, `storm` or `hurricane`). It is the
      warning's class, not a measured speed. No other type has this attribute.
- [ ] **Not started yet:** if a warning has been issued but not begun (marine wind warnings are often
      sent a day ahead), its `in_force` attribute is `false` and `effective` is the start time. The
      sensors and the count still include it. When it starts, `in_force` turns `true` within about
      10 minutes. A warning already in force shows `true`.
- [ ] **Fire danger** (a location inside a fire weather district, in any state):
      `sensor.<title>_fire_danger_today` and
      `..._fire_danger_tomorrow` show a rating (no_rating, moderate, high, extreme or catastrophic)
      and the `district`. After the afternoon issue (about 16:15) "today" keeps its earlier value
      until the end of the local day. A location outside every fire weather district has no
      fire danger entities; that is expected.
- [ ] None of them is `unavailable`. If they are, check the log and Settings > Repairs.

A quiet day proves less: all `off` / `0` / `none` shows the data path works, not that a real
warning shows up. If a warning is current in your state, the count sensor should be above 0 even
when your own location is not covered.

## 7. Repair issues

Settings > Repairs. Normally it shows nothing for BoM Warnings. Check that you can recognise each
notice, and provoke the two that are safe to provoke:

- [ ] **Zone removed** (safe to provoke): create a temporary zone, add it as an entry, then delete
      the zone. A repair "Zone for <title> was deleted" appears and the entry keeps working on its
      last areas. Create a zone with the same name again and the notice clears by itself. Then
      delete the temporary entry.
- [ ] **Radius too large** (safe to provoke): make a temporary zone with a radius over 50 km and
      add it. A repair "Zone radius for <title> is too large" appears. Shrink the radius to 50 km or
      less and it clears. Then delete the temporary entry and zone.
- [ ] **Cannot reach the Bureau of Meteorology** (recognise only, do not provoke on the live host):
      appears after three failed refreshes in a row, about 30 minutes, and clears by itself on the
      first success. If you see it, run the step 1 check from the host.
- [ ] **No warning area** (recognise only): appears if a BoM boundary update leaves a saved
      location outside every area. The entry keeps its saved areas; remove and re-add it.

## 8. Read-only checks through the MCP server

Ask the agent to run these; it changes nothing. Tools (names as exposed by the `home-assistant`
MCP server):

- [ ] `ha_get_state` on the entities from step 6: states and attributes. With a warning present, the
      `warnings` attribute lists it; check `expires` is in the future.
- [ ] `ha_get_logs`: no `bom_warnings` errors or tracebacks, and no repeated warnings.
- [ ] `ha_get_integration` for `bom_warnings`: each entry is loaded, not `setup_retry` or `failed`.
      The entry's version (3) is not shown in the UI or in diagnostics, so a successful migration
      shows only as the entry loading, working sensors and no migration errors in the log.
- [ ] Repairs: nothing for BoM Warnings unless you provoked it in step 7.
- [ ] Diagnostics: Settings > Devices & services > BoM Warnings > the entry's three dots > Download
      diagnostics. Open the file and confirm it contains **no latitude, longitude, name, zone or
      title** (they are redacted) before sharing it with anyone. It does show the warning types
      that are on, the failure count and the area codes.
- [ ] After 20 to 30 minutes (two or three polls), states are still sensible and the log is quiet.

## 9. Remove an entry and check nothing is left

- [ ] Delete one of the extra entries (three dots > Delete). Its device, entities and any repair
      notice go with it.
- [ ] Settings > Devices & services > Entities, filter on the entry's title: no orphans remain.
- [ ] The other entries keep working and the shared refresh keeps running.

## 10. Rollback

Preferred order, which leaves nothing behind:

1. [ ] Settings > Devices & services > BoM Warnings > each entry's three dots > Delete. This removes
       the entities, the devices, the repair issues and the saved fire danger data.
2. [ ] Delete `/config/custom_components/bom_warnings/`.
3. [ ] Delete the shapefile cache `/config/bom_warnings/` (about 60 MB).
4. [ ] Restart Home Assistant.
5. [ ] Check Settings > Devices & services > Entities (filter "warning") for leftovers and remove
       any orphans.

If the integration will not load at all and step 1 is impossible: do steps 2 to 4, then remove the
orphaned entities and the integration entry in step 5.

**An entry that was migrated to version 3 cannot be put back by deleting files.** If you need the
state from before the install, restore the backup from step 2. That restores everything else on the
host to that moment too, so use it only as a last resort.

## Result (paste on ticket #20)

```
Date / HA version:
Install route:
Earlier build installed before (migration tested):  yes / no
Host reaches BoM FTP (step 1):            yes / no  (note)
Backup name:
First add (step 4): time taken, outcome:  cannot_connect / no_area / created
Home / zone / typed entries created:      yes / no  (which)
Options checklist (step 5): off removes the sensor, on restores it:   yes / no
Entities present and not unavailable:     yes / no  (which)
Level sensors show attributes when a warning is current:   yes / no / no warning at the time
A warning was current at the time:        yes / no
Fire danger present (fire weather district) / absent elsewhere:     yes / no / n/a
Repairs: zone removed, radius too large:  appeared and cleared / not as expected
Read-only checks clean (log, repairs):    yes / no  (note)
Diagnostics free of coordinates / name:   yes / no
Entry removed with no leftovers:          yes / no
Rolled back:                              yes / no / not needed
Anything unexpected:
```

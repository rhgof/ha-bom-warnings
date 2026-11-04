# ha-bom-warnings

Bureau of Meteorology warnings as Home Assistant entities and events (domain `bom_warnings`).

*Unofficial and for personal use. The warning data belongs to the Bureau of Meteorology: see
[Licence](#licence).*

## Install

Tested on Home Assistant 2026.10.4 only; no other version has been tried. Home Assistant needs
outbound access to the Bureau's FTP server (`ftp.bom.gov.au`, port 21).

**HACS:** add this repository in HACS as a custom repository of type Integration, download
BoM Warnings, and restart Home Assistant. The release and HACS checks are not set up yet
(ticket #38), so this route may not work.

**Manual:** copy the `custom_components/bom_warnings` folder from this repository into the
`custom_components` folder of your Home Assistant configuration directory, using whatever
file access your install offers, then restart Home Assistant.

Then go to Settings > Devices & services > Add integration > **BoM Warnings**. The first location
you add downloads the Bureau's area boundary files, so allow a minute. Take a full backup first.
The step-by-step checklist is in `docs/live-verification-c6.md`.

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
never inside. A zone whose circle reaches the sea (a few kilometres out from the coast is enough
for a Sydney zone; a harbour is closer) counts those warnings like any other, provided Marine wind
and Hazardous surf are on in the entry's warning types (they are by default). A Home or typed
point only sees them if it sits on the water. Tsunami and tropical cyclone place warnings are not
matched yet.

## Entities

Each location gets a warning binary sensor (on while any current warning covers it), a warning
count, a most severe warning sensor and an event entity that fires when a warning appears or
changes. Locations in NSW and the ACT also get today's and tomorrow's fire danger rating.

### Which areas a location covers

The warning count sensor has an `areas` attribute: the names of the forecast districts, metro
areas, flood catchments, fire weather districts and coastal waters the location covers, as BoM
names them (a forecast district such as `Illawarra`). It shows even when no warning is active, so editing a zone's
radius is visible straight away: grow it over a second district and that district's name appears;
shrink it and the name goes. Each item in a `warnings` list also has an `area`, the names of the
location's areas that warning covers, so a warning for a neighbouring district looks different from
one for yours. `area` is left out when none of those areas has a name. Names come from BoM's
shapefiles, never area codes. An entry made before this existed looks its names up once, the first
time it loads.

### Summary and attribution

Each item in a `warnings` list also has a `summary`: the first paragraph of the warning's text from
BoM, on one line and cut to 300 characters at a word boundary, with an ellipsis if it was longer.
A marine wind warning has no text in the CAP file, so its summary is read from the Bureau's product
XML beside it, for example "Strong Wind Warning for Coffs Coast, Macquarie Coast, Hunter Coast,
Sydney Coast, Illawarra Coast and Batemans Coast". `summary` is left out when BoM sends no text
and that XML cannot be read; the warning itself is unaffected. Check for it with
`{% if w.summary %}` or `w.summary | default('')` in a template. The Most severe warning sensor and
each per-warning-type sensor also show their top warning's `summary` as an attribute, so a tile can
show it with `state_content: summary`; the warning count sensor and the warning binary sensor show it
only inside the list.

Every warning entity carries the attribution "Australian Government Bureau of Meteorology" as its
`attribution` attribute, as the fire danger sensors do. Home Assistant shows it in the entity's
details; a tile does not. The text is the Bureau's, under its own terms
(<http://www.bom.gov.au/other/copyright.shtml>).

### Choosing the warnings that matter

Open the entry's **Configure** (three-dot menu). The form is a checklist, "Warnings I care about":
one list of warning types with a tick box each, plus a switch for hiding final and cancelled
warnings.

- **Ticked** (the default for every type): the type counts everywhere (the warning sensor, the count,
  the most severe warning, the warning list and the events) and has its own sensor, already
  enabled.
- **Unticked**: the type is ignored everywhere and its sensor is removed from the entity list. Tick it
  again and the sensor comes back. A dashboard row for a type that is off shows "entity not
  available" until you remove the row.
- **Other warnings** covers any type with no entry of its own, such as tsunami, and any type BoM
  adds later.
- **Hide final and cancelled warnings** is separate: it is about a warning's phase, not its type.
  A final flood warning is recognised from the phase in BoM's product XML, because its CAP file
  gives it no "Final" in the headline. If that XML cannot be read, it shows as a current warning
  until BoM removes it.

Saving reloads the entry, with no restart. Entries from before the checklist are converted when
they load: an empty type filter becomes every type on, and a filter with names becomes just those
types; Marine wind and Hazardous surf are on only if coastal waters were on.

### Per-warning-type level sensors

One sensor per warning type says how bad the current warnings of that type are at the location. Its
state is the highest level among them, or `none`. The states, lowest first:

| State | Meaning |
| --- | --- |
| `none` | No current warning of this type |
| `minor`, `moderate`, `severe`, `extreme` | The warning's CAP severity |
| `unrated` | BoM sends the severity `unknown` for Severe Thunderstorm and Severe Weather warnings. It is shown as `unrated`, because `unknown` is Home Assistant's own no-value state. It ranks between `moderate` and `severe`. |

The top warning's `headline`, `expires`, `product_id` and `event` are attributes (all empty when the
state is `none`), so a tile can show them. Its `summary` is there too when BoM sent text for it. The `warnings` attribute lists every current warning of the
type with its severity, phase and times. The sensors have no unit and keep no history statistics.

In an automation, trigger when the state changes to the levels you care about, for example to close
the blinds on a thunderstorm warning:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.home_thunderstorm_warning
    to: [unrated, severe, extreme]
```

| Sensor | BoM warning |
| --- | --- |
| Thunderstorm warning | Severe Thunderstorm Warning |
| Fire weather warning | Fire Weather Warning (Severe, Extreme, Catastrophic) |
| Extreme heat warning | Heatwave warnings |
| Frost warning | Frost Warning |
| Hazardous road conditions warning | Road Weather Alert |
| Flood warning | Riverine flood warnings |
| Sheep grazier warning | Warning to Sheep Graziers |
| Exposure warning | Exposure warnings |
| Tropical cyclone warning | Tropical Cyclone Watch and Warning |
| Severe weather warning | Severe Weather Warning (**for display**, see below) |
| Marine wind warning | Strong, Gale Force and Storm Force Wind Warnings for coastal waters (**marine only**) |
| Hazardous surf warning | Hazardous Surf Warning |

**Severe weather warning is for display, not for automations.** BoM uses one event, Weather, for both
Severe Weather Warnings and Coastal Hazard Warnings, so the sensor cannot tell which a warning is.
Its `note` attribute says so. It is still a good thing to show on a dashboard.

**Marine wind is not wind at your house.** BoM's Wind event is for coastal and local waters; damaging
winds on land arrive as the Severe weather warning. The Marine wind sensor's `note` attribute says
so. Both marine sensors rate a warning only when the location's circle reaches a coastal or local water
zone, so a land point never turns them on. Tsunami comes with #25.

**Marine wind strength.** CAP severity has only two levels for marine wind (a gale and a strong wind
are both Moderate), so the sensor state cannot tell them apart. The class comes from the code in
BoM's product XML (`STR` for strong, `GALE` for gale; no code for storm or hurricane has been seen),
and from the headline when that XML cannot be read or has a code this integration does not know.
The Marine wind sensor has a top-level `strength` attribute for its top current warning: `strong`,
`gale`, `storm` or `hurricane` (none when the state is `none` or the warning is a cancellation).
Each Wind entry in a `warnings` list carries the same `strength` field; no other event has it. A
class this code does not know is shown as BoM wrote it. BoM publishes no speed per warning. Its
warning products guide says marine wind warnings are issued for winds of 26 knots or stronger, and
the strength is the class (strong wind, gale, storm force, hurricane force), not a measured speed.

## Development

Contributor notes, including the throwaway dev instance, are in [docs/development.md](docs/development.md).

## Licence

The code and documentation in this repository are released under the [MIT licence](LICENSE).

The Bureau of Meteorology's data is not covered by that licence. The warnings, product files and
shapefiles this integration reads, and the recorded copies of them under `tests/fixtures`, remain
© Commonwealth of Australia (Bureau of Meteorology) and stay under the Bureau's own terms
(<http://www.bom.gov.au/other/copyright.shtml>). This is an unofficial integration, not endorsed by
the Bureau.

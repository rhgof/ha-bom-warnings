# Warning colours across Home Assistant surfaces (#93)

Which surfaces can follow a warning's severity, and which cannot, from the frontend source of the
dev instance (`home_assistant_frontend` 20261028.5, HA 2026.11.1). The file names below are in
`home-assistant/frontend` at tag `20261028.5`.

## What the integration sends

Every warning has one colour, in the `color` attribute of a ranked-list entry and of each per-type
sensor (`None` while no warning of the type is in force). It is `LEVEL_COLORS[CAP severity]` for every type, a Fire Weather
warning included (`color_of` in `active_warnings.py`). Only the fire danger rating sensors use BoM's
own fire legend. Every surface that can read an attribute uses it, so those agree by construction.

## The table

| Surface | Colour comes from | Follows severity? |
| --- | --- | --- |
| Ranked list card icon (`bom-warnings-card`) | the entry's `color` | Yes |
| `custom:bom-warning-tile` icon and tint | the sensor's `color` (omitted while quiet) | Yes |
| Packaged Markdown card (font colour) | the entry's `color` | Yes |
| Packaged Markdown card (emoji fallback) | its own square per level; an ungraded warning gets orange | Yes, approximately |
| Built-in tile with no wrapper | `stateColorCss`, which is undefined for `sensor` | No colour at all |
| More-info history bars and the activity graph | `computeTimelineColor` (see below) | **No**, only a theme can. The Most severe sensor's state was free text, so each headline got a new arbitrary colour; it is a level now, like the type sensors |
| Logbook entry dot | a category colour (`nodeColor`); the timeline colour only when the entry sets `graphColor` | No |
| More-info header, entity badge, entities-card row | `state-badge`: `stateColor` or `color` only; none set for a sensor | No colour |
| `binary_sensor` (warnings active) | the frontend's own `safety` colours for on/off | Not ours to set |

## Why the history bars cannot follow severity

`timeline-color.ts` asks three things in order:

1. `computeTimelineStateColor`: a state colour from `stateColorProperties`. `sensor` is not in
   `STATE_COLORED_DOMAIN` (`state_color.ts`; only `sensor` with `device_class: battery` has a rule),
   so there is none.
2. `computeTimelineEnumColor`: for a `sensor` with `device_class: enum`, the state's **position in
   the sensor's `options` list** picks `--graph-color-N` (N is position plus one), else the default
   palette `--color-N` (`colors.ts`; `--color-1` is `#4269d0`, a blue).
3. A generic colour handed out in first-seen order.

Our level sensors are `enum`, so step 2 applies. A bar's colour is therefore the palette entry for
the level's position in `options` (`none`, `minor`, `moderate`, `unrated`, `severe`, `extreme`
for most types), with no link to severity. The integration has no way to set it: the colour is read
from CSS variables in the browser, and the integration sends no CSS.

What can: a user theme that defines `--graph-color-1` to `--graph-color-6`. That is the only lever,
and it is global: every chart in the UI (line charts, other enum sensors) reads the same variables,
so the first six series of every chart would take the severity colours. It is a documented opt-in at
most, not something to ship by default. A graded type has different options (fire weather's grades),
so its positions differ from the other types.

### An optional theme, not shipped

A theme can set `--graph-color-1` to `--graph-color-6`, which would give the standard types
severity colours in their history bars. It is documented here and **not recommended or shipped**,
because it is only right for some of our sensors and changes every chart in Home Assistant.

```yaml
# themes/bom-warnings.yaml, loaded with `frontend: themes: !include_dir_merge_named themes`
bom-warnings:
  graph-color-1: "#9E9E9E"   # none
  graph-color-2: "#FDD835"   # minor
  graph-color-3: "#FB8C00"   # moderate
  graph-color-4: "#FF6F00"   # unrated
  graph-color-5: "#D32F2F"   # severe
  graph-color-6: "#7B1FA2"   # extreme
```

The colour is taken from the state's position in the sensor's `options`, so it lines up only where
the options are the six words above in that order:

| Sensor | Options (position) | With the theme |
| --- | --- | --- |
| Flood, heatwave, frost, marine wind and the other standard types | none, minor, moderate, unrated, severe, extreme | Right |
| Fire weather warning | none, minor, high, unrated, extreme, catastrophic | Right (the grades keep the order) |
| Thunderstorm, Severe weather | none, minor, moderate, severe (4), extreme (5) | One short: `severe` gets the "unrated" colour and `extreme` gets red |
| Fire danger today / tomorrow | no_rating, moderate, high, extreme, catastrophic | Wrong: it needs BoM's fire legend |
| Most severe | the six above, then `high` (7) and `catastrophic` (8) | Needs `graph-color-7` and `-8` as well |

The variables are the graph palette for every chart, so the first six series of every line chart and
every other enum sensor take these colours too, and one theme cannot give the fire danger sensors a
different mapping. Reordering a sensor's `options` to chase the palette is not an answer: it changes
the sensor's enum for no guaranteed result.

The logbook is the same palette when it is used at all. By default an enum sensor's entry uses a
category colour, so it does not follow severity either.

## Use the card's tile, not the built-in one

A plain `type: tile` on one of these sensors shows the theme's default icon colour (blue in the
default theme) at every level, because `sensor` has no state colour in the frontend. Only
`custom:bom-warning-tile` passes the sensor's `color` to the tile. This is the usual reason a
dashboard shows a blue icon on a moderate fire danger rating that the data says is green.

## Differences that are by design

- **Two scales share words.** The fire danger rating sensors use BoM's fire danger legend:
  `moderate` is green `#64BF30`, `high` yellow `#FEDD3A`, `extreme` orange `#F78100`, `catastrophic`
  dark red `#AD0909`. Every warning, the Fire Weather warning included, uses the severity colours,
  where `moderate` is orange `#FB8C00`, `severe` red `#D32F2F` and `extreme` purple `#7B1FA2`. A
  Fire Weather grade is one step off its CAP severity, so a "High" fire warning is orange, an
  "Extreme" one red and a "Catastrophic" one purple: the same colour as any warning of equal
  urgency, which is what the Most severe tile ranks by. The fire danger tiles are titled "Extreme
  Fire Danger Today" and the like so the scale is named, and a Fire Weather warning is titled
  "Extreme Fire weather warning".
- **Thunderstorm and Severe weather** say `severe` but keep the orange of CAP `unknown`; a warning
  BoM marks `severe` is red (`31025b0`).
- **Fire weather** grades (High, Extreme, Catastrophic) take the colour of the CAP severity they are
  one step off, so they differ from the fire danger rating cards, which keep BoM's own legend. This
  was the other way until 16 Nov 2026, when the warning moved onto the severity colours so colour
  follows urgency across every warning tile.

## Verdict

Every surface the integration or the card controls already follows one colour source, so there is
nothing left to unify there. The surfaces it does not control (history bars, logbook, built-in tile,
badges) cannot follow severity from the integration; they are Home Assistant's own palette, and only
a user theme can change the history bars, globally. What remains is a decision on the thunderstorm
colour and whether to document the optional theme.

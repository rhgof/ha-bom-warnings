# Warning colours across Home Assistant surfaces (#93)

Which surfaces can follow a warning's severity, and which cannot, from the frontend source of the
dev instance (`home_assistant_frontend` 20261028.5, HA 2026.11.1). The file names below are in
`home-assistant/frontend` at tag `20261028.5`.

## What the integration sends

Every warning has one colour, in the `color` attribute of a ranked-list entry and of each per-type
sensor (`None` while no warning of the type is in force). It is `LEVEL_COLORS[CAP severity]`, or the
fire danger rating's colour for a Fire Weather grade (`color_of` in `active_warnings.py`). Every
surface that can read an attribute uses it, so those agree by construction.

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

The logbook is the same palette when it is used at all. By default an enum sensor's entry uses a
category colour, so it does not follow severity either.

## Differences that are by design

- **Thunderstorm and Severe weather** say `severe` but keep the orange of CAP `unknown`; a warning
  BoM marks `severe` is red (`31025b0`).
- **Fire weather** uses the fire danger rating's colours for its grades, which differ from the
  severity colours (BoM's own legend).

## Verdict

Every surface the integration or the card controls already follows one colour source, so there is
nothing left to unify there. The surfaces it does not control (history bars, logbook, built-in tile,
badges) cannot follow severity from the integration; they are Home Assistant's own palette, and only
a user theme can change the history bars, globally. What remains is a decision on the thunderstorm
colour and whether to document the optional theme.

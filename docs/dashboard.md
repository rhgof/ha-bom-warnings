# Dashboard: the ranked warning list

**Checked in a browser.** These snippets were rendered in Chrome against Home Assistant 2026.10.4,
in a light and a dark theme, with live warnings at moderate and severe level (screenshots at the
end of this page). What that showed:

- The Markdown card strips inline `style`. A `style="color: ..."` on `<ha-icon>` or `<span>` is
  removed, so the icon and square come out in the theme's text colour. These snippets do not use it.
- `<ha-icon>` renders inside a Markdown card.
- A `color` attribute on a `<font>` element is kept, and colours the icon and square in exactly
  the hex the integration reports. `<font>` is obsolete HTML, so if a later release strips it, use
  the emoji variant, which is plain text.
- Not seen in a browser: the `final` and `cancelled` suffix, because no such warning was active.
  A test renders that branch's text (`tests/test_dashboard_section.py`).

Replace `<title>` with your entry's slug. For an entry titled `Home` the entity is
`sensor.home_warning_count`.

## The card

[ha-bom-warnings-card](https://github.com/rhgof/ha-bom-warnings-card) is a Lovelace card for this
integration, and the richer of the two options on this page. It lists the warnings from the count
sensor, most severe first, with an icon in the colour of its severity, the event, level, headline,
area names and summary. Ended warnings are dimmed. There is no template to write, and no
`<font>` workaround: the card draws its own icons, so the sanitiser plays no part.

To use it:

1. In HACS, add `https://github.com/rhgof/ha-bom-warnings-card` as a custom repository with the
   category **Dashboard**, download it, and hard-refresh the browser.
2. Edit a dashboard, choose **Add card**, open the **By card** tab and pick **BoM Warnings**. The
   editor starts with one of your warning count sensors chosen. You can set a title, and turn each
   warning's summary off. Or in YAML:

   ```yaml
   type: custom:bom-warnings-card
   entity: sensor.<title>_warning_count
   ```

The card needs HACS. If you would rather not install anything, use the section below, which is
built from Home Assistant's own cards. The card and the section read the same attributes, and a
test here checks the shared fixture (`tests/fixtures/dashboard/states.json`) against what the
integration really produces, so a change to the attributes cannot slip past either one.

Checked on Home Assistant 2026.10.4 in Chrome: the card installs through HACS and renders live
warnings in a light and a dark theme, and a card added from the picker and editor saved as the
short YAML above plus the chosen title. Not covered: the card on a phone or in the mobile app.

## Ready-made section

[`dashboards/warnings-section.yaml`](dashboards/warnings-section.yaml) is one dashboard section
with the ranked list below, a tile for each warning type (shown only while that type has a
warning), and the fire danger card.

To use it, open the dashboard's raw configuration editor and paste the file under `sections:` in
a view of type `sections`, then replace every `<title>` with your entry's slug (`home` for an entry
titled `Home`). Delete the fire danger card if your location is not in a fire weather district,
because its entities do not exist, so the card has nothing to show. Tiles for warning types you
switched off in the entry's options can stay (see below) or go.

Checked on Home Assistant 2026.10.4 in Chrome: with two warnings active, only the two active types
get a tile; with none, the list says so. A tile for an entity that does not exist is hidden, not
shown as an error, so leaving the unused ones in is harmless. Tiles show in the theme's colour, not
the warning's.

A test renders the section's Markdown cards against recorded attribute payloads
(`tests/fixtures/dashboard/states.json`) and checks that every entity it names exists.

I left out a `flex-table-card` or `custom:button-card` variant: I do not know their config for
looping over a list attribute well enough to give you something correct.

## Using several warnings at a location

A location can have a thunderstorm warning, a flood warning and a marine wind warning at once.
Four ways to use them, each with Home Assistant's own triggers and conditions, not templates over
the `warnings` attribute. `home` stands for your entry's slug.

| Use | What to read |
| --- | --- |
| Tiles and a list | A tile on each per-type sensor, and the ranked list for everything current |
| Notifications | The event entity, `event.home_warning_event` |
| Automations | A state trigger on a per-type sensor |
| Voice | A per-type sensor exposed to Assist |

Two types need care. **Marine wind** is for coastal waters only, and a land location never
turns it on; damaging wind on land is the **Severe weather** warning. **Severe weather** is a
display type: BoM uses one event for severe weather and coastal hazard warnings, so the sensor
cannot tell them apart. Show it, but do not trigger an automation from it.

### Tiles and a list

A tile on a per-type sensor, shown only while that type has a warning, with the ranked list below
it for everything current (Severe weather included). Repeat the tile for each type you care about:

```yaml
type: vertical-stack
cards:
  - type: tile
    entity: sensor.home_thunderstorm_warning
    state_content: [state, headline]
    visibility:
      - condition: state
        entity: sensor.home_thunderstorm_warning
        state_not: "none"
  - type: tile
    entity: sensor.home_flood_warning
    state_content: [state, headline]
    visibility:
      - condition: state
        entity: sensor.home_flood_warning
        state_not: "none"
  - type: custom:bom-warnings-card
    entity: sensor.home_warning_count
```

The built-in tile does not take the warning's colour. The card's `custom:bom-warning-tile` does, and
can replace each tile above. Without the card, use the ready-made section or the Markdown card
earlier on this page for the list. `dashboards/warnings-section.yaml` already has a tile for every
type, each hidden while that type is quiet.

### Notifications

The event entity fires when a warning appears (`new`), changes (`update`) or ends (`final`,
`cancelled`). Its event data has `product_id`, `event`, `severity` and `headline`. Warnings already
present when Home Assistant starts or the entry reloads fire nothing.

```yaml
triggers:
  - trigger: state
    entity_id: event.home_warning_event
conditions:
  - condition: state
    entity_id: event.home_warning_event
    attribute: event_type
    state: [new, update]
actions:
  - action: notify.notify
    data:
      title: "BoM warning: {{ state_attr('event.home_warning_event', 'event') }}"
      message: "{{ state_attr('event.home_warning_event', 'headline') }}"
```

Drop the condition to be told about ended warnings too.

### Automations

A per-type sensor's state is the highest level among its current warnings: `none`, `minor`,
`moderate`, `unrated`, `severe` or `extreme`. Trigger on it going to the levels you care about, and
`to: [severe, extreme]` is "only if severe". This closes the blinds for a thunderstorm warning at
severe or above, or when BoM leaves it unrated, which it does for Severe Thunderstorm warnings:

```yaml
triggers:
  - trigger: state
    entity_id: sensor.home_thunderstorm_warning
    to: [unrated, severe, extreme]
actions:
  - action: cover.close_cover
    target:
      area_id: living_room
```

A warning counts from the moment BoM issues it, even if it starts later. To act only once it has
started, add a condition on the sensor's `in_force` attribute:

```yaml
conditions:
  - condition: state
    entity_id: sensor.home_thunderstorm_warning
    attribute: in_force
    state: true
```

### Voice

Expose a per-type sensor to Assist (Settings > Voice assistants > Expose) and ask for it by name,
for example "what is the thunderstorm warning at home?". Its state is the level, so the answer is
`none`, `severe` and so on. This has not been tried on a voice assistant here. A sentence that reads
out the headline is the optional spoken summary sensor, which is not built (see #35).

## What the data looks like

`state_attr('sensor.<title>_warning_count', 'warnings')` is a list, most severe first, only for
warnings covering your location. Each item has `product_id`, `event`, `severity`, `level`
(`minor`, `moderate`, `unknown`, `severe`, `extreme`; a Fire Weather Warning shows `high`,
`extreme` or `catastrophic`), `icon` (an `mdi:` name), `color` (hex),
`headline`, `phase`, `sent`, `effective` and `expires`, and `area` (the names of your location's
areas the warning covers, such as `Illawarra`; left out when none has a name) and `summary` (the
first paragraph of BoM's text, at most 300 characters; for marine wind, which has no text in its CAP
file, a line from the product XML such as "Strong Wind Warning for Sydney Coast, ..."; left out when
neither can be read). `sensor.<title>_most_severe_warning` and each per-type sensor repeat their top warning's
`summary` as a top-level attribute, so a tile can show it (`state_content: [state, summary]`); the
count sensor does not. Every warning entity carries the attribution "Australian Government Bureau of
Meteorology" in its `attribution` attribute; a tile does not show it. With the option to
keep final and cancelled warnings, ended ones come after the current ones with `phase` set to
`final` or `cancelled`.

`state_attr('sensor.<title>_warning_count', 'areas')` is the list of area names the location
covers, in code order. It is there with no warning active, so it shows what a zone's radius reaches.

Each per-type sensor (thunderstorm, flood, marine wind and so on) has a top-level `level` and
`color`, so a card can colour itself from the sensor alone. `level` is the sensor's state (`none`,
`minor`, `moderate`, `unrated`, `severe` or `extreme`; the fire weather sensor shows the Bureau's fire
grade instead, `high`, `extreme` or `catastrophic`), and `color` is that level's hex colour, the
same as in the count sensor's list. `color` is `None` while no warning of the type is in force
(ended warnings do not count), and the card decides how a quiet state looks.

## Markdown card, coloured icon

```yaml
type: markdown
title: Warnings
content: >-
  {% set items = state_attr('sensor.<title>_warning_count', 'warnings') or [] %}
  {% if items | count == 0 %}
  No warnings for this location.
  {% endif %}
  {% for w in items %}
  <font color="{{ w.color }}"><ha-icon icon="{{ w.icon }}"></ha-icon> &#9632;</font>
  **{{ w.event }}** ({{ w.level }}{% if w.phase in ['final', 'cancelled'] %}, {{ w.phase }}{% endif %}):
  {{ w.headline }}

  {% endfor %}
```

## Markdown card, emoji squares (fallback)

Uses coloured emoji squares for the level instead of a colour attribute, so it needs no markup the
sanitiser could strip.

```yaml
type: markdown
title: Warnings
content: >-
  {% set marks = {'minor': '🟨', 'moderate': '🟧', 'unknown': '🟧', 'severe': '🟥', 'extreme': '🟪'} %}
  {% for w in state_attr('sensor.<title>_warning_count', 'warnings') or [] %}
  {{ marks[w.level] }} <ha-icon icon="{{ w.icon }}"></ha-icon>
  **{{ w.event }}**: {{ w.headline }}

  {% endfor %}
```

`unknown` has no amber emoji square, so it shares orange with `moderate` here; the order of the
rows still shows the ranking.

## Colours

Defined once in `custom_components/bom_warnings/const.py` (`LEVEL_COLORS`): minor `#FDD835`,
moderate `#FB8C00`, unknown `#FF6F00` (deep amber), severe `#D32F2F`, extreme `#7B1FA2`.

## Fire danger rating

`sensor.<title>_fire_danger_today` and `sensor.<title>_fire_danger_tomorrow` exist when your
location is in a BoM fire weather district (all states publish a product; see
`docs/architecture.md`). The state is `no_rating`, `moderate`, `high`, `extreme` or `catastrophic`
(shown translated), or unknown when the latest issue has no period for that day or the level is
new to the integration (the text is then in the `level` attribute). Attributes: `level`, `color`,
`icon`, `fire_behaviour_index`, `forecast` (a list of `date`, `level`, `fire_behaviour_index`),
`issued`, `district`, `source`.

Colours, from BoM's own fire danger legend (defined once in `const.py`, `FIRE_DANGER_COLORS`):

| Level | Colour | Icon |
| --- | --- | --- |
| No Rating | grey `#949494` | `mdi:fire-off` |
| Moderate | green `#64BF30` | `mdi:fire-circle` |
| High | yellow `#FEDD3A` | `mdi:fire` |
| Extreme | orange `#F78100` | `mdi:fire-alert` |
| Catastrophic | red `#AD0909` | `mdi:alert-octagon` |

```yaml
type: markdown
title: Fire danger
content: >-
  {% for e in ['today', 'tomorrow'] %}
  {% set s = states['sensor.<title>_fire_danger_' ~ e] %}
  <font color="{{ s.attributes.color }}"><ha-icon icon="{{ s.attributes.icon }}"></ha-icon></font>
  **{{ e | title }}**: {{ s.state | replace('_', ' ') | title }}

  {% endfor %}
```

The emoji variant, for the same reason as above. Its squares follow the BoM legend order: white,
green, yellow, orange, red.

```yaml
type: markdown
title: Fire danger
content: >-
  {% set marks = {'no_rating': '⬜', 'moderate': '🟩', 'high': '🟨', 'extreme': '🟧', 'catastrophic': '🟥'} %}
  {% for e in ['today', 'tomorrow'] %}
  {% set s = states['sensor.<title>_fire_danger_' ~ e] %}
  {{ marks.get(s.state, '⬜') }} <ha-icon icon="{{ s.attributes.icon }}"></ha-icon>
  **{{ e | title }}**: {{ s.state | replace('_', ' ') | title }}

  {% endfor %}
```

A tile or entity card shows the dynamic icon without any template.

## Screenshots

What each snippet rendered as on Home Assistant 2026.10.4, light theme left and dark right. The
list uses the live warnings at the time: two moderate (orange) for the warning zone entry, and one
severe (red) for a Cairns entry.

| Snippet | Light | Dark |
| --- | --- | --- |
| Markdown card, coloured icon, two moderate warnings | ![](images/dashboard/warning-list-two-moderate-light.png) | ![](images/dashboard/warning-list-two-moderate-dark.png) |
| Same, one severe warning | ![](images/dashboard/warning-list-severe-light.png) | ![](images/dashboard/warning-list-severe-dark.png) |
| Same, no warnings | ![](images/dashboard/warning-list-empty-light.png) | ![](images/dashboard/warning-list-empty-dark.png) |
| Markdown card, emoji squares | ![](images/dashboard/warning-list-emoji-light.png) | ![](images/dashboard/warning-list-emoji-dark.png) |
| Fire danger, coloured icon (High is yellow) | ![](images/dashboard/fire-danger-colour-light.png) | ![](images/dashboard/fire-danger-colour-dark.png) |
| Fire danger, emoji squares | ![](images/dashboard/fire-danger-emoji-light.png) | ![](images/dashboard/fire-danger-emoji-dark.png) |

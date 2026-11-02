# Dashboard: the ranked warning list

**Not verified in a browser.** These snippets were written against the attribute shape the tests
check, but I could not render them in Home Assistant. Please check:

- Whether the Markdown card keeps the inline `style="color: ..."` on `<ha-icon>`. Its HTML
  sanitiser may strip `style`. If the icons show but are not coloured, use the emoji variant
  below, which needs no styles.
- Whether `<ha-icon>` itself renders inside a Markdown card (it does in the versions I know, but
  this is also unchecked).
- Replace `<title>` with your entry's slug. For an entry titled `Home` the entity is
  `sensor.home_warning_count`.

I left out a `flex-table-card` or `custom:button-card` variant: I do not know their config for
looping over a list attribute well enough to give you something correct.

## What the data looks like

`state_attr('sensor.<title>_warning_count', 'warnings')` is a list, most severe first, only for
warnings covering your location. Each item has `product_id`, `event`, `severity`, `level`
(`minor`, `moderate`, `unknown`, `severe`, `extreme`), `icon` (an `mdi:` name), `color` (hex),
`headline`, `phase`, `sent`, `effective` and `expires`. With the option to keep final and cancelled
warnings, ended ones come after the current ones with `phase` set to `final` or `cancelled`.

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
  <ha-icon icon="{{ w.icon }}" style="color: {{ w.color }}"></ha-icon>
  <span style="color: {{ w.color }}">&#9632;</span>
  **{{ w.event }}** ({{ w.level }}{% if w.phase in ['final', 'cancelled'] %}, {{ w.phase }}{% endif %}):
  {{ w.headline }}

  {% endfor %}
```

## Markdown card, no inline styles (fallback)

Uses coloured emoji squares for the level instead of CSS, so it survives a sanitiser.

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

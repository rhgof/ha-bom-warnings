"""Constants for the BoM Warnings integration."""

DOMAIN = "bom_warnings"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_STATE = "state"
CONF_AREA_CODES = "area_codes"
# The name of each stored code that has one, as {code: name}. Absent on an entry made before names
# were stored, which is how the coordinator knows to look them up once.
CONF_AREA_NAMES = "area_names"
# Set only on entries that follow a Home Assistant zone: its entity id, and its radius in metres.
CONF_ZONE = "zone"
CONF_RADIUS = "radius"
# A circle larger than this would list a whole state's warnings and make matching slow, so a
# bigger zone is clamped and the user is told.
MAX_RADIUS_M = 50_000.0
SPATIAL_CACHE_DIR = "bom_warnings/spatial"

# Options. Defaults keep today's behaviour: ended warnings hidden, every warning type on.
CONF_HIDE_FINAL = "hide_final_cancelled"
# The checklist: the keys of the warning types the location cares about (the keys of
# `warning_types.WARNING_TYPES`, plus OTHER_WARNINGS). Absent means every type is on.
CONF_WARNING_TYPES = "warning_types"
# Covers a warning whose CAP event has no row in `warning_types.WARNING_TYPES` (tsunami, and any
# type BoM adds later), so a new type is neither silently dropped nor impossible to turn off.
OTHER_WARNINGS = "other_warnings"
# The options of entries from before the checklist (config entry version 1). Only the migration
# reads them: an event-type filter, and whether coastal waters counted.
CONF_EVENT_TYPES = "event_types"
CONF_INCLUDE_MARINE = "include_marine"

# The colour of each level, which are the CAP severities. The order that ranks them is
# `active_warnings.SEVERITY_ORDER`, not the order here. Colours run yellow to purple.
LEVEL_COLORS = {
    "minor": "#FDD835",
    "moderate": "#FB8C00",
    "unknown": "#FF6F00",
    "severe": "#D32F2F",
    "extreme": "#7B1FA2",
}

DEFAULT_EVENT_ICON = "mdi:alert-circle"

NO_WARNING_ICON = "mdi:check-circle-outline"

# Fire danger rating levels, lowest first (the keys the parser stores), with the colours BoM's own
# fire danger legend uses (the `fireDanger` palette in bom.gov.au's front-end bundle, read
# 2026-11-02), and one icon each. Every icon name is checked against the frontend list in tests.
FIRE_DANGER_COLORS = {
    "no_rating": "#949494",
    "moderate": "#64BF30",
    "high": "#FEDD3A",
    "extreme": "#F78100",
    "catastrophic": "#AD0909",
}
FIRE_DANGER_ICONS = {
    "no_rating": "mdi:fire-off",
    "moderate": "mdi:fire-circle",
    "high": "mdi:fire",
    "extreme": "mdi:fire-alert",
    "catastrophic": "mdi:alert-octagon",
}
# For a day with no data, or a level this code does not know.
DEFAULT_FIRE_DANGER_ICON = "mdi:help-circle-outline"

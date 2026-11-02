"""Constants for the BoM Warnings integration."""

DOMAIN = "bom_warnings"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_STATE = "state"
CONF_AREA_CODES = "area_codes"
# Set only on entries that follow a Home Assistant zone: its entity id, and its radius in metres.
CONF_ZONE = "zone"
CONF_RADIUS = "radius"
# A circle larger than this would list a whole state's warnings and make matching slow, so a
# bigger zone is clamped and the user is told.
MAX_RADIUS_M = 50_000.0
SPATIAL_CACHE_DIR = "bom_warnings/spatial"

# Options. Defaults keep today's behaviour: ended warnings hidden, every warning type on.
CONF_HIDE_FINAL = "hide_final_cancelled"
# The checklist: the keys of the warning types the location cares about (the second column of
# WARNING_TYPE_SENSORS, plus OTHER_WARNINGS). Absent means every type is on.
CONF_WARNING_TYPES = "warning_types"
# Covers a warning whose CAP event has no row in WARNING_TYPE_SENSORS (tsunami, and any type BoM
# adds later), so a new type is neither silently dropped nor impossible to turn off.
OTHER_WARNINGS = "other_warnings"
# The options of entries from before the checklist (config entry version 1). Only the migration
# reads them: an event-type filter, and whether coastal waters counted.
CONF_EVENT_TYPES = "event_types"
CONF_INCLUDE_MARINE = "include_marine"
# Every `<event>` seen in recorded BoM CAP files (tests/fixtures/cap and cap_samples), sorted; the
# options field also accepts any other name. "Weather" covers both severe weather and coastal
# hazard warnings, so it cannot tell them apart.
KNOWN_EVENT_TYPES = (
    "Exposure",
    "Extreme Heat",
    "Fire Weather",
    "Frost",
    "Hazardous Road Conditions",
    "Large Coastal Surf",
    "Riverine Flood",
    "Sheep Grazier Warning",
    "Thunderstorm",
    "Tropical Cyclone",
    "Tsunami",
    "Weather",
    "Wind",
)

# Ranking level of a warning, lowest first, with its colour. The levels are CAP severities, but
# `unknown` sits between moderate and severe: BoM sends it for Severe Weather and Severe
# Thunderstorm warnings, which must not rank below a minor flood. Colours run yellow to purple.
LEVEL_COLORS = {
    "minor": "#FDD835",
    "moderate": "#FB8C00",
    "unknown": "#FF6F00",
    "severe": "#D32F2F",
    "extreme": "#7B1FA2",
}

# One icon per CAP event; every name is checked against the frontend icon list in the tests.
EVENT_ICONS = {
    "Exposure": "mdi:snowflake-thermometer",
    "Extreme Heat": "mdi:thermometer-alert",
    "Fire Weather": "mdi:fire-alert",
    "Frost": "mdi:snowflake-alert",
    "Hazardous Road Conditions": "mdi:car-brake-alert",
    "Large Coastal Surf": "mdi:waves-arrow-up",
    "Riverine Flood": "mdi:home-flood",
    "Sheep Grazier Warning": "mdi:sheep",
    "Thunderstorm": "mdi:weather-lightning-rainy",
    "Tropical Cyclone": "mdi:weather-hurricane",
    "Tsunami": "mdi:tsunami",
    "Weather": "mdi:cloud-alert",
    "Wind": "mdi:weather-windy",
}
DEFAULT_EVENT_ICON = "mdi:alert-circle"

# One binary sensor per warning type: (CAP event, translation key). The key is also the name of the
# type's toggle in the options checklist, so a type is switched on or off in one place and its
# sensor exists only while it is on. The icon comes from EVENT_ICONS, the single place an event gets
# one. A new type is a new row here, plus its name in strings.json. Tsunami has no zones yet (#25).
# The marine rows (Wind, Large Coastal Surf) only ever match a location whose area codes reach a
# coastal water zone.
WARNING_TYPE_SENSORS = (
    ("Thunderstorm", "thunderstorm_warning"),
    ("Fire Weather", "fire_weather_warning"),
    ("Extreme Heat", "extreme_heat_warning"),
    ("Frost", "frost_warning"),
    ("Hazardous Road Conditions", "hazardous_road_conditions_warning"),
    ("Riverine Flood", "flood_warning"),
    ("Sheep Grazier Warning", "sheep_grazier_warning"),
    ("Exposure", "exposure_warning"),
    ("Tropical Cyclone", "tropical_cyclone_warning"),
    ("Weather", "severe_weather_warning"),
    ("Wind", "marine_wind_warning"),
    ("Large Coastal Surf", "hazardous_surf_warning"),
)
# An entity has no description field, so a type that is easy to misread says so in a `note`
# attribute. BoM's Wind event is marine wind, which is not wind at the house. Its Weather event is
# both the Severe Weather Warning and the Coastal Hazard Warning, and which of the two a warning is
# can only be told from its headline, so it is no automation trigger.
WARNING_TYPE_NOTES = {
    "Wind": (
        "Marine wind only: BoM's Wind event is for coastal and local waters, not wind at your "
        "house. Damaging winds on land arrive as the Severe weather warning."
    ),
    "Weather": (
        "For display. BoM's Weather event covers both Severe Weather Warnings and Coastal Hazard "
        "Warnings, so it is not a good automation trigger."
    ),
}
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

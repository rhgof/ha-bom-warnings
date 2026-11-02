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

# Options. Defaults keep today's behaviour: ended warnings hidden, every warning type shown.
CONF_HIDE_FINAL = "hide_final_cancelled"
CONF_EVENT_TYPES = "event_types"
# Count warnings for coastal waters inside a zone's circle. Off by default: the circle reaches
# the water only when it is large enough, and surf and wind warnings are noise inland.
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

# One binary sensor per warning type, each disabled by default so a user enables only the types an
# automation needs: (CAP event, translation key). The icon comes from EVENT_ICONS, the single place
# an event gets one. A new type is a new row here, plus its name in strings.json.
WARNING_TYPE_SENSORS = (("Thunderstorm", "thunderstorm_warning"),)
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

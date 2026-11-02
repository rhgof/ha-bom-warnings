"""Constants for the BoM Warnings integration."""

DOMAIN = "bom_warnings"
CONF_LATITUDE = "latitude"
CONF_LONGITUDE = "longitude"
CONF_STATE = "state"
CONF_AREA_CODES = "area_codes"
SPATIAL_CACHE_DIR = "bom_warnings/spatial"

# Options. Defaults keep today's behaviour: ended warnings hidden, every warning type shown.
CONF_HIDE_FINAL = "hide_final_cancelled"
CONF_EVENT_TYPES = "event_types"
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
NO_WARNING_ICON = "mdi:check-circle-outline"

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

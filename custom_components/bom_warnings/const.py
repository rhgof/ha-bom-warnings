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
# Event names seen in BoM CAP files; the options field also accepts any other name.
KNOWN_EVENT_TYPES = (
    "Bushfire",
    "Extreme Heat",
    "Fire Weather",
    "Flood Watch",
    "Riverine Flood",
    "Severe Thunderstorm",
    "Severe Weather",
    "Thunderstorm",
    "Tropical Cyclone",
    "Wind",
)

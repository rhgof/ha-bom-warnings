# BoM sample CAP files, one per warning type

Unmodified files from BoM's public sample catalogue, captured 2026-11-02 over anonymous FTP from
`ftp://ftp.bom.gov.au/anon/sample/catalogue/Warnings/<type>/`. They cover warning types that are
only on the live feed while the hazard is current.

They are samples, not live warnings: the hazards were not necessarily present, and the dates are
old (mostly November 2025). Do not rely on `is_active(now)` with a real `now`. Tests pick a time
inside each file's `sent`..`expires` window; the fake server's `all_types` scenario shifts the
timestamps so they look current.

| File | Type | CAP `event` | Area codes |
| --- | --- | --- | --- |
| IDT38200.cap.xml | Bushwalkers Weather Alert (TAS) | Exposure | PW |
| IDQ21137.cap.xml | Coastal Hazard Warning | Weather | PW |
| IDN22000.cap.xml | Fire Weather Warning | Fire Weather | FW |
| IDV23000.cap.xml | Frost Warning | Frost | PW |
| IDN28522.cap.xml | Hazardous Surf Warning | Large Coastal Surf | MW |
| IDQ21013.cap.xml | Heatwave Warning | Extreme Heat | PW |
| IDD20105.cap.xml | Marine Wind Warning Summary | Wind | MW |
| IDS20240.cap.xml | Road Weather Alert | Hazardous Road Conditions | ME |
| IDQ21033.cap.xml | Severe Thunderstorm Warning | Thunderstorm | PW |
| IDN21037.cap.xml | Severe Weather Warning | Weather | PW |
| IDT29000.cap.xml | Warning to Sheep Graziers | Sheep Grazier Warning | PW |
| IDD24500.cap.xml | Tropical Cyclone Warning | Tropical Cyclone | PT, PW |
| IDY68027_cap.xml | Tsunami Warning | Tsunami | TW |

The tsunami file is named `_cap.xml` (underscore), unlike the others, and its dates are in the
year 3004. Flood and ocean wind have no CAP sample; `../cap/` holds real flood warnings.

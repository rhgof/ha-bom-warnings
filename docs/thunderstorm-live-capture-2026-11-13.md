# Live thunderstorm warnings: IDN21033 and IDN21035 (13 Nov 2026)

A capture of two real Severe Thunderstorm Warnings, to refine the thunderstorm handling from real data (tickets #77 and #78). Both were current for the Sydney area on the day, which makes it a useful pair: IDN21033 is the broad forecast-district warning and IDN21035 is the narrow, storm-cell warning.

- Captured: 2026-11-13 06:25Z (about 17:25 local), read-only, anonymous FTP `ftp.bom.gov.au:/anon/gen/fwo/`, through the integration's own client.
- Raw files, unmodified: `tests/fixtures/products/2026-11-13T0625Z-thunderstorm/` (IDN21033.cap.xml, IDN21033.txt, IDN21033.xml, IDN21035.cap.xml, IDN21035.txt, IDN21035.xml).
- Everything below the raw files is generated from them by the integration's own parsers (`cap.parse_cap`, `product_xml.parse_product`, `active_warnings.summary_of`).
- Not captured: `.pdf`, `.html`, `.ps`, `.amoc.xml` (they exist beside both products).

| File | Bytes | BoM listing time (UTC) |
|---|---|---|
| `IDN21033.cap.xml` | 6,997 | 2026-11-13 06:11:54 |
| `IDN21033.txt` | 3,146 | 2026-11-13 06:11:46 |
| `IDN21033.xml` | 119,269 | 2026-11-13 06:11:55 |
| `IDN21035.cap.xml` | 5,257 | 2026-11-13 06:14:09 |
| `IDN21035.txt` | 2,597 | 2026-11-13 06:14:03 |
| `IDN21035.xml` | 255,693 | 2026-11-13 06:14:11 |


> **Since this was written** (commit `7e0c801`, then the dashboard card): fact 1 is handled by
> reading "Detailed" from the `.txt`; facts 2 and 4 are fixed (the summary is the paragraph that
> names your area, and a Detailed summary is not cut at 300 characters); fact 3 is handled by
> reading `hazards` from that paragraph, not from the XML codes; fact 7 by working per block. The
> XML is still not read for thunderstorms (5, 10). Facts 6, 8 and 9 stand, though `next_issue` now
> tells a card when the next warning is due. The later captures, including a cancellation, are in
> `warning-products.md`.

---

# IDN21033

## 1. What the integration understands from the CAP file

Product `IDN21033`, identifier `AusBoM-IDN21033-2026-11-13T06:11:38+00:00`, sent 2026-11-13 06:11:38Z, message phase `update`, 2 info block(s). Each block is one warning, matched to a location by its area codes.

### Block 1: Thunderstorm / update

| Field | Value |
|---|---|
| `event` | Thunderstorm |
| `phase` | update |
| `severity` | unknown (the sensor shows `unrated` for `unknown`) |
| `effective` | 2026-11-13 06:11:32+00:00 |
| `expires` | 2026-11-13 11:11:32+00:00 |
| `is_active` now | True |
| `area_codes` (7) | NSW_PW001, NSW_PW002, NSW_PW003, NSW_PW004, NSW_PW005, NSW_PW008, NSW_PW011 |
| `area_desc` | New South Wales: Northern Rivers, Mid North Coast, Hunter, Metropolitan, Central Tablelands, North West Slopes and Plains and Northern Tablelands |
| `headline` | Severe Thunderstorm Warning for Sydney Metropolitan, Northern Rivers, Mid North Coast, Hunter, Northern Tablelands, Central Tablelands and North West Slopes and Plains forecast districts |
| `summary` as the sensor attribute (`summary_of(description)`) | Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding and damaging winds over the next several hours in parts of the Northern Rivers, Mid North Coast, Northern Tablelands and North West Slopes and Plains districts. Locations which may be affected include Dorrigo,… |

`description` in full, as parsed:

```
Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding and damaging winds over the next several hours in parts of the Northern Rivers, Mid North Coast, Northern Tablelands and North West Slopes and Plains districts. Locations which may be affected include Dorrigo, Nymboida, Ebor and Boggabilla.  
          
          Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones over the next several hours in parts of the Hunter, Metropolitan, Mid North Coast and Central Tablelands districts. Locations which may be affected include Cessnock, Penrith, Barrington Tops, Singleton, Putty and Wollombi.  
          
          
          Severe thunderstorms are no longer occurring in the Illawarra and Southern Tablelands districts and the warning for these districts is CANCELLED.
```

### Block 2: Thunderstorm / cancelled

| Field | Value |
|---|---|
| `event` | Thunderstorm |
| `phase` | cancelled |
| `severity` | unknown (the sensor shows `unrated` for `unknown`) |
| `effective` | 2026-11-13 06:11:32+00:00 |
| `expires` | 2026-11-13 11:11:32+00:00 |
| `is_active` now | False |
| `area_codes` (2) | NSW_PW006, NSW_PW009 |
| `area_desc` | New South Wales: Illawarra and Southern Tablelands forecast districts |
| `headline` | Cancellation of Severe Thunderstorm Warning for Illawarra and Southern Tablelands forecast districts |
| `summary` as the sensor attribute (`summary_of(description)`) | (none) |

`description` in full, as parsed:

```
(empty)
```

CAP elements present but **not parsed into `Info`** (the parser keeps no `instruction`, `urgency` or `certainty`):

- `<category>` Met
- `<urgency>` Unknown
- `<certainty>` Unknown
- `<senderName>` Australian Government Bureau of Meteorology
- `<instruction>` The State Emergency Service advises that people should:
* Park your car under secure cover and away from trees, powerlines and drains.
* Secure or put away loose items around your house, yard and balcony.
* Keep at least 8 metres away from fallen power lines or objects that may be energised, such as
- `<web>` http://www.bom.gov.au/australia/warnings
- `<contact>` http://www.bom.gov.au/inside/contacts.shtml

## 2. The `.txt` file, verbatim

```
IDN21033
Australian Government Bureau of Meteorology

TOP PRIORITY FOR IMMEDIATE BROADCAST

Severe Thunderstorm Warning
for HEAVY RAINFALL, DAMAGING WINDS and LARGE HAILSTONES

For people in parts of Northern Rivers, Mid North Coast, Hunter, Metropolitan, Northern Tablelands, Central Tablelands and North West Slopes and Plains Forecast Districts.

Issued at 5:11 pm Friday, 13 November 2026.

Severe thunderstorms this afternoon about the Northern and eastern New South Wales.

Weather situation: A warm and humid environment with slow moving severe thunderstorms about northern and eastern parts of New South Wales.

Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding and damaging winds over the next several hours in parts of the Northern Rivers, Mid North Coast, Northern Tablelands and North West Slopes and Plains districts. Locations which may be affected include Dorrigo, Nymboida, Ebor and Boggabilla.

Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones over the next several hours in parts of the Hunter, Metropolitan, Mid North Coast and Central Tablelands districts. Locations which may be affected include Cessnock, Penrith, Barrington Tops, Singleton, Putty and Wollombi.

Severe thunderstorms are no longer occurring in the Illawarra and Southern Tablelands districts and the warning for these districts is CANCELLED.

The State Emergency Service advises that people should:
    * Park your car under secure cover and away from trees, powerlines and drains. 
    * Secure or put away loose items around your house, yard and balcony. 
    * Keep at least 8 metres away from fallen power lines or objects that may be energised, such as fences. 
    * Report fallen power lines to either Ausgrid (131 388), Endeavour Energy (131 003), Essential Energy (132 080) or Evoenergy (131 093) as shown on your power bill. 
    * Keep clear of creeks and storm drains. 
    * Don't walk, ride your bike or drive through flood water. 
    * If you are trapped by flash flooding, seek refuge in the highest available place and ring 000 if you need rescue. 
    * Stay indoors away from windows, and keep children and pets indoors as well. 
For emergency help in flood and storms, ring the SES on 132 500. 
Stay updated on the Hazards Near Me NSW app or the ACT ESA website (https://esa.act.gov.au). 
 

The next warning is due to be issued by 8:15 pm.

A more Detailed Severe Thunderstorm Warning has been issued to people in Sydney Newcastle Wollongong and surrounding areas. Other warnings may be current.

Check https://www.bom.gov.au/weather-and-climate/warnings-and-alerts. Warnings are also available through TV and Radio broadcasts or call 1300 659 210. The Bureau and State Emergency Service would appreciate warnings being broadcast regularly.


Copyright Commonwealth of Australia 2011, Bureau of Meteorology (ABN 92 637 533
532).  Users of these web pages are deemed to have read and accepted the
conditions described in the Copyright, Disclaimer, and Privacy statements
(http://www.bom.gov.au/other/copyright.shtml).
```

## 3. The product XML as the integration understands it

`parse_product` result: identifier `IDN21033`, sent 2026-11-13 06:11:38+00:00, phase `UPD`, 2 hazard(s). Unseen codes are kept verbatim.

### Hazard 1: type `STW`, phase `UPD`, severity `STD`

- `phenomena`: ''
- `area_text`: 'Northern Rivers, Mid North Coast, Hunter, Metropolitan, Central Tablelands, North West Slopes and Plains and Northern Tablelands'
- `text`: ''
- areas (7): `NSW_PW005` Sydney Metropolitan (public-district, NEW); `NSW_PW001` Northern Rivers (public-district, REN); `NSW_PW002` Mid North Coast (public-district, REN); `NSW_PW003` Hunter (public-district, NEW); `NSW_PW004` Northern Tablelands (public-district, REN); `NSW_PW008` Central Tablelands (public-district, NEW); `NSW_PW011` North West Slopes and Plains (public-district, REN)

### Hazard 2: type `STW`, phase `CAN`, severity `CAN`

- `phenomena`: ''
- `area_text`: ''
- `text`: ''
- areas (2): `NSW_PW006` Illawarra (public-district, CAN); `NSW_PW009` Southern Tablelands (public-district, CAN)

### Raw XML outline (every element, with base64 map data not shown)

```xml
<product version="1.7" {http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation="http://www.bom.gov.au/schema/v1.7/product.xsd">
  <amoc>
    <source>
      <sender>  Australian Government Bureau of Meteorology
      <region>  New South Wales
      <office>  NSWRO
      <copyright>  http://www.bom.gov.au/other/copyright.shtml
      <disclaimer>  http://www.bom.gov.au/other/disclaimer.shtml
    <identifier>  IDN21033
    <issue-time-utc>  2026-11-13T06:11:38Z
    <issue-time-local tz="EDT">  2026-11-13T17:11:38+11:00
    <sent-time>  2026-11-13T06:11:38Z
    <expiry-time>  2026-11-13T11:11:32Z
    <validity-bgn-time-local tz="EDT">  2026-11-13T17:11:32+11:00
    <validity-end-time-local tz="EDT">  2026-11-13T22:11:31+11:00
    <status>  O
    <service>  WSW
    <sub-service>  WST
    <product-type>  W
    <phase>  UPD
  <warning>
    <warning-info>
      <text type="warning_title">
        <p>  Severe Thunderstorm Warning
      <text type="warning_area_summary">
        <p>  parts of Northern Rivers, Mid North Coast, Hunter, Metropolitan, Northern Tablelands, Central Tablelands and North West Slopes and Plains Forecast Districts.
        <p>
      <text type="warning_phenomena_summary">
        <p>  for HEAVY RAINFALL, DAMAGING WINDS and LARGE HAILSTONES
      <text type="issued_at">
        <p>  Issued at 5:11 pm Friday, 13 November 2026.
        <p>
      <text type="warning_advice">
        <p>  The State Emergency Service advises that people should:
        <p>  * Park your car under secure cover and away from trees, powerlines and drains.
        <p>  * Secure or put away loose items around your house, yard and balcony.
        <p>  * Keep at least 8 metres away from fallen power lines or objects that may be energised, such as fences.
        <p>  * Report fallen power lines to either Ausgrid (131 388), Endeavour Energy (131 003), Essential Energy (132 080) or Evoenergy (131 093) as shown on your power bill.
        <p>  * Keep clear of creeks and storm drains.
        <p>  * Don't walk, ride your bike or drive through flood water.
        <p>  * If you are trapped by flash flooding, seek refuge in the highest available place and ring 000 if you need rescue.
        <p>  * Stay indoors away from windows, and keep children and pets indoors as well.
        <p>  For emergency help in flood and storms, ring the SES on 132 500.
        <p>  Stay updated on the Hazards Near Me NSW app or the ACT ESA website (https://esa.act.gov.au).
        <p>
      <text type="warning_next_issue">  The next warning is due to be issued by 8:15 pm.
      <text type="product_footer">
        <p>  Check https://www.bom.gov.au/weather-and-climate/warnings-and-alerts. Warnings are also available through TV and Radio broadcasts or call 1300 659 210. The Bureau and State Emergency Service would appreciate warnings being broadcast regularly.
        <p>
    <area aac="NSW_FA001" description="New South Wales" type="region">
      <forecast-period start-time-local="2026-11-13T17:11:32+11:00" end-time-local="2026-11-13T20:11:32+11:00" start-time-utc="2026-11-13T06:11:32Z" end-time-utc="2026-11-13T09:11:32Z">
        <text type="warning_headline">  Severe thunderstorms this afternoon about the Northern and eastern New South Wales.
        <text type="synoptic_situation">
          <p>  Weather situation: A warm and humid environment with slow moving severe thunderstorms about northern and eastern parts of New South Wales.
        <text type="cross_metropolitan_advice">
          <p>  A more Detailed Severe Thunderstorm Warning has been issued to people in Sydney Newcastle Wollongong and surrounding areas.
          <p>
          <p>  Other warnings may be current.
        <element type="warning_image">  [base64 data, 109532 chars, not shown]
        <text type="forecast">
          <p>  Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding and damaging winds over the next several hours in parts of the Northern Rivers, Mid North Coast, Northern Tablelands and North West Slopes and Plains districts. Locations which may be affected include Dorrigo, Nymboida, Ebor and Boggabilla.
          <p>
          <p>  Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones over the next several hours in parts of the Hunter, Metropolitan, Mid North Coast and Central Tablelands districts. Locations which may be affected include Cessnock, Penrith, Barrington Tops, Singleton, Putty and Wollombi.
          <p>
          <p>
          <p>  Severe thunderstorms are no longer occurring in the Illawarra and Southern Tablelands districts and the warning for these districts is CANCELLED.
          <p>
      <hazard index="1" parent-aac="NSW_EV001" phase="UPD" type="STW" severity="STD" urgency="UNK" certainty="UNK" start-time-local="2026-11-13T17:11:32+11:00" end-time-local="2026-11-13T22:11:32+11:00" start-time-utc="2026-11-13T06:11:32Z" end-time-utc="2026-11-13T11:11:32Z">
        <area-list>
          <area aac="NSW_PW005" phase="NEW" description="Sydney Metropolitan" type="public-district">
          <area aac="NSW_PW001" phase="REN" description="Northern Rivers" type="public-district">
          <area aac="NSW_PW002" phase="REN" description="Mid North Coast" type="public-district">
          <area aac="NSW_PW003" phase="NEW" description="Hunter" type="public-district">
          <area aac="NSW_PW004" phase="REN" description="Northern Tablelands" type="public-district">
          <area aac="NSW_PW008" phase="NEW" description="Central Tablelands" type="public-district">
          <area aac="NSW_PW011" phase="REN" description="North West Slopes and Plains" type="public-district">
        <phenomenon-list>
          <phenomenon type="W">
          <phenomenon type="LH">
          <phenomenon type="R">
        <priority>  W
        <text type="warning_areas">  Northern Rivers, Mid North Coast, Hunter, Metropolitan, Central Tablelands, North West Slopes and Plains and Northern Tablelands
        <text type="warning">
          <p>  Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding and damaging winds over the next several hours in parts of the Northern Rivers, Mid North Coast, Northern Tablelands and North West Slopes and Plains districts. Locations which may be affected include Dorrigo, Nymboida, Ebor and Boggabilla.
          <p>
          <p>  Severe thunderstorms are likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones over the next several hours in parts of the Hunter, Metropolitan, Mid North Coast and Central Tablelands districts. Locations which may be affected include Cessnock, Penrith, Barrington Tops, Singleton, Putty and Wollombi.
          <p>
          <p>
          <p>  Severe thunderstorms are no longer occurring in the Illawarra and Southern Tablelands districts and the warning for these districts is CANCELLED.
          <p>
        <text type="warning_phenomena">
          <p>  HEAVY RAINFALL, DAMAGING WINDS and LARGE HAILSTONES
      <hazard index="2" parent-aac="NSW_EV001" phase="CAN" type="STW" severity="CAN" urgency="UNK" certainty="UNK" start-time-local="2026-11-13T17:11:32+11:00" end-time-local="2026-11-13T22:11:32+11:00" start-time-utc="2026-11-13T06:11:32Z" end-time-utc="2026-11-13T11:11:32Z">
        <area-list>
          <area aac="NSW_PW006" phase="CAN" description="Illawarra" type="public-district">
          <area aac="NSW_PW009" phase="CAN" description="Southern Tablelands" type="public-district">
        <priority>  W
```


---

# IDN21035

## 1. What the integration understands from the CAP file

Product `IDN21035`, identifier `AusBoM-IDN21035-2026-11-13T06:13:59+00:00`, sent 2026-11-13 06:13:59Z, message phase `update`, 2 info block(s). Each block is one warning, matched to a location by its area codes.

### Block 1: Thunderstorm / update

| Field | Value |
|---|---|
| `event` | Thunderstorm |
| `phase` | update |
| `severity` | unknown (the sensor shows `unrated` for `unknown`) |
| `effective` | 2026-11-13 06:13:45+00:00 |
| `expires` | 2026-11-13 08:43:45+00:00 |
| `is_active` now | True |
| `area_codes` (2) | NSW_ME014, NSW_ME017 |
| `area_desc` | New South Wales: Blue Mountains/Hawkesbury and Sydney |
| `headline` | Severe Thunderstorm Warning for Blue Mountains/Hawkesbury and Sydney |
| `summary` as the sensor attribute (`summary_of(description)`) | The Bureau of Meteorology warns that, at 5:15 pm, a severe thunderstorm likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones was detected near the Wollemi National Park north of Kurrajong and Kurrajong. This thunderstorm is moving towards the east.… |

`description` in full, as parsed:

```
The Bureau of Meteorology warns that, at 5:15 pm, a severe thunderstorm likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones was detected near the Wollemi National Park north of Kurrajong and Kurrajong. This thunderstorm is moving towards the east. It is forecast to affect Londonderry, Upper Colo and Castlereagh by 5:30 pm and Richmond, Windsor and Wilberforce by 5:45 pm.
```

### Block 2: Thunderstorm / cancelled

| Field | Value |
|---|---|
| `event` | Thunderstorm |
| `phase` | cancelled |
| `severity` | unknown (the sensor shows `unrated` for `unknown`) |
| `effective` | 2026-11-13 06:13:45+00:00 |
| `expires` | 2026-11-13 08:43:45+00:00 |
| `is_active` now | False |
| `area_codes` (1) | NSW_ME013 |
| `area_desc` | New South Wales: Wollondilly/Wingecarribee |
| `headline` | Cancellation of Severe Thunderstorm Warning for Wollondilly/Wingecarribee |
| `summary` as the sensor attribute (`summary_of(description)`) | (none) |

`description` in full, as parsed:

```
(empty)
```

CAP elements present but **not parsed into `Info`** (the parser keeps no `instruction`, `urgency` or `certainty`):

- `<category>` Met
- `<urgency>` Unknown
- `<certainty>` Unknown
- `<senderName>` Australian Government Bureau of Meteorology
- `<instruction>` The State Emergency Service advises that people should:
* Park your car under secure cover and away from trees, powerlines and drains.
* Secure or put away loose items around your house, yard and balcony.
* Keep at least 8 metres away from fallen power lines or objects that may be energised, such as
- `<web>` http://www.bom.gov.au/australia/warnings
- `<contact>` http://www.bom.gov.au/inside/contacts.shtml

## 2. The `.txt` file, verbatim

```
IDN21035
Australian Government Bureau of Meteorology

TOP PRIORITY FOR IMMEDIATE BROADCAST

Detailed Severe Thunderstorm Warning
for HEAVY RAINFALL, DAMAGING WINDS and LARGE HAILSTONES

For people in parts of Blue Mountains/Hawkesbury and Sydney areas.

Issued at 5:13 pm Friday, 13 November 2026.

Severe thunderstorms affecting parts of Blue Mountains/Hawkesbury and Sydney areas.

The Bureau of Meteorology warns that, at 5:15 pm, a severe thunderstorm likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones was detected near the Wollemi National Park north of Kurrajong and Kurrajong. This thunderstorm is moving towards the east. It is forecast to affect Londonderry, Upper Colo and Castlereagh by 5:30 pm and Richmond, Windsor and Wilberforce by 5:45 pm.

The State Emergency Service advises that people should:
    * Park your car under secure cover and away from trees, powerlines and drains. 
    * Secure or put away loose items around your house, yard and balcony. 
    * Keep at least 8 metres away from fallen power lines or objects that may be energised, such as fences. 
    * Report fallen power lines to either Ausgrid (131 388), Endeavour Energy (131 003), Essential Energy (132 080) or Evoenergy (131 093) as shown on your power bill. 
    * Keep clear of creeks and storm drains. 
    * Don't walk, ride your bike or drive through flood water. 
    * If you are trapped by flash flooding, seek refuge in the highest available place and ring 000 if you need rescue. 
    * Stay indoors away from windows, and keep children and pets indoors as well. 
For emergency help in flood and storms, ring the SES on 132 500. 
Stay updated on the Hazards Near Me NSW app or the ACT ESA website (https://esa.act.gov.au). 
 

The next warning is due to be issued by 5:45 pm.

A more general severe thunderstorm warning is also current for parts of the Northern Rivers, Mid North Coast, Hunter, Metropolitan, Northern Tablelands, Central Tablelands and North West Slopes and Plains districts. Other warnings may be current.

Check https://www.bom.gov.au/weather-and-climate/warnings-and-alerts. Warnings are also available through TV and Radio broadcasts or call 1300 659 210. The Bureau and State Emergency Service would appreciate warnings being broadcast regularly.


Copyright Commonwealth of Australia 2011, Bureau of Meteorology (ABN 92 637 533
532).  Users of these web pages are deemed to have read and accepted the
conditions described in the Copyright, Disclaimer, and Privacy statements
(http://www.bom.gov.au/other/copyright.shtml).
```

## 3. The product XML as the integration understands it

`parse_product` result: identifier `IDN21035`, sent 2026-11-13 06:13:59+00:00, phase `UPD`, 2 hazard(s). Unseen codes are kept verbatim.

### Hazard 1: type `STW`, phase `NEW`, severity `STD`

- `phenomena`: ''
- `area_text`: 'Blue Mountains/Hawkesbury and Sydney'
- `text`: ''
- areas (2): `NSW_ME014` Blue Mountains/Hawkesbury (metropolitan, NEW); `NSW_ME017` Sydney (metropolitan, NEW)

### Hazard 2: type `STW`, phase `CAN`, severity `CAN`

- `phenomena`: ''
- `area_text`: ''
- `text`: ''
- areas (1): `NSW_ME013` Wollondilly/Wingecarribee (metropolitan, CAN)

### Raw XML outline (every element, with base64 map data not shown)

```xml
<product version="1.7" {http://www.w3.org/2001/XMLSchema-instance}noNamespaceSchemaLocation="http://www.bom.gov.au/schema/v1.7/product.xsd">
  <amoc>
    <source>
      <sender>  Australian Government Bureau of Meteorology
      <region>  New South Wales
      <office>  NSWRO
      <copyright>  http://www.bom.gov.au/other/copyright.shtml
      <disclaimer>  http://www.bom.gov.au/other/disclaimer.shtml
    <identifier>  IDN21035
    <issue-time-utc>  2026-11-13T06:13:59Z
    <issue-time-local tz="EDT">  2026-11-13T17:13:59+11:00
    <sent-time>  2026-11-13T06:13:59Z
    <expiry-time>  2026-11-13T08:43:45Z
    <validity-bgn-time-local tz="EDT">  2026-11-13T17:13:45+11:00
    <validity-end-time-local tz="EDT">  2026-11-13T19:43:44+11:00
    <status>  O
    <service>  WSW
    <sub-service>  WST
    <product-type>  W
    <phase>  UPD
  <warning>
    <warning-info>
      <text type="warning_title">
        <p>  Detailed Severe Thunderstorm Warning
      <text type="warning_area_summary">
        <p>  parts of Blue Mountains/Hawkesbury and Sydney areas.
        <p>
      <text type="warning_phenomena_summary">
        <p>  for HEAVY RAINFALL, DAMAGING WINDS and LARGE HAILSTONES
      <text type="issued_at">
        <p>  Issued at 5:13 pm Friday, 13 November 2026.
        <p>
      <text type="warning_advice">
        <p>  The State Emergency Service advises that people should:
        <p>  * Park your car under secure cover and away from trees, powerlines and drains.
        <p>  * Secure or put away loose items around your house, yard and balcony.
        <p>  * Keep at least 8 metres away from fallen power lines or objects that may be energised, such as fences.
        <p>  * Report fallen power lines to either Ausgrid (131 388), Endeavour Energy (131 003), Essential Energy (132 080) or Evoenergy (131 093) as shown on your power bill.
        <p>  * Keep clear of creeks and storm drains.
        <p>  * Don't walk, ride your bike or drive through flood water.
        <p>  * If you are trapped by flash flooding, seek refuge in the highest available place and ring 000 if you need rescue.
        <p>  * Stay indoors away from windows, and keep children and pets indoors as well.
        <p>  For emergency help in flood and storms, ring the SES on 132 500.
        <p>  Stay updated on the Hazards Near Me NSW app or the ACT ESA website (https://esa.act.gov.au).
        <p>
      <text type="warning_next_issue">  The next warning is due to be issued by 5:45 pm.
      <text type="product_footer">
        <p>  Check https://www.bom.gov.au/weather-and-climate/warnings-and-alerts. Warnings are also available through TV and Radio broadcasts or call 1300 659 210. The Bureau and State Emergency Service would appreciate warnings being broadcast regularly.
        <p>
    <area aac="NSW_ME008" description="Greater Sydney and Surrounds" type="metropolitan">
      <forecast-period start-time-local="2026-11-13T17:13:45+11:00" end-time-local="2026-11-13T17:43:45+11:00" start-time-utc="2026-11-13T06:13:45Z" end-time-utc="2026-11-13T06:43:45Z">
        <text type="warning_headline">  Severe thunderstorms affecting parts of Blue Mountains/Hawkesbury and Sydney areas.
        <text type="cross_state_advice">
          <p>  A more general severe thunderstorm warning is also current for parts of the Northern Rivers, Mid North Coast, Hunter, Metropolitan, Northern Tablelands, Central Tablelands and North West Slopes and Plains districts.
          <p>
          <p>  Other warnings may be current.
        <element type="warning_image">  [base64 data, 107444 chars, not shown]
        <element type="history_image">  [base64 data, 109316 chars, not shown]
        <element type="meteogram_image">  [base64 data, 31132 chars, not shown]
        <text type="forecast">
          <p>  The Bureau of Meteorology warns that, at 5:15 pm, a severe thunderstorm likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones was detected near the Wollemi National Park north of Kurrajong and Kurrajong. This thunderstorm is moving towards the east. It is forecast to affect Londonderry, Upper Colo and Castlereagh by 5:30 pm and Richmond, Windsor and  …
          <p>
      <hazard index="1" parent-aac="NSW_ME008" phase="NEW" type="STW" severity="STD" urgency="UNK" certainty="UNK" start-time-local="2026-11-13T17:13:45+11:00" end-time-local="2026-11-13T19:43:45+11:00" start-time-utc="2026-11-13T06:13:45Z" end-time-utc="2026-11-13T08:43:45Z">
        <area-list>
          <area aac="NSW_ME014" phase="NEW" description="Blue Mountains/Hawkesbury" type="metropolitan">
          <area aac="NSW_ME017" phase="NEW" description="Sydney" type="metropolitan">
        <phenomenon-list>
          <phenomenon type="W">
          <phenomenon type="LH">
          <phenomenon type="R">
        <priority>  W
        <text type="warning_areas">  Blue Mountains/Hawkesbury and Sydney
        <text type="warning">
          <p>  The Bureau of Meteorology warns that, at 5:15 pm, a severe thunderstorm likely to produce heavy rainfall that may lead to flash flooding, damaging winds and large hailstones was detected near the Wollemi National Park north of Kurrajong and Kurrajong. This thunderstorm is moving towards the east. It is forecast to affect Londonderry, Upper Colo and Castlereagh by 5:30 pm and Richmond, Windsor and  …
          <p>
        <text type="warning_phenomena">
          <p>  HEAVY RAINFALL, DAMAGING WINDS and LARGE HAILSTONES
      <hazard index="2" parent-aac="NSW_ME008" phase="CAN" type="STW" severity="CAN" urgency="UNK" certainty="UNK" start-time-local="2026-11-13T17:13:45+11:00" end-time-local="2026-11-13T19:43:45+11:00" start-time-utc="2026-11-13T06:13:45Z" end-time-utc="2026-11-13T08:43:45Z">
        <area-list>
          <area aac="NSW_ME013" phase="CAN" description="Wollondilly/Wingecarribee" type="metropolitan">
        <priority>  W
```


---

# Side by side: what to look at when refining

Facts only, from the files above. Nothing here has been changed in the integration.

| | IDN21033 (broad) | IDN21035 (detailed) |
|---|---|---|
| Title in `.txt` and product XML | Severe Thunderstorm Warning | **Detailed** Severe Thunderstorm Warning |
| CAP headline | "Severe Thunderstorm Warning for Sydney Metropolitan, … forecast districts" | "Severe Thunderstorm Warning for Blue Mountains/Hawkesbury and Sydney" (no "Detailed") |
| Area layer and codes | public forecast districts, `NSW_PW…` | metropolitan sub-areas, `NSW_ME…` |
| Validity | 17:11 to 22:11 AEDT (5 h) | 17:13 to 19:43 AEDT (2.5 h); forecast period 17:13:45 to 17:43:45 (30 min) |
| Next issue | by 8:15 pm | by 5:45 pm |
| Description | several paragraphs, one per group of districts | one paragraph: a located storm cell, its movement and place-by-time forecast |
| CAP `severity` | Unknown | Unknown |
| XML hazard `severity` | `STD` | `STD` |
| XML phenomena codes | `W`, `LH`, `R` | `W`, `LH`, `R` |
| XML size | 119,269 bytes | 255,693 bytes |
| Embedded images | `warning_image` (109,532 base64 chars) | `warning_image`, `history_image`, `meteogram_image` (107,444, 109,316, 31,132) |

## Facts that matter for refining the thunderstorm handling

1. **"Detailed" is in the `.txt` and product XML title, not in CAP.** A CAP-only reader has indirect
   signals only: the `NSW_ME` area codes, a description that opens "The Bureau of Meteorology warns
   that, at …", and a headline that ends "for <areas>" without "forecast districts". The
   product XML `warning_title` states it outright.
2. **The summary for the broad warning is the wrong paragraph for Sydney.** `summary_of` takes the first
   paragraph of IDN21033's description, which is about Dorrigo, Nymboida, Ebor and Boggabilla (Northern
   Rivers, Mid North Coast, Northern Tablelands, North West Slopes and Plains). The paragraph that
   covers Hunter, Metropolitan, Mid North Coast and Central Tablelands is the second. The Home entries
   matched Hunter, Metropolitan and Central Tablelands, so their summary is about places 300 km away.
3. **The hazard differs by paragraph, but the XML codes are for the whole product.** The first paragraph
   of IDN21033 names heavy rainfall and damaging winds; the second adds large hailstones. The XML
   `phenomenon-list` is `W`, `LH`, `R` for the whole hazard, the union. A per-location `hazards`
   attribute (#78) read from the codes would say "hail" for a district whose paragraph does not.
   IDN21035 has one paragraph and the same three codes, so for it the two agree.
4. **The summary for the detailed warning loses the part that matters.** Its paragraph is about 420
   characters and the cap is 300, so the cut falls inside "It is forecast to affect Londonderry, Upper
   Colo and Castlereagh by 5:30 pm and Richmond, Windsor and Wilberforce by 5:45 pm."
5. **`parse_product` returns empty `phenomena` and `text` for both products.** `_hazard()` reads each
   `<text>` element's direct text, and in these files the content sits in `<p>` children
   (`<text type="warning_phenomena"><p>HEAVY RAINFALL, …</p></text>`). The flood and marine files it
   was written for have the text directly inside. It also does not read the `phenomenon-list` codes.
6. **Read by neither parser:** the CAP `<instruction>` (the SES advice, also in the `.txt` and in the
   XML `warning_advice`), `urgency` and `certainty` (both `Unknown`), the XML `warning_title`,
   `warning_next_issue`, the per-area `forecast` text and `warning_headline`, the validity window,
   `priority` (`W`), and the three images.
7. **Cancellation blocks ride along.** Each product holds a second block cancelling other districts
   (Illawarra and Southern Tablelands; Wollondilly/Wingecarribee). They do not match Home. The CAP
   `msgType` for the product is `Update` in both cases.
8. **No grade exists in either source.** CAP severity is `Unknown` and the XML severity is `STD`
   (the same code the sheep grazier product carries), so neither product says how severe the storm
   is. The headline, title and `.txt` all say "Severe".
9. **Latency against the detailed warning.** IDN21035 was issued at 17:13:59 AEDT and is refreshed about
   every 30 minutes (next due 17:45). The integration polls every 10 minutes and saw it at 17:18:37, so
   a detailed warning can be up to 10 minutes late out of a 30-minute cycle.
10. **Size.** The XML is 119 KB and 256 KB, of which the images are almost all. Both are under the
    400,000-byte capture limit but far larger than the flood and marine products the XML reader was
    sized for, and the XML adds nothing over the `.txt` and CAP for the text fields above.

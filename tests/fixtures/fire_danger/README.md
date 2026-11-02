# BoM fire danger rating capture

`IDN10016.xml` is an unmodified copy of BoM product IDN10016, "Fire Danger Ratings 4 Days (NSW)",
from `ftp://ftp.bom.gov.au/anon/gen/fwo/IDN10016.xml`, captured 2026-11-02 16:15 AEDT issue over
anonymous FTP. 21 `fire-district` areas keyed by `aac="NSW_FW0nn"`, four forecast periods each, with a
`fire_danger` text (No Rating, Moderate, High, Extreme, Catastrophic) and a `fire_behaviour_index`.
Add captures of other issues and other states' equivalents when seen; never hand-write one.

Other states' equivalents, captured the same way (unmodified, anonymous FTP, `/anon/gen/fwo/`) on
2026-11-02: `IDD10731.xml` (NT, issued 2026-11-02 05:00 +09:30 local), `IDQ13016.xml` (QLD, 2026-11-01
16:00 +10:00), `IDS10070.xml` (SA, 2026-11-01 16:05 +10:30), `IDT13151.xml` (TAS, 2026-11-02 16:00
+11:00), `IDV18555.xml` (VIC, 2026-11-02 16:00 +11:00), `IDW15100.xml` (WA, 2026-11-02 04:35 +08:00).
Same structure as IDN10016. The fake BoM server serves all of them in every scenario.

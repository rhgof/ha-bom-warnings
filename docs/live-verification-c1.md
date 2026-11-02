# Live verification checklist for ticket #13 (not yet done)

Needs a human: onboarding and token creation in the throwaway instance. Not run by the agent.

1. Start the fake server on the empty baseline: `.venv/bin/python -m scripts.fake_bom serve baseline --port 2121`.
   Shapefile zips are not in the repo, so also pass `--spatial-dir <dir of IDM000NN.zip>`, or the
   flow fails with `cannot_connect` / no area.
2. Start the dev instance with `BOM_WARNINGS_FTP_HOST=127.0.0.1:2121` (`scripts/ha-dev.sh`), finish
   onboarding, set the home location to a point inside QLD forecast district `QLD_PW001`
   (the `warning_appears` heatwave covers `QLD_PW001`..`QLD_PW003`).
3. Add the BoM Warnings integration with the home location. Expect `binary_sensor.<name>_warning`
   to be `off`.
4. `.venv/bin/python -m scripts.fake_bom apply warning_appears`, wait up to 10 minutes (or reload
   the entry). Expect `on`, with a `warnings` attribute listing `IDQ21013` (Extreme Heat).
5. Cancel it: `apply baseline` (file removed). Expect `off` after the next poll.
6. Note the result on the pull request.

## Result (2026-11-02, HA 2026.10.4 dev instance, real BoM shapefile layers served by the fake server)

Location `-21.5, 142.0` (in `QLD_PW003`), created through the config flow over REST.

| Step | Fake server | binary sensor | count | most severe |
| --- | --- | --- | --- | --- |
| 1 | `baseline` | off | 0 | none |
| 2 | `warning_appears` (IDQ21013 Extreme Heat) | on, lists Extreme Heat | 1 | Severe heatwave warning for Queensland |
| 3 | `baseline` again (warning removed) | off | 0 | none |
| 4 | server stopped | unavailable (all four entities) | | |

A `new` event fired on the event entity in step 2. The poll interval is 10 minutes, so each step
forced a refresh with `homeassistant.update_entity`. Step 3 removes the warning from the feed
rather than serving a cancel message, because no recorded `Cancel` file covers this district.

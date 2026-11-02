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

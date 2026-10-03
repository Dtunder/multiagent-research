# Hermes integration contract

Install this module on the worker that already owns the Hermes cron/background jobs.

1. Run `install.ps1` from `tools\ai-radar`.
2. Verify `G:\Meine Ablage\Antigravity\AI_Intel\CONFIG\config.yaml` exists.
3. Run one manual `collect` and inspect the generated DAILY/RAW/STATE/LOGS outputs.
4. Register exactly one existing-Hermes scheduler job for this module. Desired cadence: hourly 02:00 through 08:00 Europe/Berlin.
5. Do not edit protected Hermes configuration files directly when a Hermes config/cron command is available.
6. Store API credentials only in the worker's secret/environment mechanism:
   - `GITHUB_TOKEN` optional
   - `HF_TOKEN` optional
   - `YOUTUBE_API_KEY` optional
   - `X_BEARER_TOKEN` optional
7. Keep YouTube/X disabled until their credential exists and a manual smoke test passes.
8. After installation, write a redacted verification record into `G:\Meine Ablage\Antigravity\AI_Intel\LOGS\INSTALL_RESULT.json` containing command exit codes, created paths, enabled sources, and next scheduled run. Never include secrets.

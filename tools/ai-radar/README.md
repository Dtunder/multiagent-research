# AI Radar v1

Nightly, quota-efficient AI intelligence collector for the existing Hermes + Google Drive setup.

## Design

- Reuses `G:\Meine Ablage\Antigravity\AI_Intel` as the canonical output area.
- Runs deterministically first: collect -> normalize -> deduplicate -> score -> write brief.
- LLM work is deferred until after ranking; only high-scoring items are written to `NEEDS_DEEP_ANALYSIS.json`.
- Secrets are read only from environment variables.
- Social HTML scraping is disabled by default. X and YouTube use official APIs when credentials exist.
- Each source fails independently; one broken API does not destroy the nightly run.

## Sources

Credential-free core:
- arXiv RSS
- Hacker News Algolia
- GitHub public API (lower limits without token)
- Hugging Face Hub API
- arbitrary RSS/Atom feeds

Optional:
- YouTube Data API via `YOUTUBE_API_KEY`
- X recent-search API via `X_BEARER_TOKEN`
- GitHub authenticated access via `GITHUB_TOKEN`
- Hugging Face authenticated access via `HF_TOKEN`

Instagram and Reddit are intentionally disabled in v1 until an approved API path is configured.

## Install on worker

```powershell
cd tools\ai-radar
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

The installer creates `.venv`, installs requirements, and copies `config.example.yaml` to the Drive-backed CONFIG folder if a config is not already present. It does **not** create a second scheduler.

## Run

```powershell
.\.venv\Scripts\python.exe .\ai_radar.py nightly --config "G:\Meine Ablage\Antigravity\AI_Intel\CONFIG\config.yaml"
```

`nightly` exits without collecting when local Europe/Berlin time is outside 02:00-08:59. Configure the existing Hermes scheduler to run it hourly at 02:00 through 08:00.

For an immediate manual test:

```powershell
.\.venv\Scripts\python.exe .\ai_radar.py collect --config "G:\Meine Ablage\Antigravity\AI_Intel\CONFIG\config.yaml"
```

## Output

- `DAILY/YYYY-MM-DD_AI_Daily_Briefing.md`
- `RAW/YYYY-MM-DD/<source>.jsonl`
- `STATE/state.json`
- `LOGS/YYYY-MM-DD.jsonl`
- `KNOWLEDGE_BASE/events.jsonl`
- `NEEDS_DEEP_ANALYSIS.json`

The old one-off briefing can remain as historical evidence; new runs go into `DAILY/`.

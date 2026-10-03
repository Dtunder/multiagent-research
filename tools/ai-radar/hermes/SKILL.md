---
name: ai-radar-nightly
description: Run the existing AI_Intel nightly collector on the worker without creating a competing scheduler or memory system.
---

# AI Radar Nightly

## Invariants
- Canonical output root: `G:\Meine Ablage\Antigravity\AI_Intel`.
- Preserve the existing Vault/Memory Bus, Hermes scheduler, Sonu/Jules/AEOS/Codex/AGY routes.
- Do not create another watcher, scheduler, vector DB, or memory store.
- Secrets are local environment variables only; never write tokens to Drive.
- Do not HTML-scrape X, Instagram, YouTube, or Reddit.

## Scheduled run
Execute hourly at 02:00, 03:00, 04:00, 05:00, 06:00, 07:00, and 08:00 Europe/Berlin using the existing Hermes scheduler:

`<repo>\tools\ai-radar\.venv\Scripts\python.exe <repo>\tools\ai-radar\ai_radar.py nightly --config "G:\Meine Ablage\Antigravity\AI_Intel\CONFIG\config.yaml"`

The script itself checks the configured window and is idempotent across repeated runs.

## Quota policy
1. Fetch metadata/public feeds first.
2. Deduplicate before any LLM call.
3. Rank deterministically.
4. Only items in `NEEDS_DEEP_ANALYSIS.json` are eligible for LLM enrichment.
5. Batch high-value items into one enrichment request where possible.
6. If no high-value items changed, do not wake an LLM.

## Success evidence
A run is successful only when:
- the daily briefing exists;
- state was atomically updated;
- at least one per-source status was written to the log;
- source failures are explicitly listed instead of silently discarded.

# pWin AI Opportunities for Claude Code

This folder is the Claude Code adapter for the shared `pwin-ai-opportunities` runtime bundle.

## Mental Model

- the repo root is the shared runtime bundle
- `claude-code/` is the Claude-specific adapter layer
- the supported Claude command surface is limited to `scan`, `show digest`, `feedback`, and `research`
- the shipped runtime is federal-only and currently implemented for `SAM.gov` plus `USAspending.gov`

Do not treat this as a drop-in skill folder, and do not assume separate onboarding flows or extra data adapters exist.

## Recommended Install Model

1. Keep the repo cloned somewhere stable.
2. Set `PWIN_AI_OPPS_ROOT` to the repo root that contains `SKILL.md`, `scripts/`, `templates/`, and `references/`.
3. Copy `claude-code/.claude/commands/*.md` into either:
   - `~/.claude/commands/pwin-ai-opportunities/`
   - a project-local `.claude/commands/` folder
4. Keep this `CLAUDE.md` alongside those commands, or merge its guidance into an existing project `CLAUDE.md`.

## Command Mapping

- `scan` -> `scripts/scan/run_scan.py`
- `show digest` -> `scripts/show/show_digest.py`
- `feedback` -> `scripts/feedback/apply_feedback.py`
- `research` -> `scripts/capture/run_capture_research.py`

The command prompts are wrappers over the shared scripts. Prefer the scripts over recreating workflow logic in prompt text.

## Runtime Boundaries

- scan uses `SAM.gov` search and hydration plus `scripts/scan/usaspending_enrich.py`
- capture uses entry resolution, notice context, attachments, public context, and `scripts/capture/usaspending_enrich.py`
- `fetch_public_context.py` and related capture helpers are internal runtime support, not a separate user-facing mode

The two USAspending helpers remain separate because scan and capture use different depth and query strategies.

## Operating Rules

- Resolve `PWIN_AI_OPPS_ROOT` before running commands. If it cannot be resolved, ask for it instead of guessing.
- Read the JSON stdout from the orchestrator first, then read the artifact path it returns.
- Answer from the returned digest or capture brief, not from improvised summary text.
- Do not promise onboarding artifacts, `MEMORY.md`, `near-misses`, or `validate-artifacts` behavior unless the shared runtime starts shipping them.

## What Claude Can Ignore

- `manifest.json`
- `agents/openai.yaml`
- host metadata that exists only for OpenClaw or Codex discovery

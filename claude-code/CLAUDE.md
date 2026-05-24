# pWin AI Opportunities for Claude Code

This folder is a Claude Code adapter for the shared `pwin-ai-opportunities` bundle.

## Mental model

- The repo root is the shared script and template bundle.
- `claude-code/` is the Claude-specific adapter layer.
- Claude should treat this as a command pack plus project memory, not as a drop-in skill folder.

## Recommended install model

1. Keep the repo cloned somewhere stable.
2. Set `PWIN_AI_OPPS_ROOT` to the repo root that contains `SKILL.md`, `scripts/`, `templates/`, `references/`, and `examples/`.
3. Copy `claude-code/.claude/commands/*.md` into either:
   - `~/.claude/commands/pwin-ai-opportunities/`, or
   - a project-local `.claude/commands/` folder
4. Keep this `CLAUDE.md` alongside those commands or merge its guidance into an existing project `CLAUDE.md`.

## Claude-specific rules

- Prefer the shared Python scripts under `PWIN_AI_OPPS_ROOT/scripts/`.
- Do not rebuild scan or capture logic in prompt text when a script already exists.
- Read the JSON stdout from the orchestrator, then read the artifact path it returns.
- If `PWIN_AI_OPPS_ROOT` is not set, resolve it before running commands. If it cannot be resolved, ask for the path instead of guessing.

## Shared command surface

- `scan` -> `scripts/scan/run_scan.py`
- `show digest` -> `scripts/show/show_digest.py`
- `feedback` -> `scripts/feedback/apply_feedback.py`
- `research` -> `scripts/capture/run_capture_research.py`

## What Claude can ignore

- `manifest.json`
- `agents/openai.yaml`
- host-specific metadata that exists only to improve OpenClaw or Codex discovery

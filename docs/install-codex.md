# Codex Cheat Sheet

- Install path: copy the repo root to `~/.codex/skills/pwin-ai-opportunities/`.
- Files that matter: `SKILL.md`, `agents/openai.yaml`, `scripts/`, `templates/`, `references/`, `examples/`.
- Files they can ignore: `manifest.json`, Claude-specific files.
- User mental model: `this repo is a skill folder with a little extra metadata`.
- Friction level: low.
- Verdict: clear path, as long as the shared `SKILL.md` stays host-neutral.

## Install

1. Clone or copy the repo root into:
   `~/.codex/skills/pwin-ai-opportunities/`
2. Restart Codex or refresh skill discovery if needed.
3. Ensure runtime credentials are available:
   - `SAM_API_KEY`
   - the model credentials your Codex install already expects

## What Codex uses

- `SKILL.md` drives skill triggering and workflow rules.
- `agents/openai.yaml` gives Codex the display metadata.
- `scripts/`, `templates/`, `references/`, and `examples/` are the shared bundle.

## Direct script examples

Scan:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

Show latest digest:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/show/show_digest.py" --workspace "$PWD" --date latest
```

Capture research:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

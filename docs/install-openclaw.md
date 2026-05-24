# OpenClaw Cheat Sheet

- Install path: copy the repo root to `~/.openclaw/skills/pwin-ai-opportunities/`.
- Files that matter: `SKILL.md`, `manifest.json`, `scripts/`, `templates/`, `references/`, `examples/`.
- Files they can ignore: Claude-specific files, Codex UI metadata.
- User mental model: `this repo is a skill folder`.
- Friction level: low.
- Verdict: clear path.

## Install

1. Clone or copy the repo root into:
   `~/.openclaw/skills/pwin-ai-opportunities/`
2. Ensure runtime credentials are available:
   - `SAM_API_KEY`
   - the LLM credentials your OpenClaw install already expects
3. Use any normal OpenClaw workspace as the `--workspace` target.
4. Optional, but useful if you want one shared command surface across hosts:
   `export PWIN_AI_OPPS_ROOT="$HOME/.openclaw/skills/pwin-ai-opportunities"`

## Direct script examples

Scan:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

Show latest digest:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/show/show_digest.py" --workspace "$PWD" --date latest
```

Apply feedback:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "like A1"
```

Capture research:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

Bootstrap a workspace from a company site:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/bootstrap/bootstrap_workspace.py" --workspace "$PWD" --company-url "https://example.com" --naics "541511,541512"
```

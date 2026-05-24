# Claude Code Cheat Sheet

- Install path: not a drop-in skill folder.
- Recommended usage: keep the repo cloned, then copy the Claude adapter into a project or install user-level commands under `~/.claude/commands/`.
- Files that matter: `claude-code/CLAUDE.md`, `claude-code/.claude/commands/*.md`, plus a reliable path to the shared `scripts/` bundle.
- Files they can ignore: `manifest.json`, `agents/openai.yaml`.
- User mental model: `this is a command pack plus project memory`, not `this is a skill folder`.
- Friction level: medium.
- Verdict: workable, but only really clean because the Claude adapter is separated from the repo root.

## Recommended install

1. Clone the repo somewhere stable, for example:
   `~/src/pwin-ai-opportunities`
2. Export the shared bundle root:

```bash
export PWIN_AI_OPPS_ROOT="$HOME/src/pwin-ai-opportunities"
```

3. Copy the command pack:
   - user-level: `~/.claude/commands/pwin-ai-opportunities/`
   - project-level: `<project>/.claude/commands/`
4. Copy or merge `claude-code/CLAUDE.md` into the project context where Claude Code will read it.

## Shared command pack

- `pwin-bootstrap.md`
- `pwin-scan.md`
- `pwin-show-digest.md`
- `pwin-feedback.md`
- `pwin-research.md`

These commands assume the shared scripts still live under `PWIN_AI_OPPS_ROOT`.

## Why this is not a drop-in skill folder

OpenClaw and Codex both want the repo root to behave like the installed skill itself. Claude Code works better when its project memory and reusable command prompts are separated from the underlying script bundle. This repo keeps that separation by placing the Claude adapter under `claude-code/`.

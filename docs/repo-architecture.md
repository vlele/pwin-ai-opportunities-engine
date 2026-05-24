# Repository Architecture

## Goal

Use one shared source repo for:

- OpenClaw
- Codex
- Claude Code

without forcing all three tools into the same mental model.

## Design Choice

OpenClaw and Codex both want a package-shaped repo root.
Claude Code wants a project adapter.

This repo therefore uses:

- a shared package root for scripts, templates, references, examples, and shared skill instructions
- a Claude-specific adapter isolated under `claude-code/`

## Layout

```text
pwin-ai-opportunities/
|- SKILL.md
|- manifest.json
|- SECURITY.md
|- TRUST.md
|- agents/
|  `- openai.yaml
|- scripts/
|- templates/
|- references/
|- examples/
|- claude-code/
|  |- CLAUDE.md
|  `- .claude/
|     `- commands/
`- docs/
   |- install-openclaw.md
   |- install-codex.md
   |- install-claude-code.md
   `- repo-architecture.md
```

## Shared Root Responsibilities

- `SKILL.md`
  Shared workflow contract for scan, show digest, feedback, and capture research.
- `manifest.json`
  OpenClaw-oriented bundle metadata that does not interfere with Codex.
- `agents/openai.yaml`
  Codex-facing display metadata.
- `scripts/`
  Deterministic execution layer shared by every host.
- `templates/`
  Shipped render templates and JSON templates used by the current runtime.
- `references/`
  Deeper playbooks and source guidance for the shipped modes.
- `examples/`
  Retained behavioral anchors for scan and capture outputs.

## Claude Adapter Responsibilities

- `claude-code/CLAUDE.md`
  Claude-specific project memory and usage framing.
- `claude-code/.claude/commands/`
  Prompt-command pack that points Claude back to the shared scripts.

## Install Mental Models

- OpenClaw: the repo root is the skill folder.
- Codex: the repo root is the skill folder plus a small amount of UI metadata.
- Claude Code: the repo root is the shared bundle, and `claude-code/` is the adapter you copy into Claude's command surface.

## Guardrail

Keep `SKILL.md` neutral.

Do not hardcode:

- an OpenClaw-only install path
- slash-command-only usage language
- Claude-specific project assumptions

Host-specific installation and ergonomics should live in:

- `docs/`
- `agents/openai.yaml`
- `claude-code/`

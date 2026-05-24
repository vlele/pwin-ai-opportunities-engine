# Repository Architecture

## Goal

Keep one shared repo for `OpenClaw`, `Codex`, and `Claude Code` while shipping one runtime contract.

The current shipped contract is intentionally narrow:

- federal-only opportunity work
- `scan`
- `show digest`
- `feedback`
- `capture research`
- `SAM.gov` plus `USAspending.gov`

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
|  |- common/
|  |- scan/
|  |- show/
|  |- feedback/
|  |- capture/
|  `- tests/
|- templates/
|- references/
|- examples/
|- claude-code/
|  |- CLAUDE.md
|  `- .claude/
|     `- commands/
`- docs/
```

## Shared Runtime

- `scripts/scan/`
  Federal scan orchestration, SAM search and hydration, shortlist scoring, digest-entry map generation, digest rendering, and scan-time `USAspending.gov` enrichment.
- `scripts/show/`
  Reads the current or dated digest artifacts without rerunning scan logic.
- `scripts/feedback/`
  Logs user feedback and applies learned preference updates to runtime state.
- `scripts/capture/`
  Runs capture research from a stable entry ID or canonical ID, then uses internal helpers for notice context, attachments, public context, evidence rendering, validation, and capture-time `USAspending.gov` enrichment.
- `scripts/common/`
  Shared path, JSON, JSONL, source-registry, and validation utilities used across the shipped modes.

Other folders may exist under `scripts/`, but the supported host-facing command surface is limited to the four modes above.

## Host Adapters

- `SKILL.md`
  Shared host-neutral workflow contract used by skill-style hosts.
- `manifest.json`
  OpenClaw metadata for shipped artifacts and bundle identity.
- `agents/openai.yaml`
  Codex metadata for discovery and display.
- `claude-code/CLAUDE.md`
  Claude-specific guidance for running the shared bundle.
- `claude-code/.claude/commands/`
  Thin Claude command wrappers that resolve `PWIN_AI_OPPS_ROOT` and call the shared scripts.

## Source Scope

The shipped runtime currently implements two live source families:

- `SAM.gov` for federal opportunity retrieval and notice hydration
- `USAspending.gov` for award-history enrichment

The USAspending split is deliberate today:

- `scripts/scan/usaspending_enrich.py` supports scan-time shortlist enrichment
- `scripts/capture/usaspending_enrich.py` supports deeper capture-time research

Not part of the shipped source contract:

- state or local opportunity sources
- grants sources
- commercial enrichment portals
- placeholder adapters from older drafts

## Supporting Content

- `templates/`
  Shipped templates used by the runtime today.
- `references/`
  Playbooks and source notes that should match the current script behavior.
- `examples/`
  Behavioral anchors and artifact examples, not required runtime inputs.

## Guardrails

- Keep `SKILL.md` host-neutral.
- Keep host-specific install ergonomics in `docs/`, `agents/openai.yaml`, and `claude-code/`.
- Do not promise onboarding flows, `near-misses`, `validate-artifacts`, or `MEMORY.md` unless the shipped scripts actually require them.

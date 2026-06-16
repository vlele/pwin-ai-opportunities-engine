# Agent Skills Audit

Audit date: 2026-06-16

This note records the cross-walk for `pwin-ai-opportunities` against the Agent Skills specification and skill-authoring best practices.

## Frontmatter

- `name` is `pwin-ai-opportunities`, uses lowercase letters and hyphens, and is under the 64-character local validator limit.
- `description` is under the 1024-character spec limit, avoids angle brackets, and names the intended trigger surface: bootstrap/onboarding, federal scans, stable-ID digest lookup, feedback logging, and capture research.
- The install directory expectation remains `pwin-ai-opportunities`, matching the skill name. The GitHub repository checkout is named `pwin-ai-opportunities-engine`; that mismatch is acceptable for source development, but installed skill folders should use `pwin-ai-opportunities`.
- Optional frontmatter fields are intentionally not added:
  - `license`: repository licensing can stay outside `SKILL.md` unless a client requires inline license metadata.
  - `compatibility`: compatibility details differ across OpenClaw, Codex, and Claude Code and are documented in host install docs instead.
  - `metadata`: Codex-facing display metadata already lives in `agents/openai.yaml`.
  - `allowed-tools`: the shared skill invokes local scripts and should not narrow host tool policy in portable frontmatter.

## Progressive Disclosure

- `SKILL.md` stays below the 500-line guidance and keeps the operational mode routing in one place.
- Every `references/*.md` file is linked from `SKILL.md` with an explicit "read when" trigger.
- `references/govtribe-mcp-tool-guide.md` is called out only for GovTribe MCP enablement, commercial-intelligence enrichment, or GovTribe tool-call construction.
- Examples are grouped by active task type: bootstrap command shape, scan/digest output shape, capture output shape, user-facing capture response shape, and anti-patterns.
- `templates/` remains a runtime-template directory, not `assets/`. The shipped scripts consume these files directly; moving them to `assets/` would weaken the current script contract. This is an intentional layout decision, not a spec exception.

## Trigger Evaluation

The deterministic trigger set lives in `scripts/tests/fixtures/skill-trigger-eval.json`.

Positive trigger coverage:

- bootstrap/onboarding
- scan
- digest lookup
- feedback logging
- capture research

Negative near-miss coverage:

- generic procurement questions
- state/local opportunity scans
- grant searches
- manual report editing or presentation conversion
- credential setup
- unrelated federal research

`scripts/tests/run_skill_contract_tests.py` validates the fixture schema and category coverage. It does not run a live classifier because trigger behavior depends on the host client and installed skill state.

## Client Assumptions

- OpenClaw installs the repo contents into `~/.openclaw/skills/pwin-ai-opportunities/` and reads `SKILL.md` plus `manifest.json`.
- Codex installs the repo contents into `~/.codex/skills/pwin-ai-opportunities/` and reads `SKILL.md` plus `agents/openai.yaml`.
- Claude Code uses `claude-code/` as a command-pack adapter and resolves the shared runtime through `PWIN_AI_OPPS_ROOT`.
- Live trigger checks are optional acceptance evidence. Run them only in an installed client environment with the right credentials and workspace isolation.

## Validation

Required local checks:

```bash
python3 /Users/jhariani/.codex/skills/.system/skill-creator/scripts/quick_validate.py .
python3 scripts/tests/run_skill_contract_tests.py
python3 scripts/tests/run_bootstrap_tests.py
python3 scripts/tests/run_commercial_intel_tests.py
python3 scripts/tests/run_gold_bucket_tests.py
python3 scripts/tests/run_intel_provider_tests.py
python3 scripts/tests/run_openai_reasoning_tests.py
python3 scripts/tests/run_scan_bootstrap_guidance_tests.py
python3 scripts/tests/run_source_policy_tests.py
git diff --check
```

Optional external check:

```bash
skills-ref validate .
```

`skills-ref` was not installed on PATH during this audit. When it is available, run `skills-ref validate .` and record any intentional exceptions in this file.

# OpenClaw Install Notes

Install the repo root at:

`~/.openclaw/skills/pwin-ai-opportunities/`

OpenClaw reads this bundle through:

- `SKILL.md` for workflow behavior
- `manifest.json` for bundle metadata and required artifacts

Everything under `scripts/`, `templates/`, `references/`, and `examples/` is shared content, not an OpenClaw-only fork.

## Minimum Requirements

- Python 3 available as `python3`
- `SAM_API_KEY` exported in the shell that will run the scripts
- the LLM credentials your OpenClaw install already uses
- a workspace folder where the runtime can read and write `procurement/` artifacts

Current shipped scope:

- `bootstrap / onboarding`
- federal-only opportunity work
- `scan`
- `show digest`
- `feedback`
- `capture research`

Do not assume extra federal data adapters or `near-misses` are part of the shipped OpenClaw contract.

## Shared Runtime Shape

- `scripts/bootstrap/bootstrap_workspace.py`
  Seeds starter workspace files from a company URL and optional NAICS, and populates or merges `procurement/vendor-profile.json` plus `procurement/preferences.json`.
- `scripts/scan/run_scan.py`
  Runs the federal opportunity scan, writes the dated opportunity set, explanations, digest-entry map, report, and digest.
- `scripts/show/show_digest.py`
  Reads the latest or a dated digest.
- `scripts/feedback/apply_feedback.py`
  Logs feedback and updates preferences.
- `scripts/capture/run_capture_research.py`
  Resolves an entry, loads notice context, gathers attachments and public context, runs capture-time USAspending enrichment, and renders a validated capture brief.

Implemented shipped data sources today:

- `SAM.gov` for live federal opportunities
- `USAspending.gov` for award-history enrichment

The scan and capture paths each keep their own USAspending helper module because they serve different levels of depth.

## Install

1. Clone or copy the repo root into `~/.openclaw/skills/pwin-ai-opportunities/`.
2. Export `SAM_API_KEY` in the environment where OpenClaw will run commands.
3. Use any normal OpenClaw project folder as `--workspace`; the workspace is where `procurement/` artifacts live.
4. Optional, but useful if you want one shared command surface across hosts:

```bash
export PWIN_AI_OPPS_ROOT="$HOME/.openclaw/skills/pwin-ai-opportunities"
```

## OpenClaw Prompt Examples

Bootstrap a workspace from a company site:

```text
Use pwin-ai-opportunities and bootstrap this workspace from https://example.com.
```

Bootstrap with confirmed NAICS:

```text
Use pwin-ai-opportunities and bootstrap this workspace from https://example.com
with confirmed NAICS 541511 and 541512.
```

Bootstrap behavior to expect:

- `procurement/vendor-profile.json` is created or updated, not left empty
- confirmed NAICS you provide land in `naics.confirmed`
- tentative or inferred NAICS land in `naics.candidates`
- inferred competencies, keyword tags, buyer notes, provenance, and a starter fit narrative are added
- website-derived facts are marked provisional until you confirm them
- `procurement/preferences.json` excludes `grants` by default and seeds positive keywords from the inferred capabilities

Run the first scan:

```text
Use pwin-ai-opportunities and run a federal opportunity scan for the next 30 to 45 days in this workspace.
```

Show the digest:

```text
Use pwin-ai-opportunities and show the latest digest.
```

Give feedback:

```text
never show grants
like A1
```

Run capture research:

```text
Use pwin-ai-opportunities and research A1 with full capture depth.
```

## Direct Script Examples

These are useful for debugging or CI. In normal OpenClaw use, prefer the chat prompts above.

Bootstrap a workspace from a company site:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/bootstrap/bootstrap_workspace.py" --workspace "$PWD" --company-url "https://example.com" --naics "541511,541512"
```

Run a scan:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

Show the latest digest:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/show/show_digest.py" --workspace "$PWD" --date latest
```

Apply feedback:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "never show grants"
```

Run capture research:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

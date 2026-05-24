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

- federal-only opportunity work
- `scan`
- `show digest`
- `feedback`
- `capture research`

Do not assume onboarding flows, extra federal data adapters, `near-misses`, or `MEMORY.md` are part of the shipped OpenClaw contract.

## Shared Runtime Shape

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

## Direct Script Examples

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
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "hide E1"
```

Run capture research:

```bash
python3 "$HOME/.openclaw/skills/pwin-ai-opportunities/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

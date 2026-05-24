# Codex Install Notes

Install the repo root at:

`~/.codex/skills/pwin-ai-opportunities/`

Codex reads this bundle as a skill folder with two host-facing files:

- `SKILL.md` for triggering and workflow rules
- `agents/openai.yaml` for Codex display metadata

Everything else is shared runtime content used by all hosts.

## Minimum Requirements

- Python 3 available as `python3`
- `SAM_API_KEY` exported in the shell that will run the scripts
- the LLM credentials your Codex install already uses
- a workspace folder where the runtime can read and write `procurement/` artifacts

This bundle currently ships a federal-only workflow:

- `bootstrap / onboarding`
- `scan`
- `show digest`
- `feedback`
- `capture research`

Do not assume extra source adapters are part of the Codex contract.

## Shared Runtime Shape

- `scripts/bootstrap/bootstrap_workspace.py`
  Seeds starter workspace files from a company URL and optional NAICS.
- `scripts/scan/run_scan.py`
  Federal scan orchestrator. Uses `SAM.gov` search and hydration plus `scripts/scan/usaspending_enrich.py` for award-history enrichment.
- `scripts/show/show_digest.py`
  Reads a dated or latest digest.
- `scripts/feedback/apply_feedback.py`
  Logs feedback events and updates learned preferences.
- `scripts/capture/run_capture_research.py`
  Capture orchestrator. Uses internal helpers such as `resolve_entry.py`, `fetch_notice_context.py`, `fetch_notice_attachments.py`, `fetch_public_context.py`, and `scripts/capture/usaspending_enrich.py`.

The two USAspending modules are intentionally separate today:

- scan-time USAspending narrows to shortlist-friendly award context
- capture-time USAspending goes deeper for decision-grade research

## Install

1. Clone or copy the repo root into `~/.codex/skills/pwin-ai-opportunities/`.
2. Restart Codex or refresh skill discovery if needed.
3. Export `SAM_API_KEY` in the environment where Codex will run commands.
4. Use a normal project folder as `--workspace`; the skill root and workspace are separate paths.
5. Optional, but useful if you want one shared command surface across hosts:

```bash
export PWIN_AI_OPPS_ROOT="$HOME/.codex/skills/pwin-ai-opportunities"
```

## Direct Script Examples

Bootstrap a workspace from a company site:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/bootstrap/bootstrap_workspace.py" --workspace "$PWD" --company-url "https://example.com" --naics "541511,541512"
```

Run a scan:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

Show the latest digest:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/show/show_digest.py" --workspace "$PWD" --date latest
```

Apply feedback:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "like A1"
```

Run capture research:

```bash
python3 "$HOME/.codex/skills/pwin-ai-opportunities/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

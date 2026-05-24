# Claude Code Install Notes

Claude Code uses this repo as a shared script bundle plus a Claude-specific adapter.

It is not a drop-in skill folder.

## What Claude Uses

- `claude-code/CLAUDE.md`
  Claude-specific operating guidance
- `claude-code/.claude/commands/*.md`
  Thin command prompts that resolve `PWIN_AI_OPPS_ROOT` and call the shared Python scripts
- the shared repo root referenced by `PWIN_AI_OPPS_ROOT`

Claude does not need `manifest.json` or `agents/openai.yaml`.

## Minimum Requirements

- Python 3 available as `python3`
- `SAM_API_KEY` exported in the shell that will run the scripts
- the LLM credentials your Claude Code install already uses
- a stable checkout path for this repo
- a workspace folder where the runtime can read and write `procurement/` artifacts

Current shipped scope:

- `bootstrap / onboarding`
- federal-only opportunity work
- `scan`
- `show digest`
- `feedback`
- `capture research`

Do not assume extra data-source adapters are part of the Claude adapter contract.

## Recommended Install

1. Clone the repo somewhere stable, for example `~/src/pwin-ai-opportunities`.
2. Export the shared bundle root:

```bash
export PWIN_AI_OPPS_ROOT="$HOME/src/pwin-ai-opportunities"
```

3. Copy the command pack into either:
   - `~/.claude/commands/pwin-ai-opportunities/`
   - `<project>/.claude/commands/`
4. Copy `claude-code/CLAUDE.md` into the Claude project context, or merge its guidance into an existing project `CLAUDE.md`.

## Shared Command Pack

- `pwin-bootstrap.md` -> `scripts/bootstrap/bootstrap_workspace.py`
- `pwin-scan.md` -> `scripts/scan/run_scan.py`
- `pwin-show-digest.md` -> `scripts/show/show_digest.py`
- `pwin-feedback.md` -> `scripts/feedback/apply_feedback.py`
- `pwin-research.md` -> `scripts/capture/run_capture_research.py`

These commands are wrappers over the shared runtime. They should not recreate scan or capture logic in prompt text.

## Runtime Notes

- scan-time USAspending lives in `scripts/scan/usaspending_enrich.py` and supports shortlist enrichment
- capture-time USAspending lives in `scripts/capture/usaspending_enrich.py` and supports deeper capture research
- capture also depends on internal helpers such as `fetch_notice_context.py`, `fetch_notice_attachments.py`, and `fetch_public_context.py`

## Direct Script Examples

Bootstrap a workspace from a company site:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/bootstrap/bootstrap_workspace.py" --workspace "$PWD" --company-url "https://example.com" --naics "541511,541512"
```

Run a scan:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

Show the latest digest:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/show/show_digest.py" --workspace "$PWD" --date latest
```

Apply feedback:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "prefer subcontracting over prime"
```

Run capture research:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

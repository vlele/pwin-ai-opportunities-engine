# Validation and Recovery

This bundle does not ship a standalone `validate-artifacts` command or a manifest-driven auto-recovery layer.

## Current validation surface

- `scripts/scan/run_scan.py`
  Produces the dated scan artifacts and returns JSON with status, paths, source statuses, and stable-entry counts.
- `scripts/show/show_digest.py`
  Validates a rendered digest with `validate_digest_text` and returns the digest path plus any available digest-entry-map path.
- `scripts/feedback/apply_feedback.py`
  Resolves feedback against the latest digest-entry map, appends the feedback ledger, and recomputes learned preferences.
- `scripts/capture/run_capture_research.py`
  Validates the rendered capture brief with `validate_capture_brief_text` and returns request-scoped brief and evidence paths.

## Scan artifacts the shipped workflow actually maintains

For a successful dated scan run, the current code writes:

- `procurement/opportunities/YYYY-MM-DD.json`
- `procurement/explanations/YYYY-MM-DD.json`
- `procurement/digest-entry-map/YYYY-MM-DD.json`
- `procurement/reports/YYYY-MM-DD.md`
- `procurement/digests/YYYY-MM-DD.md`

Not part of the shipped contract:

- `procurement/near-misses/YYYY-MM-DD.md`
- `validate-artifacts {date}`
- manifest-level `autoRecover`

## Recovery guidance

Use reruns of the shipped scripts, not an external recovery command.

### If scan outputs are missing or stale

- Missing `opportunities` or `explanations`: rerun `scripts/scan/run_scan.py`
- Missing `digest-entry-map`, `report`, or `digest`: rerun `scripts/scan/run_scan.py`
- Missing or empty digest validation from `show_digest.py`: rerun `scripts/scan/run_scan.py`

### If feedback artifacts are missing

- Missing `procurement/feedback-events.jsonl`: rerun `scripts/feedback/apply_feedback.py` with the original user utterance
- Missing learned preference updates in `preferences.json`: rerun `scripts/feedback/apply_feedback.py`

### If capture artifacts are missing

- Missing `procurement/capture-requests.jsonl` entry: rerun `scripts/capture/run_capture_research.py`
- Missing request-scoped brief or evidence file: rerun `scripts/capture/run_capture_research.py`
- Capture brief still contains placeholders or missing required headings: treat the run as failed and rerun capture after fixing the upstream issue

## Manual inspection checklist

When a run looks wrong, check:

1. The JSON stdout returned by the script you ran
2. The dated artifact paths returned in that JSON
3. `procurement/source-registry.json` for the active source set
4. `procurement/preferences.json` for current timing and learning settings
5. `procurement/digest-entry-map/YYYY-MM-DD.json` before applying feedback or capture research

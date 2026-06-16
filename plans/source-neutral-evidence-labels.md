# Source-Neutral Scan Evidence Labels Implementation Plan

## Summary

Fix issue #21 in PR #35 by making scan evidence metadata come from each
retrieved record instead of always inventing a SAM.gov evidence source.
GovTribe-retrieved scan records should keep
`govtribe_mcp_commercial_intel` / `GovTribe MCP Commercial Intelligence` in
merged evidence and use source-neutral evidence wording such as
`Opportunity record set-aside`.

## Implementation Notes

- Update `scripts/common/evidence_model.py::build_scan_official_evidence_model`
  to derive `source_id` and `source_name` from `record["source_id"]` and
  `record["source_name"]`.
- Keep the existing SAM default only when a record has no source metadata, so
  current SAM scan behavior remains compatible.
- Replace hard-coded scan evidence strings like `SAM record set-aside`,
  `SAM notice text`, and `SAM record estimated value` with source-neutral
  wording: `Opportunity record set-aside`, `Opportunity text suggests...`, and
  `Opportunity record estimated value`.
- Pass the resolved source metadata into `_recompete_clues_from_text` so
  recompete signals no longer claim SAM for GovTribe records.
- Do not change capture evidence behavior; `build_capture_official_evidence_model`
  can keep `Official solicitation package` because issue #21 is only about scan
  retrieval records.
- Commit this plan artifact together with the implementation and regression
  coverage so PR #35 is the actual fix, not a plan-only PR.

## Test Commands

```bash
python3 scripts/tests/run_scan_bootstrap_guidance_tests.py
python3 scripts/tests/run_commercial_intel_tests.py
python3 -m compileall scripts
git diff --check
```

## Acceptance Criteria

- GovTribe scan opportunities keep `govtribe_mcp_commercial_intel` in
  `cross_source_evidence.source_ids`.
- GovTribe scan opportunities keep `GovTribe MCP Commercial Intelligence` in
  `cross_source_evidence.source_names`.
- GovTribe scan evidence strings do not include `SAM record` or `SAM notice`.
- Set-aside evidence uses `Opportunity record set-aside`.
- No persisted schema, CLI contract, or public API changes are required.
- PR #35 is updated to describe the implementation and can close issue #21 on
  merge.

## References

- Issue: https://github.com/vlele/pwin-ai-opportunities-engine/issues/21

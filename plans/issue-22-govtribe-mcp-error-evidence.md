# Issue 22: GovTribe MCP Error Payloads Are Not Evidence

## Summary

Fix GovTribe MCP commercial intelligence parsing so provider/tool errors are reported as source issues or warnings, not normalized into opportunity evidence.

## Implementation

- Detect explicit MCP/tool error payloads before record flattening, including `isError: true`, JSON-RPC-style `error`, structured `errors`, failed statuses, and known operator-error text.
- Stop wrapping non-JSON text tool content as `{"summary": text}` because summary-only error text can otherwise become a matched record.
- Return extracted records and extraction errors separately from the GovTribe MCP parser.
- Propagate extraction errors through scan enrichment, capture enrichment, and scan retrieval:
  - error-only responses return `status: error`, `matched: false`, empty enrichment, and notes with the tool error.
  - mixed capture responses keep valid records but return `partial_error` with the tool error in notes.
  - scan retrieval returns no records for error-only responses.

## Verification

- Extend `scripts/tests/run_intel_provider_tests.py` with structured error, text error, and mixed capture fake clients.
- Confirm error-only payloads do not populate summaries, related procurements, source logs, or scan retrieval records.
- Run:
  - `python3 scripts/tests/run_intel_provider_tests.py`
  - `python3 scripts/tests/run_commercial_intel_tests.py`

## PR Workflow

- Branch: `codex/issue-22-govtribe-mcp-error-evidence`
- Commit: `Fix GovTribe MCP error payload normalization`
- Draft PR title: `Fix GovTribe MCP error payload normalization`
- PR body should reference `Fixes #22` and include the completed test commands.

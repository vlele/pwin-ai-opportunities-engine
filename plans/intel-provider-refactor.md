# Intel Provider Refactor Plan

## Summary

Refactor source collection into a dedicated `scripts/intel/` provider layer with two clear procurement-intel paths:

- official SAM.gov opportunity retrieval and noticedesc hydration
- direct GovTribe MCP enrichment using `GOVTRIBE_MCP_API_KEY`

Keep `OPENAI_API_KEY` only for optional semantic reasoning in `scripts/common/openai_reasoning.py`.

## Implementation Notes

- Add `scripts/intel/providers/sam_gov.py` as the SAM.gov provider and leave compatibility wrappers in `scripts/scan/sam_search.py` and `scripts/scan/sam_hydrate.py`.
- Add `scripts/intel/mcp_http.py` as a standard-library MCP Streamable HTTP client for GovTribe. It supports `initialize`, `notifications/initialized`, `tools/list`, `tools/call`, JSON responses, SSE responses, session IDs, and `MCP-Protocol-Version`.
- Add `scripts/intel/providers/govtribe_mcp.py` as the direct GovTribe provider. It discovers tool families from tool metadata and schemas, calls opportunity search first by solicitation number, and normalizes GovTribe records into the existing evidence model.
- Add `scripts/intel/providers/govwin_iq.py` as the existing configured-placeholder provider.
- Move commercial-intel orchestration to `scripts/intel/commercial.py` and keep `scripts/common/commercial_intel.py` as a compatibility facade.
- Preserve the existing env names: `SAM_API_KEY`, `GOVTRIBE_MCP_API_KEY`, `GOVTRIBE_MCP_URL`, `GOVTRIBE_MCP_TIMEOUT_SECONDS`, and `OPENAI_API_KEY` for semantic reasoning only.
- Never print or log token values, authorization headers, or token fragments.

## Test Commands

```bash
python3 "${CODEX_HOME:-$HOME/.codex}/skills/.system/skill-creator/scripts/quick_validate.py" .
python3 scripts/tests/run_bootstrap_tests.py
python3 scripts/tests/run_source_policy_tests.py
python3 scripts/tests/run_commercial_intel_tests.py
python3 scripts/tests/run_scan_bootstrap_guidance_tests.py
python3 scripts/tests/run_gold_bucket_tests.py
python3 scripts/tests/run_intel_provider_tests.py
```

Optional live validation should list GovTribe MCP tools only. It should print status, tool count, and tool names, never secrets.

## References

- Issue: https://github.com/vlele/pwin-ai-opportunities-engine/issues/7
- GovTribe MCP developer guide: https://govtribe.com/docs/govtribe-user-guide/govtribe-mcp/govtribe-mcp-for-developers/
- MCP Streamable HTTP transport: https://modelcontextprotocol.io/specification/2025-06-18/basic/transports
- MCP lifecycle: https://modelcontextprotocol.io/specification/2025-06-18/basic/lifecycle
- MCP tools protocol: https://modelcontextprotocol.io/specification/2025-06-18/server/tools

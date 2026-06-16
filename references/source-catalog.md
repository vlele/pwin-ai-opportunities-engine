# Source Catalog

This bundle is federal-only, and the shipped runtime contract currently implements:

- `SAM.gov` for live contract opportunity retrieval
- `USAspending.gov` for award-history enrichment
- optional commercial-intelligence sidecars for `GovTribe MCP` and `GovWin IQ`

If an older workspace still contains additional source IDs in `procurement/source-registry.json`, treat them as stale configuration until the runtime registry is refreshed from the current template.

## Shipped sources

### 1. SAM.gov Contract Opportunities

- Type: federal procurement notices
- Shipped use: primary scan-time source for live contract opportunities
- Access pattern: official authenticated public API
- Trust tier: 1
- Portal: https://sam.gov/content/opportunities
- API docs: https://open.gsa.gov/api/get-opportunities-public-api/
- Runtime implementation:
  - `scripts/intel/providers/sam_gov.py`
  - compatibility wrappers: `scripts/scan/sam_search.py`, `scripts/scan/sam_hydrate.py`
- Required secret: `SAM_API_KEY`

Current retrieval rules:

- Use `ncode=` for NAICS filtering on the v2 search API.
- Use the official noticedesc endpoint for full notice text.
- Never log `SAM_API_KEY`.
- Treat missing full notice text as reduced-confidence enrichment, not a hidden success.

### 2. USAspending.gov Award History

- Type: federal award-history enrichment
- Shipped use:
  - scan-time award-history enrichment
  - capture-time spending context enrichment
- Access pattern: official public JSON API
- Trust tier: 1
- Portal: https://www.usaspending.gov/
- API docs: https://api.usaspending.gov/docs/endpoints
- Runtime implementation:
  - `scripts/scan/usaspending_enrich.py`
  - `scripts/capture/usaspending_enrich.py`

Current retrieval rules:

- Use documented JSON `POST` requests.
- Treat USAspending as enrichment, not as a replacement for live SAM opportunity retrieval.

### 3. GovTribe MCP Commercial Intelligence

- Type: subscription commercial-intelligence enrichment
- Shipped use:
  - optional scan-time commercial sidecar
  - optional capture-time commercial sidecar
- Access pattern: direct remote MCP over Streamable HTTP
- Trust tier: 4
- Portal: https://govtribe.com/mcp
- API docs: https://govtribe.com/docs/govtribe-user-guide/govtribe-mcp/govtribe-mcp-for-developers/
- Runtime implementation:
  - `scripts/intel/mcp_http.py`
  - `scripts/intel/providers/govtribe_mcp.py`
  - compatibility wrapper: `scripts/common/commercial_intel.py`
- Required secret: `GOVTRIBE_MCP_API_KEY`

Current retrieval rules:

- Treat GovTribe as optional enrichment, not as a replacement for official `SAM.gov` notice retrieval.
- Use direct MCP `initialize`, `notifications/initialized`, `tools/list`, and `tools/call` requests.
- Discover opportunity, award, vehicle, and government-file tools from tool metadata, descriptions, and schemas.
- Use `GOVTRIBE_MCP_URL` only to override the default remote endpoint.
- Default the GovTribe MCP timeout to 90 seconds unless `GOVTRIBE_MCP_TIMEOUT_SECONDS` is explicitly set.
- Never log `GOVTRIBE_MCP_API_KEY`, authorization headers, or token fragments.
- If GovTribe is enabled but not configured, report that state explicitly in source statuses.
- If GovTribe MCP tools are unavailable or schema-incompatible, report `tool_contract_unavailable` and keep official-source scan/capture running.

### 4. GovWin IQ Commercial Intelligence

- Type: subscription commercial-intelligence enrichment
- Shipped use:
  - source-registry contract and credential validation scaffold
  - placeholder scan and capture status reporting
- Access pattern: vendor web service
- Trust tier: 4
- Portal: https://www.deltek.com/en/products/project-based-businesses/govwin-iq
- API docs: https://help.deltek.com/Product/GovWinIQ/Configuring/API_v2_Configuration.htm
- Runtime implementation:
  - `scripts/intel/providers/govwin_iq.py`
  - compatibility wrapper: `scripts/common/commercial_intel.py`
- Required secrets:
  - `GOVWIN_CLIENT_ID`
  - `GOVWIN_CLIENT_SECRET`
  - `GOVWIN_USERNAME`
  - `GOVWIN_PASSWORD`

Current retrieval rules:

- Phase 1 validates the credential contract and source-registry wiring only.
- Do not describe GovWin IQ as a live retrieval adapter until a real runtime connector ships.

## Not in the shipped runtime contract

These may appear in older docs or stale workspace registries, but they are not part of the current shipped source set:

- SBA SUBNet
- Acquisition.gov procurement forecasts
- GSA eBuy Open
- Grants.gov / Simpler.Grants
- state or local procurement portals

## Operating guidance

1. Start with `SAM.gov` for live notice retrieval.
2. Use `USAspending.gov` only as enrichment around those live opportunities.
3. Treat `GovTribe MCP` and `GovWin IQ` as optional commercial sidecars behind explicit runtime enablement.
4. Keep the runtime source registry limited to the implemented or scaffolded source IDs in the current template.
5. Do not describe non-implemented sources as active just because they were present in older repo revisions.

## Semantic reasoning

`OPENAI_API_KEY` is used only by the optional semantic reasoning helpers in `scripts/common/openai_reasoning.py`. It is not required for `SAM.gov`, `USAspending.gov`, direct `GovTribe MCP`, or the `GovWin IQ` placeholder provider.

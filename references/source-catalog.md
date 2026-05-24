# Source Catalog

This bundle is federal-only, and the shipped runtime contract currently implements two official sources:

- `SAM.gov` for live contract opportunity retrieval
- `USAspending.gov` for award-history enrichment

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
  - `scripts/scan/sam_search.py`
  - `scripts/scan/sam_hydrate.py`
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

## Not in the shipped runtime contract

These may appear in older docs or stale workspace registries, but they are not part of the current shipped source set:

- SBA SUBNet
- Acquisition.gov procurement forecasts
- GSA eBuy Open
- Grants.gov / Simpler.Grants
- GovTribe
- GovWin
- state or local procurement portals

## Operating guidance

1. Start with `SAM.gov` for live notice retrieval.
2. Use `USAspending.gov` only as enrichment around those live opportunities.
3. Keep the runtime source registry limited to the implemented source IDs.
4. Do not describe non-implemented sources as active just because they were present in older repo revisions.

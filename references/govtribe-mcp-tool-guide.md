# GovTribe MCP Tool Guide

Use this reference when working on the optional GovTribe MCP commercial-intelligence sidecar or when a capture workflow needs direct GovTribe MCP guidance. This file summarizes the source docs under the GovTribe web repo's `resources/docs/content/docs/govtribe-for-agents/` tree.

## Core Rules

- Use GovTribe as optional commercial scan retrieval and enrichment when the workspace enables `govtribe_mcp_commercial_intel`.
- Let enabled GovTribe retrieval run alongside SAM.gov; use `provider_options.scan_retrieval_enabled: false` only when the workspace should keep GovTribe to enrichment after official-source retrieval.
- Use `GOVTRIBE_MCP_API_KEY` for GovTribe MCP. Do not require `OPENAI_API_KEY` for GovTribe.
- Use typed `Search_*` tools when the target record family is known.
- Use `Search_GovTribe` only as a broad resolver when the record type, GovTribe ID, or source identifier meaning is unclear.
- Use `Search_Activity` only after a subject record is known; it requires `govtribe_type` and `govtribe_id` and is not an opportunity search tool.
- Request focused `fields_to_return`; missing fields in a response may mean they were not requested, not that the data is absent.
- Never log token values, Authorization headers, or token fragments.

## Tool Selection

| Need | Primary tool | Use |
| --- | --- | --- |
| Vendor profile, vendor name, UEI, certifications, vendor NAICS, or vendor award/vehicle context | `Search_Vendors` | Workspace bootstrap from GovTribe vendor records. Use `uei_values` for exact UEI lookups, `query` for names or GovTribe vendor URL slugs, and focused vendor fields. |
| Federal solicitation, sources-sought notice, special notice, or pre-award opportunity | `Search_Federal_Contract_Opportunities` | Scan enrichment and opportunity lookup. Use `solicitation_numbers` for raw solicitation numbers and `govtribe_ids` for GovTribe opportunity IDs. |
| Incumbent, award history, recompete timing, contract number, obligations, awardee | `Search_Federal_Contract_Awards` | Capture enrichment around prior work and incumbent/value signals. Use `piids` for PIIDs or combined federal contract numbers. |
| IDIQ, BPA, GWAC, schedule, task-order parent, ceiling, awardee, ordering vehicle | `Search_Federal_Contract_IDVs` | Capture enrichment for IDV parent instruments and task-order lineage. Use `piids` for public vehicle or IDV numbers. |
| Vehicle program, MAS/GWAC/IDIQ program scope, ordering window, shared ceiling | `Search_Federal_Contract_Vehicles` | Capture enrichment for vehicle-level scope and buying-lane signals. |
| Solicitation attachments, file metadata, citable URLs, snippets/extracts | `Search_Government_Files` | Evidence gathering from government-file metadata and snippets. Use parent GovTribe IDs when known; do not pass raw PIIDs or solicitation numbers as parent IDs. |
| Unknown record type or ambiguous identifier | `Search_GovTribe` | Resolve to candidate records and follow returned resolver hints into typed tools. |
| Recent changes on a known GovTribe record | `Search_Activity` | Activity-only enrichment after a typed record has already been resolved. Pass `govtribe_type` and `govtribe_id`. |

## Default Fields

Use these fields as a compact default projection when the schema supports them.

### `Search_Vendors`

- `govtribe_id`
- `govtribe_type`
- `govtribe_url`
- `uei`
- `name`
- `dba`
- `division`
- `govtribe_ai_summary`
- `location`
- `address`
- `sba_certifications`
- `business_types`
- `parent_or_child`
- `parent`
- `naics_category`
- `federal_contract_awards`
- `federal_contract_idvs`
- `federal_contract_sub_awards`
- `awarded_federal_contract_vehicle`

### `Search_Federal_Contract_Opportunities`

- `govtribe_id`
- `govtribe_url`
- `source_url`
- `name`
- `solicitation_number`
- `opportunity_type`
- `opportunity_state`
- `set_aside_type`
- `posted_date`
- `due_date`
- `award_date`
- `descriptions`
- `govtribe_ai_summary`
- `federal_contract_vehicle`
- `federal_agency`
- `naics_category`
- `psc_category`
- `government_files`
- `federal_contract_awards`
- `federal_contract_idvs`

### `Search_Federal_Contract_Awards`

- `govtribe_id`
- `govtribe_url`
- `name`
- `contract_number`
- `award_date`
- `ultimate_completion_date`
- `ceiling_value`
- `dollars_obligated`
- `base_and_exercised_options_value`
- `set_aside_type`
- `descriptions`
- `govtribe_ai_summary`
- `awardee`
- `federal_contract_vehicle`
- `federal_contract_idv`
- `contracting_federal_agency`
- `funding_federal_agency`
- `originating_federal_contract_opportunity`

### `Search_Federal_Contract_IDVs`

- `govtribe_id`
- `govtribe_url`
- `name`
- `contract_number`
- `award_date`
- `last_date_to_order`
- `ceiling_value`
- `dollars_obligated`
- `base_and_exercised_options_value`
- `set_aside`
- `description`
- `govtribe_ai_summary`
- `awardee`
- `federal_contract_vehicle`
- `contracting_federal_agency`
- `funding_federal_agency`
- `originating_federal_contract_opportunity`
- `task_orders`

### `Search_Federal_Contract_Vehicles`

- `govtribe_id`
- `govtribe_url`
- `name`
- `award_date`
- `last_date_to_order`
- `shared_ceiling`
- `set_aside_type`
- `descriptions`
- `govtribe_ai_summary`
- `federal_agency`
- `federal_contract_awards`
- `originating_federal_contract_opportunity`

### `Search_Government_Files`

- `govtribe_id`
- `govtribe_url`
- `download_url`
- `name`
- `file_format`
- `extension`
- `file_source`
- `size`
- `posted_date`
- `content_snippet`
- `govtribe_ai_summary`
- `parent_record`

## Query And Search Mode Guidance

Use `keyword` when the user gives exact words, identifiers, names, category codes, contract numbers, solicitation numbers, or phrases that must match. Use `semantic` when the user describes a concept, mission, capability, problem, or related work and exact wording is not the main requirement.

If a selected tool does not expose `search_mode`, omit it and use keyword-style query construction.

Keyword guidance:

- Quote exact names, identifiers, titles, program phrases, and multi-word service names.
- Use `+` when both concepts must match.
- Use `|` for alternatives; do not use uppercase `OR`.
- Use `-` only when there is at least one positive term or phrase.
- Use parentheses to group alternatives.
- Use trailing `*` or `~1`/`~2` sparingly for prefix or fuzzy broadening.
- Keep agencies, vendors, categories, dates, values, locations, set-asides, statuses, workspace state, and capture state in structured tool arguments instead of `field:value` query text.
- Do not use `agency:NASA`, boosted terms such as `cloud^2`, or Lucene words such as `AND` and `OR`.

Semantic guidance:

- Write a natural-language description of the work, mission, or problem.
- Add only a few useful synonyms or paraphrases when they improve recall.
- Keep structured constraints in tool arguments.
- Do not use keyword operators in semantic mode.
- Pair broad semantic queries with strong filters when possible.

## Scan Retrieval And Enrichment Pattern

1. For GovTribe enrichment of SAM.gov records, use `Search_Federal_Contract_Opportunities` against each SAM result.
2. If a SAM record has a solicitation number, call with `solicitation_numbers: ["<number>"]`, `search_mode: "keyword"`, and the opportunity fields above.
3. If that returns no records, call the same tool with a keyword `query` built from the title and buyer.
4. Use semantic mode for SAM-record enrichment only when title/buyer keyword search returns no useful records and the task is broad concept discovery.
5. When GovTribe scan retrieval is enabled, call `Search_Federal_Contract_Opportunities` directly with vendor capability/profile terms as `query`, confirmed/candidate NAICS as structured `naics_codes` when the schema supports it, and focused `fields_to_return`.
6. Run GovTribe retrieval as keyword/structured-filter first. Apply active opportunity states and a future-facing `due_date_range` before any semantic expansion; do not rank expired semantic matches as open opportunities.
7. Use semantic mode only as a controlled broadening fallback after the keyword/structured-filter pass returns no usable records. Keep the strongest structured filters in place, use a concise plain-language capability query, and sort semantic calls by `_score`.
8. If GovTribe returns no match or a schema-compatible tool is unavailable, report `no_match` or `tool_contract_unavailable` and keep the scan output shape stable.

## Vendor Bootstrap Pattern

1. Use `Search_Vendors` when bootstrap input is a GovTribe vendor URL, vendor name, UEI, or vendor-search request.
2. For exact UEI input, pass `uei_values: ["<UEI>"]`, `search_mode: "keyword"`, `per_page: 5`, and the vendor fields above.
3. For GovTribe vendor URLs, parse the vendor slug for `query` and prefer returned records whose `govtribe_url` or ID matches the slug.
4. For vendor names, pass the name as `query`, use keyword mode, and choose exact normalized name or DBA before falling back to the highest-ranked result.
5. If the resolved vendor has `parent_or_child: "Child"` and a `parent` record, preserve that hierarchy and explicitly ask the user whether to stay on the resolved child vendor or move up the vendor chain to the parent before scanning.
6. After the vendor is resolved, use `Search_Federal_Contract_Awards` with the vendor UEI/GovTribe ID, `per_page: 0`, and every compatible bootstrap aggregation the schema exposes: buyer agencies, vehicles, NAICS, places of performance, set-asides, contract types, pricing types, and value stats.
7. When available, call `Search_Service_Contract_Inventory` with the vendor UEI/GovTribe ID and `per_page: 0` for pricing/workshare aggregations: derived hourly rate, invoiced dollars, hours, FTEs, role split, PSC/NAICS categories, buyer agencies, states, fiscal years, and contract numbers.
8. When available, call `Search_FCV_Subcategories` with the vendor UEI/GovTribe ID to capture concrete GSA MAS SINs, pools, lots, lanes, and other vehicle subcategories that are more actionable than a top-level vehicle name.
9. When available, call `Search_Federal_Contract_Sub_Awards` with the vendor UEI/GovTribe ID to capture subcontractor posture, historical prime relationships, and sub-award buyer context. Add `"subcontractor"` only when the vendor appears in sub-award evidence or the vendor profile explicitly carries sub-award evidence.
10. Normalize award aggregation buckets into both simple profile fields and `vendor-profile.json.govtribe_award_profile`; keep NAICS and geography as candidate or soft preference signals, not user-confirmed facts.
11. Store GovTribe award value stat min/max/average/sum as observed history, for example `commercial_constraints.observed_award_value_range`; keep hard `min_award_value`, `max_award_value`, and `preferred_award_band` null unless the user confirms them as constraints.
12. Normalize SCI pricing/workshare data into `vendor-profile.json.govtribe_service_contract_inventory_profile`. Use it for soft preferences and starter notes only; do not backfill hard `min_award_value`, `max_award_value`, or labor-rate constraints from history.
13. Use `Search_Federal_Contract_Vehicles` or `Find_Federal_Contract_Vehicles` with the vendor UEI/GovTribe ID to identify vehicles the vendor has access to, including schedules, GWACs, BPAs, and IDIQs.
14. Normalize returned fields into `vendor-profile.json` with field-level provenance marked `govtribe_subscription_derived`.
15. Skip optional aggregations or tools that are not exposed by the active schema and add a bootstrap note instead of failing the workflow.
16. Never write API keys, bearer tokens, Authorization headers, or token fragments into workspace files.
17. If GovTribe is not configured or returns no match, report that status and use website bootstrap only when a company URL is also available.

## Capture Enrichment Pattern

1. Resolve the opportunity with `Search_Federal_Contract_Opportunities`.
2. Search `Search_Federal_Contract_Awards` for incumbent, awardee, value, contract number, prior work, and recompete timing.
3. Search `Search_Federal_Contract_IDVs` and `Search_Federal_Contract_Vehicles` for vehicle path, task-order parentage, ceiling, ordering windows, and buying-lane signals.
4. Search `Search_Government_Files` for citable files, snippets, and attachment evidence. If snippets are insufficient and full-text retrieval is available, stage files with `Add_To_Vector_Store` and search with `Search_Vector_Store`; otherwise record the evidence gap.
5. Normalize returned records into incumbent, vehicle, recompete, related procurement, value, teaming, next-question, and evidence-gap fields.

## Troubleshooting

- Too many results: add structured filters, quote exact phrases, switch to `keyword`, or use aggregations with `per_page: 0`.
- No results: remove one filter at a time, remove phrase quotes, broaden terms, switch to `semantic`, or try a related typed tool.
- Unrelated results: verify the typed tool, mode, filters, and result fields before discarding records.
- Missing values: confirm `fields_to_return` included the field and that the selected tool exposes it.

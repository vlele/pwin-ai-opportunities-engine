# GovTribe MCP Tool Guide

Use this reference when working on the optional GovTribe MCP commercial-intelligence sidecar or when a capture workflow needs direct GovTribe MCP guidance. This file summarizes the source docs under the GovTribe web repo's `resources/docs/content/docs/govtribe-for-agents/` tree.

## Core Rules

- Use GovTribe as optional commercial enrichment after official SAM.gov retrieval by default.
- Use GovTribe as primary scan retrieval only when the workspace explicitly sets `provider_options.allow_scan_retrieval_without_sam: true` and SAM.gov is disabled or missing `SAM_API_KEY`.
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
- `naics_category`
- `federal_contract_awards`
- `federal_contract_idvs`
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

1. When SAM.gov produced records, use `Search_Federal_Contract_Opportunities` only as scan enrichment.
2. If a SAM record has a solicitation number, call with `solicitation_numbers: ["<number>"]`, `search_mode: "keyword"`, and the opportunity fields above.
3. If that returns no records, call the same tool with a keyword `query` built from the title and buyer.
4. Use semantic mode only when title/buyer keyword search returns no useful records and the task is broad concept discovery.
5. When SAM.gov cannot run and GovTribe-only scan retrieval is explicitly opted in, call `Search_Federal_Contract_Opportunities` directly with vendor capability/profile terms as `query`, confirmed/candidate NAICS as structured `naics_codes` when the schema supports it, and focused `fields_to_return`.
6. Run GovTribe-only retrieval as keyword/structured-filter first. Apply active opportunity states and a future-facing `due_date_range` before any semantic expansion; do not rank expired semantic matches as open opportunities.
7. Use semantic mode only as a controlled broadening fallback after the keyword/structured-filter pass returns no usable records. Keep the strongest structured filters in place, use a concise plain-language capability query, and sort semantic calls by `_score`.
8. If GovTribe returns no match or a schema-compatible tool is unavailable, report `no_match` or `tool_contract_unavailable` and keep the scan output shape stable.

## Vendor Bootstrap Pattern

1. Use `Search_Vendors` when bootstrap input is a GovTribe vendor URL, vendor name, UEI, or vendor-search request.
2. For exact UEI input, pass `uei_values: ["<UEI>"]`, `search_mode: "keyword"`, `per_page: 5`, and the vendor fields above.
3. For GovTribe vendor URLs, parse the vendor slug for `query` and prefer returned records whose `govtribe_url` or ID matches the slug.
4. For vendor names, pass the name as `query`, use keyword mode, and choose exact normalized name or DBA before falling back to the highest-ranked result.
5. After the vendor is resolved, use `Search_Federal_Contract_Awards` with the vendor UEI/GovTribe ID, `per_page: 0`, and aggregations such as `top_contracting_federal_agencies_by_dollars_obligated`, `top_funding_federal_agencies_by_dollars_obligated`, and `top_federal_contract_vehicles_by_dollars_obligated` to identify buyer and vehicle signals.
6. Use `Search_Federal_Contract_Vehicles` or `Find_Federal_Contract_Vehicles` with the vendor UEI/GovTribe ID to identify vehicles the vendor has access to, including schedules, GWACs, BPAs, and IDIQs.
7. Normalize returned fields into `vendor-profile.json` with field-level provenance marked `govtribe_subscription_derived`.
8. Never write API keys, bearer tokens, Authorization headers, or token fragments into workspace files.
9. If GovTribe is not configured or returns no match, report that status and use website bootstrap only when a company URL is also available.

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

# Fix GovTribe Vendor Bootstrap URL Lookup and Profile Normalization

## Summary

Fix issue #39 as a follow-up to the merged GovTribe bootstrap feature. A user starting from `https://govtribe.com/vendors/halvik-corp-5grr4` should get the same successful bootstrap as using `VMRTJLWMQRH7` or `Halvik, LLC`, and generated workspace files should contain clean NAICS, capability, certification, vehicle, keyword, and provenance buckets.

## Implementation Changes

- Update GovTribe vendor URL resolution in `scripts/intel/providers/govtribe_mcp.py` so vendor URLs try a stripped human query such as `halvik corp` before the full slug query such as `halvik corp 5grr4`, while preserving UEI and exact-name behavior.
- Normalize GovTribe vendor output before bootstrap writes artifacts: keep `naics` as six-digit codes, add display-oriented `naics_items`, map known label-only NAICS values such as `Web Search Portals and All Other Information Services` to `519290`, and filter boolean/generic metadata out of vehicles, capabilities, and matching keywords.
- Improve GovTribe bootstrap artifact construction in `scripts/bootstrap/bootstrap_workspace.py` so capabilities come from summary and award text, certifications stay under commercial constraints, NAICS filters are code-only, and `STARTER_PROFILE.md` renders code plus label.

## Test Plan

- Extend `scripts/tests/run_intel_provider_tests.py` with a Halvik-style URL retry fixture, label-only NAICS normalization, and filtering assertions for `True` and generic entity metadata.
- Extend `scripts/tests/run_bootstrap_tests.py` with a Halvik-style GovTribe bootstrap fixture that verifies `519290`, real capabilities, certification placement, clean preferences, and starter-profile NAICS display.
- Validate with:
  - `PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/run_bootstrap_tests.py`
  - `PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/run_intel_provider_tests.py`
  - `PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/run_skill_contract_tests.py`
  - `PYTHONDONTWRITEBYTECODE=1 python3 scripts/tests/run_source_policy_tests.py`
  - Live GovTribe MCP bootstrap against the Halvik vendor URL when credentials and network access are available.

## Assumptions

- Do not change the public CLI; `--vendor-lookup` remains the user-facing interface.
- Do not add live GovTribe tests to CI because they require credentials and network access.
- Keep GovTribe-derived facts labeled as provisional commercial intelligence, and never write secrets or authorization details to workspace files.

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.paths import load_json, write_json  # type: ignore
from common.source_registry import filter_sources_for_policy, get_enabled_sources, refresh_runtime_registry, sources_summary  # type: ignore


def main() -> int:
    registry = {
        "sources": [
            {
                "id": "sam_contract_opportunities",
                "name": "SAM.gov Contract Opportunities",
                "enabled": True,
                "federal_only_eligible": True,
                "trust_tier": 1,
            },
            {
                "id": "usaspending_award_history",
                "name": "USAspending.gov Award History",
                "default_enabled": True,
                "federal_only_eligible": True,
                "trust_tier": 1,
            },
            {
                "id": "virginia_eva_vbo",
                "name": "Virginia eVA / VBO",
                "enabled": True,
                "federal_only_eligible": False,
                "trust_tier": 2,
            },
            {
                "id": "govtribe_mcp_commercial_intel",
                "name": "GovTribe MCP Commercial Intelligence",
                "enabled": True,
                "federal_only_eligible": True,
                "trust_tier": 4,
            },
            {
                "id": "govwin_iq_commercial_intel",
                "name": "GovWin IQ Commercial Intelligence",
                "enabled": True,
                "federal_only_eligible": True,
                "trust_tier": 4,
            },
            {
                "id": "disabled_source",
                "name": "Disabled Source",
                "enabled": False,
                "federal_only_eligible": True,
                "trust_tier": 2,
            },
        ]
    }

    enabled_sources = get_enabled_sources(registry)
    federal_only_sources = filter_sources_for_policy(enabled_sources, federal_only=True)
    unfiltered_sources = filter_sources_for_policy(enabled_sources, federal_only=False)

    enabled_ids = [source.get("id") for source in enabled_sources]
    federal_only_ids = [source.get("id") for source in federal_only_sources]
    failures: list[str] = []

    if enabled_ids != [
        "sam_contract_opportunities",
        "usaspending_award_history",
        "virginia_eva_vbo",
        "govtribe_mcp_commercial_intel",
        "govwin_iq_commercial_intel",
    ]:
        failures.append("enabled_source_selection")

    if federal_only_ids != [
        "sam_contract_opportunities",
        "usaspending_award_history",
        "govtribe_mcp_commercial_intel",
        "govwin_iq_commercial_intel",
    ]:
        failures.append("federal_only_filter")

    if [source.get("id") for source in unfiltered_sources] != enabled_ids:
        failures.append("non_federal_mode_preserves_enabled_sources")

    summary = sources_summary(federal_only_sources)
    if "Virginia" in summary:
        failures.append("federal_summary_excludes_non_federal_sources")

    if "GovTribe" not in summary or "GovWin" not in summary:
        failures.append("federal_summary_includes_federal_commercial_sources")

    bundle_root = Path(__file__).resolve().parents[2]
    template = load_json(bundle_root / "templates" / "source-registry.template.json", default={})
    template_govtribe = next(
        (source for source in template.get("sources", []) if source.get("id") == "govtribe_mcp_commercial_intel"),
        {},
    )
    if template_govtribe.get("provider_options", {}).get("allow_scan_retrieval_without_sam") is not False:
        failures.append("govtribe_scan_retrieval_default_off")
    if "scan_retrieval" not in template_govtribe.get("capabilities", []):
        failures.append("govtribe_scan_retrieval_capability")

    with tempfile.TemporaryDirectory() as tmpdir:
        workspace = Path(tmpdir)
        runtime_path = workspace / "procurement" / "source-registry.json"
        runtime = dict(template)
        runtime["template_version"] = "stale-template"
        runtime_sources = []
        for source in template.get("sources", []):
            copied = dict(source)
            if copied.get("id") == "govtribe_mcp_commercial_intel":
                copied["enabled"] = True
                copied["provider_options"] = {"allow_scan_retrieval_without_sam": True}
            runtime_sources.append(copied)
        runtime["sources"] = runtime_sources
        write_json(runtime_path, runtime)
        _, refreshed_registry, refreshed, _ = refresh_runtime_registry(bundle_root, workspace)
        refreshed_govtribe = next(
            (source for source in refreshed_registry.get("sources", []) if source.get("id") == "govtribe_mcp_commercial_intel"),
            {},
        )
        if not refreshed:
            failures.append("registry_refresh_expected")
        if refreshed_govtribe.get("provider_options", {}).get("allow_scan_retrieval_without_sam") is not True:
            failures.append("registry_refresh_preserves_provider_options")

    output = {
        "status": "OK" if not failures else "FAILED",
        "enabled_ids": enabled_ids,
        "federal_only_ids": federal_only_ids,
        "federal_only_summary": summary,
        "failed_checks": failures,
    }
    print(json.dumps(output, ensure_ascii=True))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())

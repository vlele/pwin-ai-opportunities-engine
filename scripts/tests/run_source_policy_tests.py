from __future__ import annotations

import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.source_registry import filter_sources_for_policy, get_enabled_sources, sources_summary  # type: ignore


def main() -> int:
    registry = {
        "sources": [
            {
                "id": "sam_contract_opportunities",
                "name": "SAM.gov Contract Opportunities",
                "enabled": True,
                "trust_tier": 1,
            },
            {
                "id": "usaspending_award_history",
                "name": "USAspending.gov Award History",
                "default_enabled": True,
                "trust_tier": 1,
            },
            {
                "id": "virginia_eva_vbo",
                "name": "Virginia eVA / VBO",
                "enabled": True,
                "trust_tier": 2,
            },
            {
                "id": "govtribe_commercial_intel",
                "name": "GovTribe",
                "enabled": True,
                "trust_tier": 4,
            },
            {
                "id": "disabled_source",
                "name": "Disabled Source",
                "enabled": False,
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
        "govtribe_commercial_intel",
    ]:
        failures.append("enabled_source_selection")

    if federal_only_ids != [
        "sam_contract_opportunities",
        "usaspending_award_history",
    ]:
        failures.append("federal_only_filter")

    if [source.get("id") for source in unfiltered_sources] != enabled_ids:
        failures.append("non_federal_mode_preserves_enabled_sources")

    summary = sources_summary(federal_only_sources)
    if "Virginia" in summary or "GovTribe" in summary:
        failures.append("federal_summary_excludes_filtered_sources")

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

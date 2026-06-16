from __future__ import annotations

import os
from typing import Any

from intel.providers.base import default_result, env_int


def _govwin_timeout_seconds() -> int:
    return env_int("GOVWIN_TIMEOUT_SECONDS", 30)


class GovWinIQCommercialIntelProvider:
    source_id = "govwin_iq_commercial_intel"
    source_name = "GovWin IQ Commercial Intelligence"

    def __init__(self, source_config: dict[str, Any]):
        self.source_config = source_config

    def is_configured(self) -> tuple[bool, list[str]]:
        required = [
            "GOVWIN_CLIENT_ID",
            "GOVWIN_CLIENT_SECRET",
            "GOVWIN_USERNAME",
            "GOVWIN_PASSWORD",
        ]
        missing = [name for name in required if not str(os.getenv(name) or "").strip()]
        return not missing, missing

    def _phase1_result(self) -> dict[str, Any]:
        configured, missing = self.is_configured()
        if not configured:
            return default_result(
                self.source_id,
                self.source_name,
                "not_configured",
                notes=[f"Missing env vars: {', '.join(missing)}"],
            )
        return default_result(
            self.source_id,
            self.source_name,
            "configured_no_runtime_adapter",
            notes=[
                "GovWin Phase 1 validates the credential contract and source-registry entry only.",
                f"GovWin timeout setting available: {_govwin_timeout_seconds()} seconds.",
            ],
        )

    def enrich_scan(
        self,
        *,
        record: dict[str, Any],
        hydrated_text: str,
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any],
    ) -> dict[str, Any]:
        return self._phase1_result()

    def enrich_capture(
        self,
        *,
        resolved: dict[str, Any],
        notice_context_text: str,
        attachment_bundle: dict[str, Any],
        vendor_profile: dict[str, Any],
        preferences: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._phase1_result()

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scan.sam_search import search_sam_opportunities  # type: ignore


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    original_sam_api_key = os.environ.get("SAM_API_KEY")
    os.environ["SAM_API_KEY"] = "test-sam-key"
    try:
        search_result = search_sam_opportunities(naics_codes=[], today=date(2026, 6, 10))
        assert search_result["status"] == "no_naics", search_result
        assert search_result["recommended_next_step"] == "bootstrap_workspace", search_result
        assert "Bootstrap this workspace" in search_result["recommended_message"], search_result

        with tempfile.TemporaryDirectory() as tmp_dir:
            workspace = Path(tmp_dir) / "workspace"
            procurement = workspace / "procurement"
            procurement.mkdir(parents=True, exist_ok=True)
            _write_json(
                procurement / "vendor-profile.json",
                {
                    "company": {
                        "website": "https://example.com",
                    }
                },
            )

            completed = subprocess.run(
                [
                    "python3",
                    str(SCRIPT_ROOT / "scan" / "run_scan.py"),
                    "--workspace",
                    str(workspace),
                    "--horizon",
                    "30-45",
                    "--federal-only",
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(completed.stdout.strip())

            assert payload["recommended_next_step"] == "bootstrap_workspace", payload
            assert payload["bootstrap_suggested"] is True, payload
            assert payload["recommended_next_moves"], payload
            assert payload["recommended_next_moves"][0]["type"] == "bootstrap_workspace", payload
            assert "https://example.com" in payload["recommended_next_moves"][0]["command"], payload
            assert Path(payload["digest_path"]).exists(), payload

            sam_status = next(
                item
                for item in payload["source_statuses"]
                if item.get("source_id") == "sam_contract_opportunities"
            )
            assert sam_status["status"] == "no_naics", sam_status
            assert sam_status["recommended_next_step"] == "bootstrap_workspace", sam_status
            assert "https://example.com" in sam_status["recommended_command"], sam_status
    finally:
        if original_sam_api_key is None:
            os.environ.pop("SAM_API_KEY", None)
        else:
            os.environ["SAM_API_KEY"] = original_sam_api_key

    print("run_scan_bootstrap_guidance_tests.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

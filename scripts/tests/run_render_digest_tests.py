from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from scan.render_digest import render_digest_and_report  # type: ignore


DATE_STR = "2026-06-10"


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _write_base_workspace(workspace: Path) -> None:
    _write_json(
        workspace / "procurement" / "vendor-profile.json",
        {
            "company": {
                "name": "Acme Federal",
                "website": "https://example.com",
            }
        },
    )


def _render(bundle_root: Path, workspace: Path, *, source_issues: list[str] | None = None) -> tuple[str, str]:
    result = render_digest_and_report(
        bundle_root=bundle_root,
        workspace=workspace,
        date_str=DATE_STR,
        horizon="30-45",
        run_notes=["Regression test render."],
        enabled_source_summary="SAM.gov Contract Opportunities (Tier 1)",
        source_issues=source_issues,
    )
    digest_text = Path(result["digest_path"]).read_text(encoding="utf-8")
    report_text = Path(result["report_path"]).read_text(encoding="utf-8")
    return digest_text, report_text


def _assert_no_placeholders(*texts: str) -> None:
    for text in texts:
        assert "{{" not in text and "}}" not in text, text


def _assert_absent(text: str, snippets: list[str]) -> None:
    for snippet in snippets:
        assert snippet not in text, snippet


def test_empty_digest_feedback_guidance(bundle_root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_base_workspace(workspace)
        _write_json(workspace / "procurement" / "opportunities" / f"{DATE_STR}.json", {"records": []})

        digest_text, report_text = _render(
            bundle_root,
            workspace,
            source_issues=["SAM.gov Contract Opportunities: quota throttled"],
        )

        old_examples = [
            "`like A1`",
            "`dislike W2 because too small`",
            "`research A1`",
            "`capture deep dive on A1`",
        ]
        _assert_absent(digest_text, old_examples)
        _assert_absent(report_text, old_examples)
        _assert_no_placeholders(digest_text, report_text)

        for text in (digest_text, report_text):
            assert "No stable entry IDs were generated" in text, text
            assert "retry the scan after the source recovers" in text, text
            assert "SAM.gov Contract Opportunities: quota throttled" in text, text


def test_non_empty_digest_uses_actual_ids(bundle_root: Path) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        workspace = Path(tmp_dir) / "workspace"
        _write_base_workspace(workspace)
        _write_json(
            workspace / "procurement" / "opportunities" / f"{DATE_STR}.json",
            {
                "records": [
                    {
                        "bucket": "watchlist",
                        "source_id": "sam_contract_opportunities",
                        "source_name": "SAM.gov Contract Opportunities",
                        "source_tier": 1,
                        "opportunity_id": "opp-1",
                        "canonical_record_id": "opp-1",
                        "title": "Case Management Modernization",
                        "url": "https://sam.gov/opp/opp-1",
                        "buyer": "Department of Example",
                        "due_date": "2026-07-15",
                        "match_score": 50,
                        "confidence_score": 72,
                        "notice_type": "sources_sought",
                        "opportunity_class": "contracts",
                    }
                ]
            },
        )
        _write_json(
            workspace / "procurement" / "explanations" / f"{DATE_STR}.json",
            {
                "items": [
                    {
                        "opportunity_id": "opp-1",
                        "summary": "Modernization opportunity for case management systems.",
                        "reasons": ["Matches case management modernization capabilities."],
                    }
                ]
            },
        )

        digest_text, report_text = _render(bundle_root, workspace)

        absent_examples = [
            "`like A1`",
            "`dislike W2 because too small`",
            "`more like A1`",
            "`research A1`",
            "`capture deep dive on A1`",
        ]
        for text in (digest_text, report_text):
            assert "### E1 - Case Management Modernization" in text, text
            assert "`like E1`" in text, text
            assert "`dislike E1 because too small`" in text, text
            assert "`research E1`" in text, text
            assert "`capture deep dive on E1`" in text, text
            _assert_absent(text, absent_examples)
        _assert_no_placeholders(digest_text, report_text)


def main() -> int:
    bundle_root = Path(__file__).resolve().parents[2]
    test_empty_digest_feedback_guidance(bundle_root)
    test_non_empty_digest_uses_actual_ids(bundle_root)
    print("run_render_digest_tests.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

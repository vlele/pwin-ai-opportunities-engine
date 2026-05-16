from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.paths import load_json, read_text
from common.validation import validate_capture_brief_text
from capture.resolve_entry import resolve_entry


def resolve_paths_from_workspace(workspace: Path, entry: str) -> tuple[Path | None, Path | None]:
    resolved = resolve_entry(workspace, entry)
    digest_date = resolved.get("digest_date")
    if not digest_date:
        return None, None

    display_entry = resolved.get("report_entry_id") or "direct"
    canonical = resolved.get("canonical_record_id") or resolved.get("notice_id") or entry
    canonical_fragment = canonical[:24]
    brief_dir = workspace / "procurement" / "capture-briefs" / digest_date
    evidence_dir = workspace / "procurement" / "capture-evidence" / digest_date
    brief_candidates = sorted(brief_dir.glob(f"{display_entry.lower()}-{canonical_fragment}*.md")) + sorted(
        brief_dir.glob(f"{display_entry}-{canonical_fragment}*.md")
    )
    evidence_candidates = sorted(evidence_dir.glob(f"{display_entry.lower()}-{canonical_fragment}*.json")) + sorted(
        evidence_dir.glob(f"{display_entry}-{canonical_fragment}*.json")
    )
    brief_path = brief_candidates[-1] if brief_candidates else None
    evidence_path = evidence_candidates[-1] if evidence_candidates else None
    return brief_path, evidence_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--brief")
    parser.add_argument("--evidence")
    parser.add_argument("--workspace")
    parser.add_argument("--entry")
    args = parser.parse_args()

    if args.brief and args.evidence:
        brief_path = Path(args.brief)
        evidence_path = Path(args.evidence)
    elif args.workspace and args.entry:
        brief_path, evidence_path = resolve_paths_from_workspace(Path(args.workspace), args.entry)
        if brief_path is None or evidence_path is None:
            print(json.dumps({"status": "FAILED", "reason": "Unable to resolve capture artifacts"}, ensure_ascii=True))
            return 20
    else:
        print(
            json.dumps(
                {"status": "FAILED", "reason": "Provide either --brief and --evidence, or --workspace and --entry"},
                ensure_ascii=True,
            )
        )
        return 20

    evidence = load_json(evidence_path, default={})
    brief_text = read_text(brief_path)
    brief_validation = validate_capture_brief_text(brief_text)

    result = {
        "status": evidence.get("status", "FAILED"),
        "brief_path": brief_path.as_posix(),
        "evidence_path": evidence_path.as_posix(),
        "brief_validation": brief_validation,
        "generated_from_current_request": evidence.get("validation", {}).get("generated_from_current_request", False),
        "stub_stage_exited_before_response": evidence.get("validation", {}).get("stub_stage_exited_before_response", False),
    }

    if not brief_validation["all_required_sections_present"] or brief_validation["contains_placeholders"]:
        print(json.dumps(result, ensure_ascii=True))
        return 20
    if evidence.get("status") == "PARTIAL_CAPTURE_RESEARCH":
        print(json.dumps(result, ensure_ascii=True))
        return 10
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

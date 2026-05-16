from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from common.paths import latest_dated_file, read_text, standard_procurement_paths
from common.validation import validate_digest_text


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--date", required=True)
    args = parser.parse_args()

    workspace = Path(args.workspace)
    digests_dir = workspace / "procurement" / "digests"
    if args.date == "latest":
        digest_path = latest_dated_file(digests_dir, ".md")
        if digest_path is None:
            print(json.dumps({"status": "FAILED", "reason": "No digests found"}, ensure_ascii=True))
            return 20
        date_str = digest_path.stem
    else:
        date_str = args.date
        digest_path = standard_procurement_paths(workspace, date_str)["digest"]
        if not digest_path.exists():
            print(json.dumps({"status": "FAILED", "reason": f"Digest {date_str} not found"}, ensure_ascii=True))
            return 20

    map_path = standard_procurement_paths(workspace, date_str)["digest_entry_map"]
    digest_text = read_text(digest_path)
    result = {
        "status": "OK",
        "date": date_str,
        "digest_path": digest_path.as_posix(),
        "digest_entry_map_path": map_path.as_posix() if map_path.exists() else "",
        "validation": validate_digest_text(digest_text),
    }
    print(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


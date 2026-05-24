from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("America/New_York")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bundle_root_from_script(script_file: str) -> Path:
    return Path(script_file).resolve().parents[2]

def local_now() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_local_str() -> str:
    return local_now().date().isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> Path:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
    return path


def read_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    return path.read_text(encoding="utf-8")


def write_text(path: Path, text: str) -> Path:
    ensure_dir(path.parent)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")
    return path


def procurement_dir(workspace: Path) -> Path:
    return ensure_dir(workspace / "procurement")


def list_dated_files(directory: Path, suffix: str) -> list[Path]:
    if not directory.exists():
        return []
    files: list[Path] = []
    for path in directory.iterdir():
        if path.is_file() and path.name.endswith(suffix):
            stem = path.name[: -len(suffix)]
            if DATE_RE.match(stem):
                files.append(path)
    return sorted(files)


def latest_dated_file(directory: Path, suffix: str) -> Path | None:
    files = list_dated_files(directory, suffix)
    return files[-1] if files else None


def standard_procurement_paths(workspace: Path, date_str: str) -> dict[str, Path]:
    base = procurement_dir(workspace)
    return {
        "procurement": base,
        "vendor_profile": base / "vendor-profile.json",
        "preferences": base / "preferences.json",
        "source_registry": base / "source-registry.json",
        "feedback_events": base / "feedback-events.jsonl",
        "capture_requests": base / "capture-requests.jsonl",
        "opportunities": base / "opportunities" / f"{date_str}.json",
        "explanations": base / "explanations" / f"{date_str}.json",
        "report": base / "reports" / f"{date_str}.md",
        "digest": base / "digests" / f"{date_str}.md",
        "digest_entry_map": base / "digest-entry-map" / f"{date_str}.json",
        "run_log": base / "run-logs" / f"{date_str}.log",
    }


def safe_slug(value: str, max_length: int = 48) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    if not cleaned:
        cleaned = "item"
    return cleaned[:max_length].rstrip("-")


def first_non_empty(values: Iterable[Any], default: Any = "") -> Any:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return default

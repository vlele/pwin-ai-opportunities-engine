from __future__ import annotations

from pathlib import Path
from typing import Any

from common.paths import load_json


def load_notice_context(workspace: Path, resolved: dict[str, Any]) -> dict[str, Any]:
    digest_date = resolved.get("digest_date")
    context: dict[str, Any] = {
        "opportunity_record": {},
        "explanation_record": {},
        "report_text": "",
        "digest_text": "",
    }
    if not digest_date:
        return context

    opportunities_path = workspace / "procurement" / "opportunities" / f"{digest_date}.json"
    explanations_path = workspace / "procurement" / "explanations" / f"{digest_date}.json"
    report_path = workspace / "procurement" / "reports" / f"{digest_date}.md"
    digest_path = workspace / "procurement" / "digests" / f"{digest_date}.md"

    opportunities = load_json(opportunities_path, default=[])
    records = opportunities if isinstance(opportunities, list) else opportunities.get("records", [])
    for record in records:
        if record.get("opportunity_id") == resolved.get("opportunity_id") or record.get("notice_id") == resolved.get("notice_id"):
            context["opportunity_record"] = record
            break

    explanations = load_json(explanations_path, default=[])
    explanation_items = explanations if isinstance(explanations, list) else explanations.get("items", [])
    for item in explanation_items:
        if item.get("opportunity_id") == resolved.get("opportunity_id") or item.get("title") == resolved.get("title"):
            context["explanation_record"] = item
            break

    if report_path.exists():
        context["report_text"] = report_path.read_text(encoding="utf-8")
    if digest_path.exists():
        context["digest_text"] = digest_path.read_text(encoding="utf-8")
    return context


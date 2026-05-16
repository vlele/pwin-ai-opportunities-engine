from __future__ import annotations

from pathlib import Path
from typing import Any

from common.paths import load_json, procurement_dir, write_json


def _source_map(sources: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {source["id"]: source for source in sources}


def refresh_runtime_registry(bundle_root: Path, workspace: Path) -> tuple[Path, dict[str, Any], bool, list[str]]:
    template_path = bundle_root / "templates" / "source-registry.template.json"
    runtime_path = procurement_dir(workspace) / "source-registry.json"
    template = load_json(template_path, default={})
    runtime = load_json(runtime_path, default=None)
    reasons: list[str] = []

    if runtime is None:
        write_json(runtime_path, template)
        return runtime_path, template, True, ["runtime registry missing"]

    template_sources = template.get("sources", [])
    runtime_sources = runtime.get("sources", [])
    template_by_id = _source_map(template_sources)
    runtime_by_id = _source_map(runtime_sources)

    needs_refresh = False

    if runtime.get("template_version") != template.get("template_version"):
        needs_refresh = True
        reasons.append("template_version changed")

    if sorted(template_by_id) != sorted(runtime_by_id):
        needs_refresh = True
        reasons.append("source IDs changed")

    if not needs_refresh:
        for source_id, template_source in template_by_id.items():
            runtime_source = runtime_by_id.get(source_id, {})
            if template_source.get("default_enabled") != runtime_source.get("default_enabled"):
                needs_refresh = True
                reasons.append(f"default_enabled changed for {source_id}")
                break

    if not needs_refresh:
        return runtime_path, runtime, False, reasons

    merged = dict(template)
    merged_sources: list[dict[str, Any]] = []
    for template_source in template_sources:
        merged_source = dict(template_source)
        runtime_source = runtime_by_id.get(template_source["id"])
        if runtime_source:
            if "enabled" in runtime_source:
                merged_source["enabled"] = runtime_source["enabled"]
            if "notes" in runtime_source:
                merged_source["notes"] = runtime_source["notes"]
        merged_sources.append(merged_source)
    merged["sources"] = merged_sources
    write_json(runtime_path, merged)
    return runtime_path, merged, True, reasons


def enabled_sources_summary(registry: dict[str, Any]) -> str:
    parts: list[str] = []
    for source in registry.get("sources", []):
        if source.get("enabled", source.get("default_enabled", False)):
            parts.append(f'{source.get("name", source.get("id", "Unknown"))} (Tier {source.get("trust_tier", "N/A")})')
    return ", ".join(parts) if parts else "none enabled"


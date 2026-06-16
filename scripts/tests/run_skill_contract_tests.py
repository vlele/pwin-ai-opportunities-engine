from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


BUNDLE_ROOT = Path(__file__).resolve().parents[2]
SKILL_NAME = "pwin-ai-opportunities"
MAX_SKILL_LINES = 500
MAX_SKILL_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024

REQUIRED_TRIGGER_CATEGORIES = {
    "bootstrap",
    "scan",
    "digest",
    "feedback",
    "capture_research",
}

REQUIRED_NON_TRIGGER_CATEGORIES = {
    "generic_procurement",
    "state_local_scan",
    "grants",
    "manual_report_edit",
    "credential_setup",
    "unrelated_federal_research",
}


def load_skill_text() -> str:
    return (BUNDLE_ROOT / "SKILL.md").read_text(encoding="utf-8")


def parse_frontmatter(skill_text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", skill_text, re.DOTALL)
    if not match:
        raise ValueError("SKILL.md is missing YAML frontmatter")

    frontmatter: dict[str, str] = {}
    for line in match.group(1).splitlines():
        if not line.strip():
            continue
        if ":" not in line:
            raise ValueError(f"Invalid frontmatter line: {line}")
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip('"').strip("'")
    return frontmatter


def extract_skill_root_paths(skill_text: str, directory: str) -> set[str]:
    pattern = rf"SKILL_ROOT/{re.escape(directory)}/[A-Za-z0-9._/-]+"
    return {match.removeprefix(f"SKILL_ROOT/{directory}/") for match in re.findall(pattern, skill_text)}


def validate_frontmatter(skill_text: str, failures: list[str]) -> dict[str, str]:
    try:
        frontmatter = parse_frontmatter(skill_text)
    except ValueError as exc:
        failures.append(str(exc))
        return {}

    if set(frontmatter) != {"name", "description"}:
        failures.append("SKILL.md frontmatter must contain exactly name and description")

    name = frontmatter.get("name", "")
    description = frontmatter.get("description", "")

    if name != SKILL_NAME:
        failures.append(f"skill name must be {SKILL_NAME}")
    if not re.fullmatch(r"[a-z0-9-]+", name):
        failures.append("skill name must use lowercase letters, digits, and hyphens only")
    if name.startswith("-") or name.endswith("-") or "--" in name:
        failures.append("skill name cannot start/end with hyphen or contain consecutive hyphens")
    if len(name) > MAX_SKILL_NAME_LENGTH:
        failures.append("skill name exceeds length limit")

    if len(description) > MAX_DESCRIPTION_LENGTH:
        failures.append("description exceeds 1024 characters")
    if "<" in description or ">" in description:
        failures.append("description must not contain angle brackets")

    lower_description = description.lower()
    required_terms = ["bootstrap", "scan", "digest", "feedback", "capture"]
    missing_terms = [term for term in required_terms if term not in lower_description]
    if missing_terms:
        failures.append(f"description missing trigger terms: {', '.join(missing_terms)}")

    return frontmatter


def validate_reference_triggers(skill_text: str, failures: list[str]) -> None:
    reference_files = sorted(path.name for path in (BUNDLE_ROOT / "references").glob("*.md"))
    linked_references = extract_skill_root_paths(skill_text, "references")
    missing_links = sorted(set(reference_files) - linked_references)
    if missing_links:
        failures.append(f"SKILL.md missing reference links: {', '.join(missing_links)}")

    missing_triggers = [
        name
        for name in reference_files
        if f"Read `SKILL_ROOT/references/{name}` when" not in skill_text
    ]
    if missing_triggers:
        failures.append(f"references missing explicit read triggers: {', '.join(missing_triggers)}")


def validate_examples(skill_text: str, failures: list[str]) -> None:
    example_files = sorted(path.name for path in (BUNDLE_ROOT / "examples").iterdir() if path.is_file())
    linked_examples = extract_skill_root_paths(skill_text, "examples")
    missing_examples = sorted(set(example_files) - linked_examples)
    if missing_examples:
        failures.append(f"SKILL.md missing example links: {', '.join(missing_examples)}")

    stale_examples = sorted(path for path in linked_examples if not (BUNDLE_ROOT / "examples" / path).exists())
    if stale_examples:
        failures.append(f"SKILL.md links to missing examples: {', '.join(stale_examples)}")


def validate_trigger_fixture(failures: list[str]) -> dict[str, Any]:
    fixture_path = BUNDLE_ROOT / "scripts" / "tests" / "fixtures" / "skill-trigger-eval.json"
    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        failures.append(f"cannot load trigger fixture: {exc}")
        return {}

    if fixture.get("schema") != "pwin-ai-opportunities.skill-trigger-eval/v1":
        failures.append("trigger fixture schema mismatch")
    if fixture.get("skill") != SKILL_NAME:
        failures.append("trigger fixture skill mismatch")

    cases = fixture.get("cases")
    if not isinstance(cases, list):
        failures.append("trigger fixture cases must be a list")
        return fixture
    if len(cases) < 20:
        failures.append("trigger fixture must include at least 20 cases")

    ids: set[str] = set()
    trigger_categories: set[str] = set()
    non_trigger_categories: set[str] = set()

    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            failures.append(f"trigger case {index} must be an object")
            continue

        case_id = case.get("id")
        prompt = case.get("prompt")
        expected_trigger = case.get("expected_trigger")
        category = case.get("category")

        if not isinstance(case_id, str) or not case_id:
            failures.append(f"trigger case {index} is missing id")
        elif case_id in ids:
            failures.append(f"duplicate trigger case id: {case_id}")
        else:
            ids.add(case_id)

        if not isinstance(prompt, str) or len(prompt.strip()) < 10:
            failures.append(f"trigger case {case_id or index} has an invalid prompt")
        if not isinstance(expected_trigger, bool):
            failures.append(f"trigger case {case_id or index} expected_trigger must be boolean")
        if not isinstance(category, str) or not category:
            failures.append(f"trigger case {case_id or index} is missing category")
        elif expected_trigger is True:
            trigger_categories.add(category)
        elif expected_trigger is False:
            non_trigger_categories.add(category)

    missing_trigger_categories = sorted(REQUIRED_TRIGGER_CATEGORIES - trigger_categories)
    if missing_trigger_categories:
        failures.append(f"trigger fixture missing positive categories: {', '.join(missing_trigger_categories)}")

    missing_non_trigger_categories = sorted(REQUIRED_NON_TRIGGER_CATEGORIES - non_trigger_categories)
    if missing_non_trigger_categories:
        failures.append(f"trigger fixture missing negative categories: {', '.join(missing_non_trigger_categories)}")

    return fixture


def validate_audit_doc(frontmatter: dict[str, str], failures: list[str]) -> None:
    audit_path = BUNDLE_ROOT / "docs" / "agent-skills-audit.md"
    if not audit_path.exists():
        failures.append("docs/agent-skills-audit.md is missing")
        return

    audit_text = audit_path.read_text(encoding="utf-8")
    required_phrases = [
        "pwin-ai-opportunities-engine",
        "pwin-ai-opportunities",
        "license",
        "compatibility",
        "metadata",
        "allowed-tools",
        "templates/",
        "assets/",
        "skills-ref",
        "OpenClaw",
        "Codex",
        "Claude Code",
    ]
    for phrase in required_phrases:
        if phrase not in audit_text:
            failures.append(f"audit doc missing phrase: {phrase}")

    if BUNDLE_ROOT.name != frontmatter.get("name") and BUNDLE_ROOT.name not in audit_text:
        failures.append("audit doc must record repo folder and install folder mismatch")


def validate_templates(failures: list[str]) -> None:
    template_files = sorted(path.name for path in (BUNDLE_ROOT / "templates").iterdir() if path.is_file())
    if not template_files:
        failures.append("templates directory must contain runtime templates")
        return

    for template_name in template_files:
        path = BUNDLE_ROOT / "templates" / template_name
        if path.stat().st_size == 0:
            failures.append(f"template is empty: {template_name}")


def validate_openai_metadata(failures: list[str]) -> None:
    metadata_path = BUNDLE_ROOT / "agents" / "openai.yaml"
    text = metadata_path.read_text(encoding="utf-8")
    if "$pwin-ai-opportunities" not in text:
        failures.append("agents/openai.yaml default_prompt must mention $pwin-ai-opportunities")

    match = re.search(r'^\s*short_description:\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if not match:
        failures.append("agents/openai.yaml missing quoted short_description")
        return

    short_description = match.group(1)
    if not 25 <= len(short_description) <= 64:
        failures.append("agents/openai.yaml short_description must be 25-64 characters")


def main() -> int:
    failures: list[str] = []
    skill_text = load_skill_text()
    line_count = len(skill_text.splitlines())
    if line_count > MAX_SKILL_LINES:
        failures.append(f"SKILL.md has {line_count} lines; limit is {MAX_SKILL_LINES}")

    frontmatter = validate_frontmatter(skill_text, failures)
    validate_reference_triggers(skill_text, failures)
    validate_examples(skill_text, failures)
    fixture = validate_trigger_fixture(failures)
    validate_audit_doc(frontmatter, failures)
    validate_templates(failures)
    validate_openai_metadata(failures)

    result = {
        "status": "OK" if not failures else "FAILED",
        "skill_name": frontmatter.get("name") if frontmatter else None,
        "repo_directory": BUNDLE_ROOT.name,
        "skill_line_count": line_count,
        "trigger_case_count": len(fixture.get("cases", [])) if isinstance(fixture, dict) else 0,
        "skills_ref_available": shutil.which("skills-ref") is not None,
        "failed_checks": failures,
    }
    print(json.dumps(result, ensure_ascii=True, indent=2))
    return 0 if not failures else 10


if __name__ == "__main__":
    raise SystemExit(main())

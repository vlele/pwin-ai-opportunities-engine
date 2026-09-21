"""Bounded stage-only live probe. Expectations never enter model messages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

SCRIPTS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SCRIPTS))
from common import semantic_contract as contract, openai_reasoning as reasoning


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n")


def grade_fixture(expected, parts):
    work = [p["text"] for p in parts if p["kind"] == "work"]
    errors = ["Core work missing: " + pattern for pattern in expected["work_patterns"]
              if not any(re.search(pattern, text, re.I) for text in work)]
    errors += ["Extraneous or condition-bearing work: " + text for text in work
               if any(re.search(pattern, text, re.I) for pattern in expected["forbidden_work_patterns"])]
    kinds = {p["kind"] for p in parts}
    errors += ["Missing condition kind: " + kind for kind in expected["required_condition_kinds"] if kind not in kinds]
    if work and parts[0]["kind"] != "work":
        errors.append("First component is not core work.")
    return errors


def jobs(h04_run, repeats):
    original = []
    for path in sorted((h04_run / "calls").glob("*.request.json")):
        request = read(path)
        payload = json.loads(request["messages"][-1]["content"])
        if set(payload) == {"requirements", "spans"} and isinstance(payload["requirements"], dict):
            original.append(payload)
    if len(original) != 1:
        raise ValueError("Expected one original decomposition request, not a correction-selected input.")
    h04 = {"id": "H04_failed_input", "payload": original[0], "checks": {}}
    for key, record in original[0]["requirements"].items():
        if record["record_kind"] == "requirement":
            h04["checks"][key] = {"work_patterns": ["pav|concrete.*place|place.*concrete"],
                "forbidden_work_patterns": ["reopen|closed|12|72"], "required_condition_kinds": ["timing"]}
        else:
            h04["checks"][key] = {"work_patterns": [], "forbidden_work_patterns": ["."], "required_condition_kinds": []}
    cases = [h04]
    for fixture in read(SCRIPTS / "tests/fixtures/core_work_decomposition_cases.json")["cases"]:
        anchor = {"ref": "D1:0", "quote": fixture["text"]}
        record = {"area": "scope", "status": "current", "task": bool(fixture["work_patterns"]),
                  "record_kind": "requirement", "supersedes": [], "meaning": fixture["focus"],
                  "focus": [{"ref": "D1:0", "quote": fixture["focus"]}], "evidence": [anchor]}
        payload = {"requirements": {"R0": record}, "spans": {
            "D1:0": {"kind": "package", "source_id": "D1", "offset": 0, "text": fixture["text"]}}}
        cases.append({"id": fixture["id"], "payload": payload, "checks": {"R0": fixture}})
    return [{**case, "repeat": repeat} for case in cases for repeat in range(1, repeats + 1)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--h04-run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="gpt-5.4-2026-03-05")
    parser.add_argument("--repeats", type=int, choices=(1, 2, 3), default=3)
    parser.add_argument("--live", action="store_true", help="Required to authorize bounded provider calls.")
    args = parser.parse_args()
    if not args.live:
        parser.error("No provider calls without --live.")
    if not os.environ.get("OPENAI_API_KEY", "").strip():
        raise SystemExit("OPENAI_API_KEY unavailable; no calls made.")
    planned = jobs(args.h04_run, args.repeats)
    args.output.mkdir(parents=True, exist_ok=False)
    hashes = {str(p.relative_to(SCRIPTS)): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in SCRIPTS.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    save(args.output / "runtime-hashes.json", hashes)
    save(args.output / "plan.json", {"jobs": planned, "model": args.model, "reasoning_effort": "low",
         "retries": 0, "scope": "Decomposer only, no vendor fitting or auditing. Fixture lexical checks require manual semantic review."})
    client = reasoning._openai_client()
    if client is None:
        raise SystemExit("Provider client unavailable; no calls made.")
    client = client.with_options(max_retries=0, timeout=120)
    results = []
    for job in planned:
        folder = args.output / f"{job['id']}-r{job['repeat']}"
        payload = job["payload"]
        inventory = {"requirements": list(payload["requirements"].values())}
        request = {"model": args.model, "reasoning_effort": "low",
                   "messages": [{"role": "system", "content": contract.DECOMPOSE_PROMPT},
                                {"role": "user", "content": json.dumps(payload)}],
                   "response_format": {"type": "json_schema", "json_schema": {"name": "capture_understanding",
                       "schema": contract.decomposition_schema(inventory["requirements"], payload["spans"]), "strict": True}}}
        save(folder / "request.json", request)
        try:
            response = client.chat.completions.create(**request)
        except Exception as error:
            body = getattr(error, "body", {}) or {}
            detail = body.get("error", body) if isinstance(body, dict) else {}
            problem = {"case": job["id"], "repeat": job["repeat"], "pass": False,
                       "provider_error": type(error).__name__, "status": getattr(error, "status_code", None),
                       "provider_code": detail.get("code")}
            results.append(problem)
            save(folder / "provider-error.json", problem)
            save(args.output / "results.json", results)
            print(json.dumps(problem), flush=True)
            break
        save(folder / "response.json", response.model_dump())
        try:
            raw = json.loads(response.choices[0].message.content)
            result = contract.apply_decomposition(inventory, raw, payload["spans"])
            errors = [f"{key}: {error}" for key, expected in job["checks"].items()
                      for error in grade_fixture(expected, result["requirements"][int(key[1:])]["components"])]
            save(folder / "decomposition.json", result)
        except (ValueError, TypeError, KeyError) as error:
            errors = ["Contract error: " + str(error)]
        row = {"case": job["id"], "repeat": job["repeat"], "pass": not errors, "errors": errors,
               "usage": response.model_dump().get("usage"), "model": response.model}
        results.append(row)
        save(args.output / "results.json", results)
        print(json.dumps({k: v for k, v in row.items() if k != "usage"}), flush=True)
    current = {str(p.relative_to(SCRIPTS)): hashlib.sha256(p.read_bytes()).hexdigest()
               for p in SCRIPTS.rglob("*") if p.is_file() and "__pycache__" not in p.parts}
    assert current == hashes, "Runtime changed during probe."
    summary = {"planned": len(planned), "completed": len(results), "passes": sum(r["pass"] for r in results),
               "manual_review_required": True, "full_pipeline_test": False}
    save(args.output / "summary.json", summary)
    print(json.dumps(summary), flush=True)
    raise SystemExit(0 if len(results) == len(planned) and all(r["pass"] for r in results) else 1)


if __name__ == "__main__":
    main()

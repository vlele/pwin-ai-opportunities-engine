"""Frozen-input semantic classification checks, never predetermined pursuit scores.

The mechanical grader checks declared dimensions, routing and fact retention.
It does NOT certify entailment or question quality: those require recorded review.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "scripts/tests/fixtures/semantic_classification_cases.json"
VENDOR_KINDS = {"vendor_experience", "vendor_role", "company_identity", "vendor_scale", "vendor_recency", "vendor_eligibility"}
SCORECARD_VERSION = 4
DECISIONS = ROOT / "scripts/tests/fixtures/semantic_decision_expectations.json"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grade_semantic_expectations(expected, state):
    if not expected:
        return []
    plan = state.get("understanding_audit", {}).get("semantic_plan")
    if not isinstance(plan, dict):
        return ["missing_claim_level_semantic_plan"]
    claims, requirements, edges = (plan.get(k, []) for k in ("claims", "requirements", "comparisons"))
    errors = []
    def claim_ids(quote):
        return {i for i, c in enumerate(claims) if quote.lower() in " ".join(a["quote"] for a in c.get("evidence", [])).lower()}
    for item in expected.get("claims", []):
        ids = claim_ids(item["quote"])
        acceptable = [i for i in ids if all(claims[i].get(k) == v for k, v in item.items() if k != "quote")]
        if not acceptable:
            errors.append("wrong_claim_classification:" + item["quote"])
    for item in expected.get("tasks", []):
        ids = claim_ids(item["claim_quote"])
        rids = {i for i, r in enumerate(requirements) if item["requirement_quote"].lower() in r.get("meaning", "").lower() and r.get("status", "current") == "current"}
        candidates = [e for e in edges if e["claim"] in ids and e["requirement"] in rids]
        def correct(edge):
            if edge.get("relationship") != item["relationship"]:
                return False
            if "coverage_allowed" in item and edge.get("coverage") not in item["coverage_allowed"]:
                return False
            if "work_pattern" in item:
                parts = requirements[edge["requirement"]].get("components", [])
                matches = [f"K{i}" for i, p in enumerate(parts) if p["kind"] == "work" and re.search(item["work_pattern"], p["text"], re.I)]
                return bool(matches) and all(edge.get("component_findings", {}).get(k, {}).get("status") in item["work_states"] for k in matches)
            return True
        if not any(correct(e) for e in candidates):
            errors.append("wrong_task_decision:" + item["requirement_quote"])
    for item in expected.get("no_positive_tasks", []):
        rids = {i for i, r in enumerate(requirements) if item["requirement_quote"].lower() in r.get("meaning", "").lower()}
        candidates = [e for e in edges if e["requirement"] in rids]
        def unsupported(edge):
            if "work_pattern" not in item:
                return edge.get("relationship") in {"same_task", "applicable_different_task"}
            parts = requirements[edge["requirement"]].get("components", [])
            keys = [f"K{i}" for i, p in enumerate(parts) if p["kind"] == "work" and re.search(item["work_pattern"], p["text"], re.I)]
            return not keys or any(edge.get("component_findings", {}).get(k, {}).get("status") in {"matched", "partial", "transferable"} for k in keys)
        if not candidates or any(unsupported(e) for e in candidates):
            errors.append("unsupported_task_credit_or_missing_comparison:" + item["requirement_quote"])
    for item in expected.get("pricing", []):
        matching = [r for r in requirements if item["requirement_quote"].lower() in r.get("meaning", "").lower() and r.get("status") == "current"]
        def allocated(record, part):
            compound = any(other != item and other["requirement_quote"].lower() in record.get("meaning", "").lower() for other in expected["pricing"])
            return part["kind"] == "pricing" and re.search(item["pricing_pattern"], part["text"], re.I) and (
                not compound or item["requirement_quote"].lower() in part["text"].lower())
        if not any(any(allocated(r, p) for p in r.get("components", [])) for r in matching):
            errors.append("missing_line_item_pricing:" + item["requirement_quote"])
    for item in expected.get("records", []):
        if not any(item["quote"].lower() in r.get("meaning", "").lower() and
                   all(r.get(k) == v for k, v in item.items() if k != "quote") for r in requirements):
            errors.append("wrong_requirement_record:" + item["quote"])
    return errors


def grade_case(case, state):
    errors = []
    if state.get("status") == "TECHNICAL_BLOCKED":
        return {"pass": False, "errors": ["technical_block"], "manual_review_required": True}
    if state.get("status") not in case["statuses"]:
        errors.append("wrong_clarification_route_or_missed_ambiguity")
    findings = state.get("questions", []) + state.get("open_gaps", [])
    # Work-relevance expectations do not classify unrelated identity/date/preference rows.
    vendor = [r for r in findings if r.get("record_type") != "question" and (
              r.get("claim", {}).get("subject") in {"performed_work", "work_reference", "capability"}
              or ("claim" not in r and r.get("kind") == "vendor_experience"))]
    supplied = [r for r in vendor if r.get("claim", {}).get("basis") != "not_supplied"]
    if supplied:
        # Missing extra coverage is not a second claim contradicting known work.
        for row in vendor:
            if row.get("claim", {}).get("basis") == "not_supplied" and row.get("relevance") != "unknown":
                errors.append("absent_work_received_credit_or_inability_label")
        vendor = supplied
    if case["relevance"] and not vendor:
        errors.append("missing_vendor_classification")
    for index, row in enumerate(vendor):
        for field, expected in (("relevance", case["relevance"]), ("ambiguity", case["ambiguity"]),
                                ("verification_status", case["verification"])):
            if expected and row.get(field) not in expected:
                errors.append(f"vendor[{index}].{field}:{row.get(field)}")
    if case["question_kinds"] and not any(q.get("kind") in case["question_kinds"] for q in state.get("questions", [])):
        errors.append("missing_required_targeted_question")
    text = " ".join(r["text"] for r in state.get("interpretation", [])) + " " + " ".join(
        r.get("statement", "") for r in state.get("understanding_audit", {}).get("facts", []))
    for pattern in case["facts"]:
        if not re.search(pattern, text, flags=re.I):
            errors.append("required_fact_not_retained:" + pattern)
    errors.extend(grade_semantic_expectations(case.get("semantic_expectations", {}), state))
    return {"pass": not errors, "errors": errors, "manual_review_required": True}


def prepare(folder, repeats):
    (folder / "inputs").mkdir(parents=True, exist_ok=False)
    shutil.copytree(ROOT / "scripts", folder / "runtime-scripts", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    cases = read(FIXTURE)["cases"]
    decisions = read(DECISIONS)
    for case in cases:
        if case["id"] in decisions:
            case["semantic_expectations"] = decisions[case["id"]]
    save(folder / "cases.json", cases)
    manifests = []
    for case in cases:
        sources = {f"D{i}": {"kind": "package", "filename": f"document-{i}.txt", "text": text}
                   for i, text in enumerate(case["documents"], 1)}
        if case["profile"]:
            sources["V1"] = {"kind": "profile", "profile_field": "reported_experience", "text": case["profile"],
                             "provenance": "profile_reported_not_independently_verified"}
        packet = {"sources": sources, "technical_issues": [], "profile_present": bool(case["profile"]),
                  "opportunity": {"title": "Procurement package"}}
        for repeat in range(1, repeats + 1):
            path = folder / "inputs" / f"{case['id']}-focused-r{repeat}" / "audit/understanding-input.json"
            save(path, packet)
            manifests.append({"case": case["id"], "repeat": repeat, "path": str(path.relative_to(folder)), "sha256": digest(path)})
    runtime = {str(p.relative_to(folder)): digest(p) for p in (folder / "runtime-scripts").rglob("*") if p.is_file()}
    save(folder / "frozen-manifest.json", {"fixture_sha256": digest(folder / "cases.json"), "inputs": manifests, "runtime": runtime})
    print(json.dumps({"cases": len(cases), "repeats": repeats, "folder": str(folder)}))


def verify_frozen(folder):
    manifest = read(folder / "frozen-manifest.json")
    if digest(folder / "cases.json") != manifest["fixture_sha256"]:
        raise ValueError("Frozen expectations changed.")
    for relative, expected in manifest["runtime"].items():
        if digest(folder / relative) != expected:
            raise ValueError("Frozen runtime changed: " + relative)
    for row in manifest["inputs"]:
        if digest(folder / row["path"]) != row["sha256"]:
            raise ValueError("Frozen packet changed: " + row["path"])


def summarize(folder, label):
    run_root = folder / label
    plan = read(run_root / "plan.json")
    cases = {c["id"]: c for c in read(folder / "cases.json")}
    grades, usage, models, reviews = [], Counter(), Counter(), []
    for job in plan["jobs"]:
        case = cases[job["case"]]
        path = run_root / f"{job['case']}-r{job['repeat']}"
        if not (path / "state.json").exists():
            grades.append({"case": case["id"], "repeat": job["repeat"], "pass": False, "errors": ["missing_run"], "status": "MISSING"})
            continue
        state = read(path / "state.json")
        grade = grade_case(case, state)
        if digest(path / "packet.json") != job["sha256"]:
            grade["pass"] = False
            grade["errors"].append("packet_hash_mismatch")
        grades.append({"case": case["id"], "repeat": job["repeat"], "status": state["status"], **grade})
        findings = state["questions"] + state["open_gaps"]
        reviews.append({"case": case["id"], "repeat": job["repeat"], "rubric": case["rubric"],
                        "status": state["status"], "interpretation": [r["text"] for r in state["interpretation"]],
                        "findings": [{k: r.get(k) for k in ("kind", "claim", "comparison", "task_alignment", "clarification", "routing_reason", "relevance", "ambiguity", "verification_status", "question", "current_interpretation", "decision_impact", "evidence_check")} for r in findings],
                        "claim_evidence": state.get("understanding_audit", {}).get("claim_evidence", {}),
                        "technical_issues": state["technical_issues"]})
        for p in path.glob("calls/*.response.json"):
            response = read(p)
            models[response["model"]] += 1
            u = response.get("usage", {})
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                usage[key] += u.get(key, 0)
            usage["reasoning_tokens"] += (u.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
    summary = {"scorecard_version": SCORECARD_VERSION,
               "automatic_passes": sum(r["pass"] for r in grades), "expected_runs": len(plan["jobs"]),
               "statuses": dict(Counter(r["status"] for r in grades)), "response_models": dict(models), "usage": dict(usage),
               "release_verdict": "NOT_PROVEN_AWAITING_SEMANTIC_REVIEW" if all(r["pass"] for r in grades) else "FAIL",
               "grades": grades}
    save(run_root / "grades.json", summary)
    save(run_root / "review-data.json", reviews)
    print(json.dumps({k: v for k, v in summary.items() if k != "grades"}, indent=2))
    return summary


def main():
    p = argparse.ArgumentParser()
    p.add_argument("mode", choices=("prepare", "run", "grade"))
    p.add_argument("--folder", required=True, type=Path)
    p.add_argument("--label", default="candidate")
    p.add_argument("--split", choices=("known", "sealed"), default="known")
    p.add_argument("--model")
    p.add_argument("--effort", choices=("low", "medium", "high"), default="low")
    p.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    p.add_argument("--concurrency", type=int, choices=range(1, 5), default=3)
    args = p.parse_args()
    if args.mode == "prepare":
        prepare(args.folder, args.repeats)
        return
    verify_frozen(args.folder)
    if args.mode == "run":
        if not args.model:
            p.error("--model required for explicit candidate selection")
        env = dict(os.environ, PWIN_UNDERSTANDING_MODEL=args.model, PWIN_UNDERSTANDING_REASONING_EFFORT=args.effort)
        cases = ",".join(c["id"] for c in read(args.folder / "cases.json") if c["split"] == args.split)
        command = [sys.executable, str(args.folder / "runtime-scripts/tests/run_understanding_replay.py"),
                   "--baseline", str(args.folder / "inputs"), "--cases", cases, "--repeats", str(args.repeats),
                   "--concurrency", str(args.concurrency), "--output", str(args.folder / args.label)]
        result = subprocess.run(command, env=env)
        if result.returncode:
            raise SystemExit(result.returncode)
    summary = summarize(args.folder, args.label)
    raise SystemExit(1 if summary["release_verdict"] == "FAIL" else 0)


if __name__ == "__main__":
    main()

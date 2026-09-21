"""Audit-only adversarial controls: challenge exact claims, not their source-ID syntax."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import capture_understanding as u
from common.openai_reasoning import _call_openai_json

FIXTURE = Path(__file__).parent / "fixtures/claim_evidence_cases.json"


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def inputs(case):
    sources = {f"D{i}": {"kind": "package", "text": text, "filename": f"document-{i}.txt"}
               for i, text in enumerate(case["documents"], 1)}
    if case["profile"]:
        sources["V1"] = {"kind": "profile", "text": case["profile"], "profile_field": "reported_experience"}
    spans = u.build_spans({"sources": sources})
    row = deepcopy(case["target"])
    if "claim" in row:
        for key, value in {"kind": "vendor_experience", "owner": "user", "action": "record_gap", "question": "", "options": [],
                           "affected_decisions": ["past_performance"], "decision_impact": "Determines whether the supplied work earns experience credit."}.items():
            row.setdefault(key, value)
        raw = {"interpretation": [], "uncertainties": [row, *deepcopy(case.get("additional_targets", []))]}
    else:
        raw = {"interpretation": [row], "uncertainties": []}
    return u.claim_targets(raw, spans), spans


def audit_request(targets, spans, model, effort="low"):
    return {"system_prompt": u.CLAIM_AUDIT_PROMPT, "user_payload": {"targets": u.audit_components(targets)},
            "model": model, "reasoning_effort": effort, "timeout_seconds": 120,
            "response_schema": {"name": "capture_understanding", "schema": u.claim_audit_schema(targets, spans), "strict": True}}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fixture", type=Path, default=FIXTURE)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--model", required=True)
    parser.add_argument("--effort", choices=("low", "medium", "high"), default="low")
    parser.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    parser.add_argument("--concurrency", type=int, choices=range(1, 5), default=3)
    args = parser.parse_args()
    if not args.live:
        parser.error("--live required; this benchmark uses API credits")
    args.output.mkdir(parents=True, exist_ok=False)
    cases = json.loads(args.fixture.read_text())["cases"]
    save(args.output / "plan.json", {"model": args.model, "reasoning_effort": args.effort, "repeats": args.repeats,
                                     "fixture_sha256": hashlib.sha256(args.fixture.read_bytes()).hexdigest(),
                                     "implementation_sha256": hashlib.sha256(Path(u.__file__).read_bytes()).hexdigest(),
                                     "auditor_sha256": hashlib.sha256(Path(u.__file__).with_name("claim_audit.py").read_bytes()).hexdigest(),
                                     "note": "Single audit call per sample, no provider retry, no expected outcome in request."})

    def run(case, repeat):
        folder = args.output / f"{case['id']}-r{repeat}"
        targets, spans = inputs(case)
        request = audit_request(targets, spans, args.model, args.effort)
        save(folder / "request.json", request)
        raw = _call_openai_json(**request)
        save(folder / "response.json", raw)
        try:
            if raw is None:
                raise ValueError("Provider unavailable or invalid JSON; no semantic judgment returned.")
            audited = u.validate_claim_audit(raw, targets, spans)
            result = {"case": case["id"], "repeat": repeat, "expected_accept": case["expected_pass"],
                      "actual_accept": audited["passed"], "pass": audited["passed"] == case["expected_pass"], "audit": audited}
        except (ValueError, KeyError, TypeError) as error:
            result = {"case": case["id"], "repeat": repeat, "pass": False, "technical_error": str(error)}
        save(folder / "result.json", result)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        jobs = [pool.submit(run, case, repeat) for case in cases for repeat in range(1, args.repeats + 1)]
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            save(args.output / "results.json", results)
            print(json.dumps({k: v for k, v in result.items() if k != "audit"}), flush=True)
    summary = {"passes": sum(r["pass"] for r in results), "runs": len(results),
               "false_accepts": sum(r.get("actual_accept") is True and r.get("expected_accept") is False for r in results),
               "false_rejects": sum(r.get("actual_accept") is False and r.get("expected_accept") is True for r in results),
               "technical_failures": sum("technical_error" in r for r in results)}
    save(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

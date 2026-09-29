"""Frozen adversarial semantic plans, including both false claims and honest gaps."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import semantic_plan as s
from common.semantic_contract import audit_payload
from common.openai_reasoning import _openai_client
from fixtures.semantic_plan_cases import cases


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=True) + "\n")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--effort", choices=("low", "medium", "high"), default="low")
    p.add_argument("--repeats", type=int, choices=range(1, 4), default=3)
    p.add_argument("--concurrency", type=int, choices=range(1, 5), default=3)
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    if not args.live:
        p.error("--live is required for paid calls")
    args.output.mkdir(parents=True, exist_ok=False)
    fixture = cases()
    save(args.output / "fixtures.json", fixture)
    frozen = []
    for case in fixture:
        plan = s.validate(case["plan"], case["spans"])
        targets = s.audit_records(plan, case["spans"])
        requests = []
        batches = list(s.audit_batches(targets, case["spans"]))
        for batch in batches:
            requests.append({"model": args.model, "reasoning_effort": args.effort,
                             "messages": [{"role": "system", "content": s.audit_prompt(batch)},
                                          {"role": "user", "content": json.dumps(audit_payload(batch, case["spans"]))}],
                             "response_format": {"type": "json_schema", "json_schema": {"name": "semantic_plan_audit", "schema": s.audit_schema(batch), "strict": True}}})
        frozen.append((case, targets, batches, requests))
    save(args.output / "plan.json", {"model": args.model, "effort": args.effort, "repeats": args.repeats,
                                     "implementation_sha256": hashlib.sha256(Path(s.__file__).read_bytes()).hexdigest(),
                                     "fixture_sha256": hashlib.sha256((args.output / "fixtures.json").read_bytes()).hexdigest(),
                                     "note": "No expected decisions in model payload; homogeneous bounded audit batches, no automatic retry."})

    def run(case, targets, batches, requests, repeat):
        folder = args.output / f"{case['id']}-r{repeat}"
        save(folder / "requests.json", requests)
        result = {"case": case["id"], "repeat": repeat, "expected_accept": case["expected_accept"]}
        try:
            client = _openai_client()
            if client is None:
                raise ValueError("No provider client")
            checks, usage, models = {}, Counter(), Counter()
            for index, (batch, request) in enumerate(zip(batches, requests), 1):
                response = client.with_options(max_retries=0, timeout=120).chat.completions.create(**request)
                save(folder / f"response-{index}.json", response.model_dump())
                checked = s.validate_audit(json.loads(response.choices[0].message.content), batch)
                checks.update(s.audit_responses(checked["checks"]))
                models[response.model] += 1
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    usage[key] += getattr(response.usage, key)
            audit = s.validate_audit({"checks": checks}, targets)
            result.update(actual_accept=audit["passed"], audit=audit, usage=dict(usage), response_models=dict(models), model=response.model,
                          passed=audit["passed"] == case["expected_accept"])
        except Exception as error:
            # Do not persist arbitrary provider exception strings, which may contain secrets.
            result.update(passed=False, technical_error=type(error).__name__)
        save(folder / "result.json", result)
        return result

    results = []
    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        jobs = [pool.submit(run, c, t, b, r, repeat) for c, t, b, r in frozen for repeat in range(1, args.repeats + 1)]
        for job in as_completed(jobs):
            result = job.result()
            results.append(result)
            save(args.output / "results.json", results)
            print(json.dumps({k: v for k, v in result.items() if k not in {"audit", "usage"}}), flush=True)
    usage = Counter()
    for r in results:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            usage[key] += r.get("usage", {}).get(key, 0)
    summary = {"passes": sum(r["passed"] for r in results), "runs": len(results),
               "false_accepts": sum(r.get("actual_accept") is True and not r["expected_accept"] for r in results),
               "false_rejects": sum(r.get("actual_accept") is False and r["expected_accept"] for r in results),
               "technical_failures": sum("technical_error" in r for r in results), "usage": dict(usage)}
    save(args.output / "summary.json", summary)
    print(json.dumps(summary, indent=2))
    raise SystemExit(0 if all(r["passed"] for r in results) else 1)


if __name__ == "__main__":
    main()

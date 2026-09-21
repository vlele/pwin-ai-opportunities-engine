"""Opt-in live capture benchmark. Fixtures and keys stay outside the repository."""
from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def hashes(root):
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"}


def prepare(config, root, skill):
    if (root / "plan.json").exists():
        raise RuntimeError("Benchmark already prepared; use a new output or resume it.")
    root.mkdir(parents=True, exist_ok=True)
    for name in ("scripts", "templates", "references", "assets"):
        if (skill / name).exists():
            shutil.copytree(skill / name, root / "skill" / name, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    plan = copy.deepcopy(config)
    plan["created_at"] = datetime.now(timezone.utc).isoformat()
    plan["skill_hashes"] = hashes(root / "skill")
    plan["source_hashes"] = hashes(skill / "scripts")
    plan["source_skill"] = str(skill)
    plan["protected_hashes"] = {p: hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in config.get("protected_files", [])}
    for family in plan["families"]:
        target = root / "inputs" / family["id"]
        target.mkdir(parents=True)
        copied = []
        for source in family["files"]:
            dest = target / Path(source).name
            shutil.copy2(source, dest)
            copied.append(str(dest))
        family["files"] = copied
    plan["input_hashes"] = hashes(root / "inputs")
    write(root / "plan.json", plan)
    print(json.dumps({"prepared": str(root), "planned_runs": len(plan["families"]) * 4 * plan["repeats"]}), flush=True)


def case(root, family_id, condition, repeat):
    plan = read(root / "plan.json")
    family = next(f for f in plan["families"] if f["id"] == family_id)
    name = f"{family_id}-{condition}-r{repeat}"
    workspace = root / "runs" / name
    audit = workspace / "audit"
    audit.mkdir(parents=True, exist_ok=True)
    procurement = workspace / "procurement"
    write(procurement / "vendor-profile.json", family["profiles"][condition])
    preferences = read(root / "skill/templates/preferences.template.json")
    preferences["soft_preferences"]["positive_keywords"] = []
    preferences["soft_preferences"]["negative_keywords"] = []
    write(procurement / "preferences.json", preferences)
    os.environ["PWIN_REASONING_MODEL"] = plan["model"]
    os.environ["PWIN_REASONING_TIMEOUT_SECONDS"] = "240"
    sys.path.insert(0, str(root / "skill/scripts"))
    capture = importlib.import_module("capture.run_capture_research")
    reasoning = importlib.import_module("common.openai_reasoning")
    cache = root / "evidence" / family_id
    cache.mkdir(parents=True, exist_ok=True)
    events = []
    boundaries = ("load_local_attachments", "fetch_url_excerpt", "fetch_public_research", "enrich_from_usaspending", "enrich_capture_context")
    for stage in boundaries:
        original = getattr(capture, stage)

        def boundary(*args, _stage=stage, _original=original, **kwargs):
            path = cache / (_stage + ".json")
            if path.exists():
                output = read(path)["output"]
            elif family.get("evidence_cache"):
                output = read(Path(family["evidence_cache"]) / (_stage + ".json"))["output"]
                write(path, {"mode": "frozen_prior_boundary", "output": output})
            elif _stage == "load_local_attachments":
                output = _original(*args, **kwargs)
                write(path, {"mode": "fresh_local_extraction", "output": output})
            else:
                output = {"status": "not_attempted_controlled_test", "source_log": [], "evidence_gaps": ["No new external research in this controlled profile experiment."]}
                if _stage == "enrich_capture_context":
                    output.update(matches=[], evidence_models=[], source_statuses=[], competitive_landscape=[], vehicle_signals=[], related_procurements=[], next_questions=[], issues=[])
                write(path, {"mode": "research_disabled", "output": output})
            events.append({"stage": _stage, "output_hash": digest(output)})
            write(audit / "boundary-events.json", events)
            return copy.deepcopy(output)
        setattr(capture, stage, boundary)

    original_client = reasoning._openai_client

    class Client:
        def __init__(self, client):
            self.client = client

        def with_options(self, **options):
            configured = self.client.with_options(**options)

            def create(**request):
                write(audit / "model-request.json", request)
                try:
                    response = configured.chat.completions.create(**request)
                except Exception as error:
                    write(audit / "model-error.json", {"error_type": type(error).__name__, "status_code": getattr(error, "status_code", None)})
                    raise
                write(audit / "model-response.json", {"model": response.model, "id": response.id, "usage": response.usage.model_dump() if response.usage else None})
                return response
            return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))

    def client_factory():
        client = original_client()
        return Client(client) if client else None
    reasoning._openai_client = client_factory
    original_call = reasoning._call_openai_json

    def call(**kwargs):
        write(audit / "reasoning-input.json", kwargs)
        result = original_call(**kwargs)
        write(audit / "reasoning-output.json", result)
        return result
    reasoning._call_openai_json = call
    argv = ["run_capture_research.py", "--workspace", str(workspace), "--title", family["title"], "--buyer", family["buyer"], "--solicitation-number", family["solicitation_number"], "--summary", family["summary"], "--depth", "full_360"]
    for path in family["files"]:
        argv += ["--file", path]
    write(audit / "invocation.json", {"argv": argv, "profile_hash": digest(family["profiles"][condition])})
    sys.argv = argv
    return capture.main()


def run(root):
    if not os.environ.get("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY missing; no silent heuristic-only benchmark allowed")
    plan = read(root / "plan.json")
    results = []
    for family in plan["families"]:
        for condition in ("adjacent", "strong", "poor", "missing"):
            for repeat in range(1, plan["repeats"] + 1):
                name = f"{family['id']}-{condition}-r{repeat}"
                audit = root / "runs" / name / "audit"
                audit.mkdir(parents=True, exist_ok=True)
                if (audit / "result.json").exists():
                    results.append(read(audit / "result.json"))
                    continue
                print(json.dumps({"started": name}), flush=True)
                with (audit / "stdout.log").open("w") as out, (audit / "stderr.log").open("w") as err:
                    try:
                        proc = subprocess.run([sys.executable, str(Path(__file__).resolve()), "case", "--root", str(root), "--family", family["id"], "--condition", condition, "--repeat", str(repeat)], stdout=out, stderr=err, timeout=1500)
                        code = proc.returncode
                    except subprocess.TimeoutExpired:
                        code = 124
                result = {}
                for line in reversed((audit / "stdout.log").read_text().splitlines()):
                    try:
                        parsed = json.loads(line)
                        if isinstance(parsed, dict) and "status" in parsed:
                            result = parsed
                            break
                    except ValueError:
                        pass
                result.update(case=name, family=family["id"], condition=condition, repeat=repeat, process_exit_code=code)
                write(audit / "result.json", result)
                results.append(result)
                write(root / "results.json", results)
                print(json.dumps({"finished": name, "status": result.get("status", "FAILED")}), flush=True)
    analyze(root)


def analyze(root):
    plan = read(root / "plan.json")
    rows = []
    for path in sorted((root / "runs").glob("*/audit/result.json")):
        result = read(path)
        if not result.get("evidence_path"):
            rows.append({**result, "checks": {"capture_completed": False}})
            continue
        evidence = read(result["evidence_path"])
        brief = Path(result["brief_path"]).read_text()
        model = evidence.get("capture_reasoning_model", {})
        fit = model.get("vendor_fit_assessment", {})
        strategy = evidence.get("win_strategy", {})
        decision = evidence["pursuit_recommendation"]
        audit = path.parent
        meta = read(audit / "model-response.json") if (audit / "model-response.json").exists() else {}
        themes = strategy.get("win_theme_rows", [])
        discriminators = strategy.get("discriminator_rows", [])
        positive_themes = [row for row in themes if row.get("evidence_anchor")]
        positive_discriminators = [row for row in discriminators if row.get("evidence_anchor")]
        checks = {"capture_completed": True, "live_model": bool(meta.get("id")),
                  "all_sections": len(set(re.findall(r"^## (\d+)\.", brief, re.M))) == 18,
                  "fit_contract_valid": not fit.get("validation_issues"),
                  "no_unanchored_company_rows": all(r.get("requirement_ids") and r.get("vendor_evidence_ids") for r in positive_themes + positive_discriminators)}
        if result["condition"] == "poor":
            checks.update(no_bid=decision["recommendation"] == "No-bid", unrelated_performance_zero=fit.get("past_performance_score") == 0,
                          no_false_company_advantages=not positive_themes and not positive_discriminators,
                          no_false_proof_points=not evidence.get("capability_fit_analysis", {}).get("proof_points"))
        elif result["condition"] == "missing":
            checks.update(unknown_not_rejected=fit.get("status") == "unknown", qualification_pending=decision["recommendation"] == "Monitor only",
                          no_false_company_advantages=not positive_themes and not positive_discriminators)
        elif result["condition"] == "strong":
            checks.update(positive_fit=fit.get("status") in {"fit", "adjacent"}, relevant_performance_credit=fit.get("past_performance_score", 0) > 0, supported_themes_present=bool(positive_themes))
        elif result["condition"] == "adjacent":
            checks.update(contribution_recognized=bool(fit.get("supported_workshare")))
        family = next(f for f in plan["families"] if f["id"] == result["family"])
        types = evidence.get("solicitation_facts", {}).get("contract_types", [])
        if family.get("expected_contract_types"):
            checks["contract_types_preserved"] = set(types) == set(family["expected_contract_types"])
        model_input = read(audit / "reasoning-input.json")["user_payload"]
        model_input.pop("vendor_profile", None)
        model_input.pop("heuristic_capture_strategy", None)
        if "fit_evidence_catalog" in model_input:
            model_input["fit_evidence_catalog"].pop("vendor_evidence", None)
        rows.append({**result, "fit_status": fit.get("status"), "fit_summary": fit.get("summary"), "fit_issues": fit.get("validation_issues"),
                     "recommendation": decision["recommendation"], "total": decision["score_total"], "performance": fit.get("past_performance_score"), "capability": fit.get("capability_score"),
                     "theme_count": len(positive_themes), "discriminator_count": len(positive_discriminators), "checks": checks,
                     "facts_hash": digest(evidence["solicitation_facts"]), "nonprofile_payload_hash": digest(model_input), "boundary_hash": digest(read(audit / "boundary-events.json")),
                     "model": meta.get("model"), "usage": meta.get("usage"), "contract_types": types})
    invariants = {}
    for family in plan["families"]:
        subset = [row for row in rows if row["family"] == family["id"] and row.get("facts_hash")]
        for key in ("facts_hash", "nonprofile_payload_hash", "boundary_hash"):
            invariants[f"{family['id']}_{key}"] = len({row[key] for row in subset}) == 1
    invariants["snapshot_unchanged"] = hashes(root / "skill") == plan["skill_hashes"]
    invariants["inputs_unchanged"] = hashes(root / "inputs") == plan["input_hashes"]
    invariants["real_profiles_unchanged"] = all(hashlib.sha256(Path(p).read_bytes()).hexdigest() == h for p, h in plan["protected_hashes"].items())
    stable = []
    for family in plan["families"]:
        for condition in ("adjacent", "strong", "poor", "missing"):
            subset = [r for r in rows if r["family"] == family["id"] and r["condition"] == condition]
            verdicts = sorted({r.get("recommendation", "FAILED") for r in subset})
            successful_samples = sum(bool(r["checks"].get("live_model")) for r in subset)
            stable.append({"family": family["id"], "condition": condition, "samples": successful_samples, "recommendations": verdicts, "stable": len(verdicts) == 1 and successful_samples == plan["repeats"]})
    report = {"runs": rows, "invariants": invariants, "stability": stable, "expected_runs": len(plan["families"]) * 4 * plan["repeats"]}
    write(root / "comparison.json", report)
    lines = ["# Profile Decision Regression Benchmark", "", "Synthetic profiles only. No real company qualifications changed. Current opportunity availability is not established.", "", "| Family | Profile | Repeat | Fit | Recommendation | PP | Themes | Checks |", "|---|---|---:|---|---|---:|---:|---|"]
    for row in rows:
        bad = [k for k, v in row["checks"].items() if not v]
        lines.append(f"| {row['family']} | {row['condition']} | {row['repeat']} | {row.get('fit_status')} | {row.get('recommendation')} | {row.get('performance')} | {row.get('theme_count')} | {', '.join(bad) or 'PASS'} |")
    lines += ["", "## Invariants", *[f"- {'PASS' if v else 'FAIL'}: {k}" for k, v in invariants.items()], "", "## Stability", *[f"- {r['family']} / {r['condition']}: {r['samples']} samples; {', '.join(r['recommendations'])}; stable={r['stable']}" for r in stable], "", "## Audit", "Each runs/<case>/audit folder contains the exact model prompt, payload, raw response, API model and usage, and boundary evidence hashes. Capture memo/evidence paths are in result.json. No predetermined total-score targets are used."]
    (root / "COMPARISON.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"report": str(root / "COMPARISON.md"), "completed": len(rows), "failed_checks": sum(not value for row in rows for value in row["checks"].values())}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("prepare", "run", "case", "analyze"))
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--skill", type=Path)
    parser.add_argument("--family")
    parser.add_argument("--condition")
    parser.add_argument("--repeat", type=int)
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(read(args.config), args.root, args.skill)
    elif args.command == "case":
        raise SystemExit(case(args.root, args.family, args.condition, args.repeat))
    elif args.command == "run":
        run(args.root)
    else:
        analyze(args.root)

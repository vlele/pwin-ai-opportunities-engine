"""Inspect saved live payloads offline without resampling or changing verdicts."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import inventory_handoff as h, audit_partitioning as ap
from common import semantic_plan as s
from common.audit_evidence_encoding import decode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.run / "audit/outcome-summary.json").read_text())
    state_path = Path(summary["checkpoint_state_path"])
    digest = hashlib.sha256(state_path.read_bytes()).hexdigest()
    state = json.loads(state_path.read_text())
    ua = state["understanding_audit"]
    spans, ledger = ua["span_registry"], ua["facts"]
    batches = h.prepare(ledger, spans)
    out = {"mode": "offline request construction, not a live semantic verdict", "api_calls": 0,
           "facts": len(ledger), "batch_sizes": [b["request_chars"] for b in batches],
           "package_batches": sum(b["mode"] == "package" for b in batches),
           "vendor_batches": sum(b["mode"] == "vendor" for b in batches)}
    fact_ids = [fid for b in batches if b["mode"] == "package" for fid in b["payload"]["fact_ledger"]]
    assert fact_ids == [f"F{i}" for i in range(len(ledger))]
    assert all(size <= 640000 for size in out["batch_sizes"])
    old_targets = ua["claim_evidence"]["targets"]
    target = next(t for t in old_targets if t["id"] == "package-coverage")
    original = deepcopy(target)
    layout = ap._Layout(target, spans)
    old = next(r for r in ua["coverage_partition_audit"]["cross_partition_checks"]
               if r["target_id"] == "package-coverage-P0-P2")
    groups = [[r["ref"] for r in m["source_ranges"]]
              for m in ua["coverage_manifest"] if m["partition_id"] in old["partition_ids"]]
    check = layout.make(groups, old["partition_ids"], "cross_range")
    out["old_cross_partition_now_includes_R16"] = "R16" in check["audit_partition"]["requirement_ids"]
    assert out["old_cross_partition_now_includes_R16"]
    out["context_dependency_records"] = check["audit_partition"]["context_dependency_records"]
    print(json.dumps(out), flush=True)
    partition = ap.prepare(target, spans)
    out.update(partitions=len(partition["coverage_manifest"]),
               cross_checks=len(partition["cross_partition_checks"]),
               max_coverage_request_chars=max(partition["request_chars"].values()))
    assert out["max_coverage_request_chars"] <= 640000
    assert target == original
    out["original_checkpoint_unchanged"] = digest == hashlib.sha256(state_path.read_bytes()).hexdigest()
    assert out["original_checkpoint_unchanged"]
    # Old rejected receipts stay rejected; no replay result is promoted to pass.
    checks = {r["target_id"]: {s.audit_verdict_key(r): r["verdict"], "reason": r["reason"]}
              for r in ua["claim_evidence"]["checks"]}
    out["old_semantic_failures_still_block"] = not s.validate_audit({"checks": checks}, old_targets)["passed"]
    assert out["old_semantic_failures_still_block"]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()

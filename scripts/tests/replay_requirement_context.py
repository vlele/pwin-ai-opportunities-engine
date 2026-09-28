"""Offline structural replay of a saved inventory; never an E2E semantic pass.

The input stays private outside the repo. No failed child evidence is automatically
added to a parent, and no historical audit verdict is replaced.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import requirement_context as rc, semantic_contract as contract


def replay(state):
    audit = state["understanding_audit"]
    stages = [s for s in audit["stages"] if s["stage"] == "semantic-inventory" and s.get("retrieved_response")]
    original = stages[-1]["retrieved_response"]
    spans = audit["span_registry"]
    parent_wire = deepcopy(original)
    for row in parent_wire["requirements"]:
        row.pop("components", None)
        row.pop("logic", None)
        row["supporting_context"] = row.pop("evidence")
    parents = rc.validate_parent_inventory(parent_wire, spans)
    rows = []
    for ri, old in enumerate(original["requirements"]):
        ctx = rc.context(f"R{ri}", parents["requirements"][ri], spans)
        for ci, part in enumerate(old["components"]):
            missing = [a for a in part["evidence"] if not contract._contained([a], old["evidence"])]
            if not missing:
                continue
            ids = [ctx["id"] + "-E" + rc.digest(a) for a in missing]
            response = {"requirements": {ctx["id"]: {"status": "complete", "logic": old["logic"],
                "components": [{"kind": part["kind"], "text": part["text"], "evidence_ids": ids}]}}}
            # A previously selected parent focus may already declare this text.
            # Otherwise the attempted new child link MUST still be inadmissible.
            allowed = all(i in ctx["evidence_catalog"] for i in ids)
            rejected = False
            try:
                rc.validate_decomposition(response, [ctx], spans)
            except ValueError:
                rejected = True
            assert rejected == (not allowed)
            rows.append({"requirement": ri, "component": ci,
                         "previously_outside_parent": missing,
                         "unapproved_link_rejected": rejected,
                         "already_declared_in_parent_focus": allowed})
        if not contract._contained(old["focus"], old["evidence"]):
            assert contract._contained(old["focus"], ctx["parent"]["evidence"])
            rows.append({"requirement": ri, "type": "parent_focus_declaration",
                         "focus_retained_verbatim": old["focus"] == ctx["parent"]["focus"],
                         "child_evidence_imported": False})
    contexts = [rc.context(f"R{i}", row, spans) for i, row in enumerate(parents["requirements"])]
    batches = list(rc.batches(contexts))
    return {"mode": "offline structural replay, NOT semantic acceptance or capture",
            "live_calls": 0, "requirements": len(contexts), "mismatches_examined": len(rows),
            "unapproved_child_links_rejected": sum(r.get("unapproved_link_rejected", False) for r in rows),
            "batch_sizes": [len(b) for b in batches], "all_parents_preserved": sum(map(len, batches)) == len(contexts),
            "rows": rows}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.out.exists():
        raise SystemExit("Refusing to overwrite an evaluation artifact.")
    result = replay(json.loads(args.state.read_text()))
    args.out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))


if __name__ == "__main__":
    main()

"""Export or verify the exact runtime prompts; Markdown is not an input to models."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from common import semantic_contract as c, semantic_plan as s, capture_understanding as u
from common import requirement_context as rc
from common import ambiguity_repair as ar
from common import requirement_routing as rr
from common import evidence_selection as es
from common import inventory_handoff as ih
from common import preliminary_capture as pc


def documents():
    groups = {
        "PRELIMINARY-PROMPT": [("Bounded package reading", pc.REVIEW_PROMPT),
                               ("Independent package/materiality audit", pc.PACKAGE_AUDIT_PROMPT),
                               ("Cross-range decision reconciliation", pc.RECONCILE_PROMPT),
                               ("Independent reconciliation audit", pc.RECONCILE_AUDIT_PROMPT),
                               ("Preliminary workstream assessment", pc.ASSESS_PROMPT),
                               ("Independent judgment audit", pc.ASSESS_AUDIT_PROMPT),
                               ("Evidence selection transport", es.SELECTION_PROMPT)],
        "EXTRACTOR-PROMPT": [("Package extractor", u.EXTRACT_PROMPT),
                             ("Parent inventory extractor", rc.parent_inventory_prompt()),
                             ("Ledger-driven package inventory", rc.parent_inventory_prompt() + "\n" + ih.PACKAGE_RULES),
                             ("Separate vendor assertion inventory", rc.parent_inventory_prompt() + "\n" + ih.VENDOR_RULES),
                             ("Evidence selection transport (appended when active)", es.SELECTION_PROMPT),
                             ("General bounded correction (contract_correction.instruction payload)", u.CONTRACT_CORRECTION_PROMPT),
                             ("Targeted evidence-selection repair system prompt", es.REPAIR_PROMPT),
                             ("Historical combined inventory extractor (legacy probes only)", c.INVENTORY_PROMPT),
                             ("Legacy inventory extractor", s.INVENTORY_PROMPT)],
        "COMPARATOR-PROMPT": [("Current categorized component comparator", c.ROUTED_COMPONENT_PROMPT),
                              ("Historical isolated component comparator", c.ISOLATED_COMPONENT_PROMPT),
                              ("Component comparator", c.COMPONENT_PROMPT),
                              ("Legacy pair comparator", s.COMPARE_PROMPT)],
        "AUDITOR-PROMPT": [(kind, s.audit_prompt([{"kind": kind}])) for kind in s.AUDIT_TASKS]
                          + [("Ledger and vendor handoff auditor", ih.HANDOFF_AUDIT_PROMPT),
                             ("Standalone criterion per-record audit question (payload)", s.STANDALONE_CRITERION_AUDIT_QUESTION)]
                          + [("Source-partitioned coverage auditor", s.audit_prompt([{'kind': 'package_coverage', 'audit_partition': {}}]))]
                          + [("Current categorized comparison auditor", s.audit_prompt([{"kind": "comparison", "required": {
                              "components": [{"category": "technical_capability", "applicability": "prime_contractor",
                                              "routing_reason": "Explicitly assigned scope."}]}}])),
                             ("Legacy combined auditor", s.AUDIT_PROMPT)],
        "QUESTION-ROUTER-PROMPT": [("Independent ambiguity detection", c.AMBIGUITY_PROMPT),
                                   ("Question warrant audit", c.QUESTION_AUDIT_PROMPT),
                                   ("Bounded citation and category repair", ar.REPAIR_CATEGORY_PROMPT),
                                   ("Independent repair admission audit", ar.REPAIR_AUDIT_PROMPT),
                                   ("Routing audit", s.audit_prompt([{"kind": "routing"}]))],
        "DECOMPOSER-PROMPT": [("Parent-scoped decomposition", c.DECOMPOSE_PROMPT + "\n" + rc.DECOMPOSITION_INTERFACE),
                               ("Package context proposal", rc.CONTEXT_SELECT_PROMPT),
                               ("Independent context admission audit", rc.CONTEXT_AUDIT_PROMPT)],
    }
    return {name + ".md": "# " + name + "\n\n"
            "Exact assembled runtime system prompts. Generated reference only: the runtime reads "
            "the embedded strings in scripts/common/, not this Markdown. "
            "Regenerate with scripts/tests/export_semantic_prompts.py.\n\n"
            + "\n\n".join("## " + label + "\n\n```text\n" + text.strip() + "\n```" for label, text in sections) + "\n"
            for name, sections in groups.items()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    folder = ROOT / "references/semantic-prompts"
    failed = []
    for name, text in documents().items():
        path = folder / name
        if args.check:
            if not path.exists() or path.read_text() != text:
                failed.append(name)
        else:
            folder.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
    if failed:
        raise SystemExit("Prompt exports differ from runtime: " + ", ".join(failed))
    print(str(len(documents())) + " prompt exports " + ("verified" if args.check else "generated"))


if __name__ == "__main__":
    main()

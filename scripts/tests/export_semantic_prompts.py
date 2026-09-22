"""Export or verify the exact runtime prompts; Markdown is not an input to models."""
import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from common import semantic_contract as c, semantic_plan as s, capture_understanding as u


def documents():
    groups = {
        "EXTRACTOR-PROMPT": [("Package extractor", u.EXTRACT_PROMPT),
                             ("Structured inventory extractor", c.INVENTORY_PROMPT),
                             ("Legacy inventory extractor", s.INVENTORY_PROMPT)],
        "COMPARATOR-PROMPT": [("Isolated component comparator", c.ISOLATED_COMPONENT_PROMPT),
                              ("Component comparator", c.COMPONENT_PROMPT),
                              ("Legacy pair comparator", s.COMPARE_PROMPT)],
        "AUDITOR-PROMPT": [(kind, s.audit_prompt([{"kind": kind}])) for kind in s.AUDIT_TASKS]
                          + [("Legacy combined auditor", s.AUDIT_PROMPT)],
        "QUESTION-ROUTER-PROMPT": [("Independent ambiguity detection", c.AMBIGUITY_PROMPT),
                                   ("Question warrant audit", c.QUESTION_AUDIT_PROMPT),
                                   ("Routing audit", s.audit_prompt([{"kind": "routing"}]))],
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
    print("4 prompt exports " + ("verified" if args.check else "generated"))


if __name__ == "__main__":
    main()

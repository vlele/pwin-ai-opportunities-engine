# Categorized Requirement Routing

The local capture understanding pipeline now separates three independent concepts:

- `kind` identifies work, qualifications, timing, pricing, acceptance or context.
- `category` identifies whether the component belongs in vendor-fit assessment or a checklist.
- `applicability` identifies whether the source assigns it to this prime, not to this prime, or leaves that unresolved.

Every component emitted by the current parent-scoped decomposer must have a strict
category, applicability, source-grounded `routing_reason` and current-package evidence.
Missing or invented enum values fail validation; Python does not guess categories
from keywords, document names or customer names.

## Routes

| Category | Current, applicable component destination |
| --- | --- |
| `technical_capability` | Vendor comparison |
| `past_performance` | Vendor comparison |
| `compliance_certification` | Vendor comparison |
| `administrative_formatting` | Proposal Formatting & Submission Checklist |
| `contract_terms` | Contract Terms Review Checklist |

The filter runs before comparator job creation. Bypassed components generate no
vendor-comparison model calls and no fabricated `matched`/`not_applicable` vendor
findings. They remain in the immutable package graph and source-fidelity/coverage
audits. Original component IDs remain stable even when jobs skip some IDs.

A mixed clause is split first. Installation remains technical work; its pricing
basis becomes a contract term. A license remains a qualification; the instruction
to attach its copy becomes proposal administration. Technical service restoration
times and deliverable acceptance limits remain vendor-assessable, not ordinary
commercial terms. Eligibility registration is not the same as portal upload mechanics.
Proposal dimensions are formatting; product/drawing dimensions may be technical scope.

Socioeconomic participation thresholds and eligibility are `compliance_certification`.
Instructions to name/upload their proof or put it in a proposal volume are separately
`administrative_formatting`. Preserve conditional evaluation credit, denominators,
actors and exceptions; a scoring preference is not automatically mandatory eligibility.
Numeric thresholds alone do not determine category: technical response/availability
limits remain technical, and project-count/recency criteria remain past performance.

For current applicable components, checklists retain original source wording,
document/span and available page/character provenance, category, applicability and
routing reason. All entries remain unchecked with compliance `not_assessed`.
Bypassing capability assessment does not mean the government rule is optional or met.
Commercial terms are also retained for human pricing/legal/operational review; they
can still affect pursuit risk without being vendor capability evidence.

Superseded/exemplar components remain inactive context rather than current checklist
obligations. A source-supported `not_prime_contractor` component has disposition
`unrelated`, retained in applicability notes. An `unclear` applicability becomes a
source-anchored requirement-meaning question through the independent question channel;
it is not silently discarded. Official package-only questions route to formal Q&A.
No vendor answer can establish that a government term does not apply.

## Missing and Unrelated

In the current categorized path, `missing` means the applicable component lacks
specific proof in the isolated vendor claim. A generic capability and a concrete
different project with no demonstrated overlap both provide no proof of that
component. This does not invent outside experience or assert company inability.

`unrelated` is exclusively a requirement-applicability disposition, never a vendor
comparison status. The comparator wire schema and Python validator reject it for
current categorized jobs, not just the prompt. Explicit denial of the exact task
remains `contradicted`; genuinely ambiguous supplied claims remain `ambiguous`.
The comparator and comparison auditor use the same current policy. Historical
uncategorized stage fixtures remain readable with their historical vocabulary;
the production decomposer cannot emit those unclassified records. Runtime/prompt/
schema fingerprints invalidate old stage receipts for the current pipeline.

Only compared components enter fit aggregation and coverage denominators. Checklists
neither add credit nor penalize a proven task. A `Supported Fit` for the assessed
subset is not complete proposal compliance. Main fit notes omit bypassed component
findings and display the checklists separately.

For a standalone experience or qualification criterion, aggregate
`relationship/coverage=not_applicable` means no operational-task relationship is
asserted. It does not label the criterion formatting or exempt it from assessment.
The per-record auditor question is selected from the requirement's actual component
contract, not merely from that aggregate label. Component findings and `fit_label`
remain subject to evidence audit; unsupported or uncertain audits still block.

## Material-Fact Handoff

`inventory_handoff.py` gives the mapper bounded batches of extracted facts, stable
fact IDs and their original package spans. Every fact must link to one or more
returned records with its original provenance. Missing IDs, empty links, unknown
indexes and private-to-package citations fail before decomposition. Exact duplicate
records can be interned, but every fact retains its explicit link. Different source
occurrences are not semantically merged by code.

Vendor assertions have a separate private-source request and explicit per-source
dispositions. Generic assertions are retained without invented performance credit;
empty history and navigation text are not converted into work. An independent handoff
audit checks semantic retention and exclusions. An ID or matching citation alone
is not proof of coverage. Rejected/uncertain verdicts block, without semantic retries.

Full original package spans, including uncited text or facts missed by extraction,
still reach the separate source-partition coverage audit. This source gate now runs
before vendor comparisons. Partition selection follows cited supporting-context and
precedence dependencies to closure, retaining unchanged records, their citations,
and original IDs. Dense indivisible dependency graphs fail, never silently drop text.
No lexical similarity, customer keywords or solicitation-specific admission rules
are used to select these dependency records.

Post-award performance deliverables and task deadlines are not proposal formatting.
The decomposer and source auditor share this boundary; code does not rewrite model
categories. Actual delivery remains technical, ordinary commercial notices remain
contract terms, and proposal upload/page-layout mechanics remain administrative.

No source text, evidence-selection limit, request ceiling or negative audit verdict
is relaxed. Changed runtime identities invalidate earlier receipts. Offline tests
prove accounting, request construction and blocking behavior, not live semantic
accuracy. Cross-batch precedence and facts missing from the extractor still require
full-source audit; the ledger is not an exhaustive statement of source truth.

## Tests

Run from the skill root:

```bash
python3 -B scripts/tests/test_requirement_routing.py
python3 -B scripts/tests/test_inventory_audit_alignment.py
python3 -B -m unittest discover -s scripts/tests -p 'test_*.py'
python3 -B scripts/tests/export_semantic_prompts.py --check
```

Opt-in paid probes require `OPENAI_API_KEY` and a new, empty output directory. They
use GPT-5.4 mini with medium reasoning, save every response/status/usage receipt,
and refuse to overwrite earlier results:

```bash
export PWIN_LIVE_TEST_AUDIT_DIR=/absolute/path/to/new-private-test-output
PWIN_LIVE_ROUTING_TEST=1 python3 -B scripts/tests/test_live_requirement_routing.py
PWIN_LIVE_COMPONENT_TEST=1 python3 -B scripts/tests/test_component_wire.py
```

Offline tests exercise real orchestration with synthetic model responses and assert
exact job routing, coverage accounting, rejected labels, citation fidelity, formal
Q&A blocking and Markdown handoff. They are not model-accuracy evidence. The live
probes assess category behavior in three synthetic domains and comparator proof
boundaries, not a full-document end-to-end capture or repeated stability benchmark.

## Independent Audit Budgets and Label Checks

`semantic_plan.audit_batches` packs by serialized character count, not record count.
It measures the complete initial request using the same serializer as the runtime
guard: system prompt, source spans, targets, answers, previous/independent questions
where relevant, evidence transport and strict response schema. JSON escaping counts.
Kinds remain separate so package-fidelity audits never receive private vendor context.

The hard ceiling remains 640,000 characters. Smaller limits may be requested but
larger ones are rejected. Every target is retained intact and exactly once. If a
single target plus its required context cannot fit, preflight raises an exception
naming that target and its size before any independent-audit model calls. No source
or target is truncated. The runtime still checks every request, including repair
requests; additional repair context can still trigger a hard block.

Current comparison prompts share `CATEGORIZED_MISSING_PROOF_POLICY` from
`semantic_policy.py`. The comparison auditor additionally uses
`CATEGORIZED_AUDIT_LABEL_POLICY`: a correct explanation cannot excuse a wrong label,
and missing/unrelated conflation requires `unsupported`, not silent repair. These
vendor-fit instructions are not injected into source-fidelity audits.

`test_audit_size_batching.py` covers full-request overhead, exact boundaries,
oversized singleton/context, escaping, source isolation and production wiring.
`test_missing_proof_regressions.py` retains the five historical explanations as
opaque negative fixtures, with no company-specific production rules or relabeling.
Those historical administrative clauses do not override the current smart filter.
Passing these tests is not a full capture release or proof of live model accuracy.

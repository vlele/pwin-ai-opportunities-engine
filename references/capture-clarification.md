# Capture Understanding Checkpoint

Capture reads the package and company profile before market research. The model
interprets meaning; code validates references and controls whether research starts.
This checkpoint is not a fit score or bid decision. Passing unit tests does not
prove live reliability. See `plans/claim-contract-hardening.md` for release criteria.

## Ten Synthetic Examples

These fictional examples were defined before implementation. They belong in test
fixtures, never in customer-specific production matching rules.

| Case | Material confusion | Appropriate response |
| --- | --- | --- |
| Undefined acronym | An acronym could describe different tasks. | Seek its definition in this package first; ask only if meaning remains unresolved. |
| Migration | An existing reference does not identify what moved. | Ask what the performer migrated, not for a replacement project. |
| Workshare | A reference names a prime and supporting company. | Clarify which tasks the offeror itself performed. |
| Legal entity | Offeror and performer names differ without a relationship. | Ask about the relationship; identity alone does not establish tasks. |
| Scale | A reported quantity has ambiguous units or workshare. | Clarify meaning if material. A simply missing site count is a qualified gap. |
| Recency | A date could mean award, start or completion. | Clarify the event if material. Missing dates alone are not misunderstood work. |
| Certification | Holder or covered services are unclear. | Clarify scope without assuming affiliate eligibility. |
| Vehicle access | Access is through an unspecified partner. | Clarify holder and proposed role; do not assume an executed agreement. |
| Official conflict | Current provisions conflict with no controlling precedence. | Obtain authoritative clarification through formal Q&A. |
| Mixed pricing | Multiple bases are stated but allocation is absent. | Preserve known types and identify the missing allocation; never invent CLINs. |

Unrelated work does not need a rescue questionnaire. Missing history is unknown, not
inability. An understandable self-report is unverified, not necessarily ambiguous.
Technical failures are not business questions for the user.

## Source-Linked Pipeline

Production orchestration is in `common/capture_understanding.py`; representation,
contracts and projection are in `common/semantic_plan.py` and
`common/semantic_contract.py`.

1. Detect material ambiguity in original inputs through an independent question
   channel. Check whether each question is warranted, not whether its answer is true.
   Keep source-valid questions available if a later stage fails.
2. Extract package facts in contiguous batches. Retain coverage and the raw ledger.
3. Build an inventory from **all original source spans**, not ledger paraphrases.
   Preserve current/superseded/example package facts, distinct vendor claim types,
   and material questions. Each requirement's `focus` identifies its exact subject;
   `evidence` preserves surrounding context. Package wording is assembled from the
   focus quotations, not an independently generated paraphrase.
   Claims explicitly list `unresolved_dimensions`. Unclear duties, unclear own
   workshare and conflicting performer identity are distinct; a broad unresolved
   label must not invent a legal-entity question. Inventory questions enter the
   same warrant channel as initial ambiguity signals.
   `quoted_vendor_context` is an explicit array of distinct package-provided vendor
   references, each with bounded meaning and exact package-only evidence. A profile
   duplicate cannot replace the package occurrence. An empty array is not filled
   from raw claims; the package-coverage auditor must catch omitted references.
4. Decompose requirements using package-only evidence. Separate activities from
   their conditions, qualifications, pricing and timing. Code enumerates work-bearing
   requirement/claim pairs, regardless of the original area/task hints.
   A scoped underlying task named inside a completion/deadline clause must remain a
   separate work component; a narrow focus on the outcome must not erase it. Preserve
   actor attribution: government prerequisites, historical work and pure payment/date
   events are not new contractor duties. Work components are stably ordered first
   before assigning component IDs; sorting cannot invent an omitted activity.
5. Compare each component in a separate model call. The response schema locks
   `pair_id`, `component_id`, `component_text` and `component_kind` to that target.
   Code rechecks identity during assembly and computes partial coverage from met
   and missing components; the model cannot replace that with an overall fit label.
   This trades additional model calls for smaller, isolated decisions. It does not
   establish that a correctly bound natural-language explanation is true.
   Evidence quotations are selected from the claim's declared exact ref/quote pairs
   and explicitly linked negative/uncertainty context. Reading a surrounding span
   cannot expand a citation past that declared boundary. Selection does not prove
   semantic support; the independent auditor still judges each reason.
6. Audit immutable records in homogeneous batches. Requirement fidelity and package
   completeness receive package-only sources. Vendor-inventory completeness receives
   vendor/answer sources only. Comparisons receive both sides. The auditor cannot
   rewrite claims or omit targets. Modern assertion audits do not re-audit question
   warrant. One warrant decision owns each exact dimension/source candidate.
7. Code renders the checked records and the independent questions. Neither questions
   nor failed audits can invent positive experience or authorize research.

Legacy assessment/facet helpers retain regression fixtures but are not the current
production orchestration. Their isolated test success does not prove this path.

### Evidence Contracts

Invented quotes, wrong source roles, unknown IDs and missing matrix entries fail.
A valid citation proves text exists, not that its interpretation is correct.
Component citations must be contained within the specific claim/requirement's
declared evidence, not merely somewhere in the same document or source span.

`performed_task` is reported past or ongoing execution. General service offerings
are `capability`; existing references with unresolved duties are `work_reference`.
Extraction and all claim auditors use `common/semantic_policy.py`. A present-tense
statement of a specific activity the vendor itself performs is `staff_execution`,
even without dates, a named customer or a completed-project narrative. It receives
reported-work status, not verified success or full-scope credit. An explicit offer
or ability claim without asserted execution remains `service_offering`; conditional
and future plans remain prospective. Stated performer and workshare still govern.
Identity, dates, owned assets, preferences and qualifications are not performed tasks.
Reported claims remain unverified. An identity answer cannot create task history.
The explicit `execution` field separates affirmative actual work from denials, asset
ownership, date metadata and prospective offerings. Mixed statements retain their
affirmative work separately; a lexical occurrence of "not" is not a semantic filter.

Requirements retain `focus`, `components`, `logic`, `record_kind` and `supersedes`. An active
precedence rule can retire its old target, not its own instruction. Cyclic, self-linked
or indistinguishable rule/target references fail validation rather than guessing.
The old term and its active replacement rule may share context but have distinct
subjects. Quoted vendor references inside a package remain separate source context,
not additional official duties to be invented by the coverage auditor.

Requirement audit targets explicitly declare `audit_dimension=source_fidelity`.
Their model response uses `fidelity_verdict`, never a verdict on which term governs.
Code preserves this scope when combining audit batches. Faithfully recorded current
terms can conflict: both remain current and receive `unresolved_precedence` plus
linked requirement IDs when an official-conflict question identifies them. Here
`current` means present and not explicitly superseded, not resolved as controlling.
No linked conflict means `not_assessed`, not an assertion of resolved precedence.
Faithful recording passes audit while the conflict still requires formal Q&A and
blocks research. Wrong numbers, lost qualifiers and fabricated source quotations
still fail; conflict is not an audit bypass. Model verdicts are never flipped to
supported because their reason mentions a conflict.

`component_findings`, `met_components`, `partial_components`, `missing_components`,
`unknown_components`
and `fit_label` expose
the basis of a partial fit. These are component-coverage findings, not pursuit scores
or independently verified qualifications. Pricing facts never become experience.
A component may itself be only partly established. Its `partial` status records
the exact `supported_scope` rather than granting the entire broader activity or
calling a subordinate task different-task transfer. Neither a partial component
nor an unrelated matched qualification can become complete performed-work credit.

Comparisons state `matched_work`, `coverage` and a relationship:

- `same_task`: matching identifiable work, possibly only partial coverage.
- `applicable_different_task`: different work with a concrete transfer basis.
- `unrelated`: different reported work with no supported overlap, not universal inability.
- `unknown`: unclear work/attribution or additional coverage not claimed.
- `not_applicable`: no identifiable work in a commercial/administrative record.

Only self-attributed performed tasks receive positive experience credit. Code does
not infer similarity from industry vocabulary. Missing conditions are not satisfied.
Valid `not_applicable` context/pricing components are excluded from completeness
aggregation and downstream score denominators. Adding administrative clauses cannot
reduce credit or satisfy an alternative. Marking real work/conditions `not_applicable`,
or marking context `missing`, remains a contract error; code does not silently relabel
it or convert invalid output into a business-fit penalty.
When a self-report establishes the core work but says nothing about a cumulative
timing or qualification condition, work remains matched and the condition is
missing/Unknown: the aggregate is Partial Fit. Silence is not contradiction. Clearly
different supplied work remains Unrelated. Identifying the actual core-work match
is still a semantic decision; a wrong explanation must fail its independent audit
even if its component ID, echoed text and citations are structurally valid.

The model selects a question's unresolved dimension and decision consequence. Code
builds neutral wording around the exact linked quotes. No hypothetical answer earns
credit. The auditor judges whether the question is warranted, not whether its unknown
answer is true. Official conflicts need authority, not the vendor's preference.

Question receipts retain exact evidence, source-context hashes, detection origins
and the warrant verdict. The same candidate cannot be rejected then reintroduced
by the inventory, or accepted then rejected by an unrelated claim auditor. Receipt
identity includes dimension, affected decision and exact citations. After warrant
checks, display rows merge by intent (the unresolved information dimension) and covered
word positions in the original source. Split versus whole quotations and boundary
punctuation therefore do not create duplicate displayed questions. The broadest
actual quotations and all original receipt IDs/checks survive. Conflicting warrant
verdicts remain uncertain, never silently supported. Affected decisions are consequences,
not question identity: one precedence answer may resolve both timing and acceptance.
Merged rows retain all those consequences. Different passages or missing-information
dimensions are not merged. Repeated ambiguous quote locations are not guessed.
This is conservative provenance-based deduplication, not an unrestricted semantic
clustering model: materially different citation coverage may still leave duplicates.
An unvalidated question survives a provider failure with `question_validation:
pending`, never as authority to proceed. A workshare question can resolve which
tasks the offeror performed; an identity answer alone cannot do so. If all relevant
questions are rejected while the claim still asserts unresolved meaning, that
contract contradiction blocks research rather than silently clearing ambiguity.

Downstream fit catalog entries retain checked credit boundaries mapped to original
profile fields. Unknown/unrelated or identity-only projects cannot later earn past
performance credit. Answers apply to referenced entries only. Inconsistent fit
mappings fail. Every company theme needs linked requirement and company evidence.
Commercial partner signals cannot rescue no-fit status.

The modern handoff exports a `checked_evidence_graph` containing only audited
requirements, claims and component comparisons, not proposed questions or the raw
extraction ledger. The fit catalog uses the original requirement IDs and all current
work-bearing records, not a newly truncated or paraphrased workstream list.
Superseded records are excluded from fit and research-query focus; active precedence
rules remain separately inspectable. This does not yet prove precedence preservation
through every legacy acquisition-field parser/renderer.

Final fit and project coverage are projections of those checked comparisons. The
strategy model cannot reassign a project's credit to a different task or replace a
known partial match with complete qualification. Disagreements are retained in
`checked_decision_overrides`. `component_coverage_notes` render the met, partial and
unestablished parts with project, requirement and claim IDs. Different claims are
not combined into complete coverage without a checked common basis.

The numeric score is a ranking proxy, not a measurement of delivered scope or win
probability: matched components count 1, partial components .5, transferable .4,
and unproved components 0; commercial/context terms are excluded. Partial totals
cannot round to full credit. Qualification alone can be displayed as partial
component support without receiving performed-work credit. Model-supplied numeric
weights are ignored. Positive capability/performance still depends on the accuracy
of the upstream semantic decisions; these deterministic contracts do not establish
live model accuracy or independently verify a reported project.

### Independent Dimensions

| Field | Meaning |
| --- | --- |
| `relevance` | Direct, transferable, unrelated, unknown or not applicable. |
| `ambiguity` | Clear, missing, ambiguous or conflicting meaning. |
| `verification_status` | Unverified reported claim, absent/unknown, or explicit source support under the relevant contract. |

Package support is not authentication. A requirement cannot prove vendor performance.
Clear partial coverage retains gaps without requiring a proposal-completeness interview.

## States and Boundaries

- `READY`: understanding permits research, not proof of fit or memo completeness.
- `NEEDS_CLARIFICATION` (exit 20): material meaning needs user facts or a document.
- `NEEDS_FORMAL_QA` (exit 21): official conflict needs authoritative clarification.
- `TECHNICAL_BLOCKED` (exit 22): provider, extraction, citation, schema, semantic-validation, stale-answer or resource-limit failure.

A negative semantic verdict is not retried until it passes. Each stage permits at
most one malformed-contract correction; provider failure is not automatically retried.
No model upgrade or fallback is automatic.

A rejected finding must not hide a source-valid material question. The independent
channel runs before comparison and fidelity audits. It can retain an unresolved
question even when another stage returns `TECHNICAL_BLOCKED`; the question is not a
claim that its answer is true. Questions rejected on their own merits are not rescued
by unrelated findings. Failed reassessments retain both old and new questions.
`validation_pending` and `research_authorized: false` prevent question-only output
from approving research. All fit judgments are withheld on a failed assessment.
Actual answers require a full reassessment.

The gate stops public enrichment, USAspending, commercial intelligence and final
judgment. Primary retrieval, OCR/vision and understanding-model APIs may run before
the gate: this is not an offline mode. At most three unanswered questions are shown
per batch. Unknown answers do not resolve blockers, grant credit or cause indefinite
repeated questioning. Clear poor fit may proceed to an honest no-bid assessment.

## Run, Answer and Resume

Run normal capture, or inspect understanding only:

```bash
python3 "$SKILL_ROOT/scripts/capture/run_capture_research.py" \
  --workspace "$WORKSPACE" --file /absolute/path/to/PWS.pdf --preflight-only
```

Stdout returns `clarification_path` and `answers_template_path`. Keep edits in a
separate answers file so subsequent templates do not overwrite them. Preserve IDs
and fingerprint. Supply the user's actual words, not an invented resolving answer:

```json
{
  "fingerprint": "the returned fingerprint",
  "answers": [
    {"question_id": "the returned ID", "answer_status": "answered", "answer": "Our staff installed the equipment; repairs were performed by the prime."}
  ]
}
```

Use `answer_status: "unknown"` for unresolved answers. Rerun with
`--clarification-answers /absolute/path/to/my-answers.json`. Remove `--preflight-only`
to run full capture once ready. Substantive answers are reassessed, not overrides.
Corrections reopen questions; withdrawing an answer revokes earlier approval.

Add new documents with additional `--file` arguments. Changed package/profile inputs
require a fresh interpretation; stale answers fail. `--retry-clarification` retries
technical failures, not unresolved meaning or official conflicts.

## Settings, Limits and Audit

`PWIN_UNDERSTANDING_MODEL` defaults to the shared model.
`PWIN_UNDERSTANDING_REASONING_EFFORT` defaults to `high`; cost-sensitive experiments
explicitly select `low` without changing the default. Requested model/effort are
saved and fingerprinted. Bounded input or context overflow blocks, never silently
discards evidence. Native PDF text does not prove table/image fidelity. Sparse pages
and incomplete workbook extraction remain limitations. More calls do not prove quality.

`procurement/capture-clarifications/<fingerprint>/` retains input, state, review,
events and answer templates. `understanding_audit` retains prompts/responses, spans,
coverage, the semantic plan and every verdict. These contain private package/profile
data: **do not commit live audit directories**. Fingerprints include inputs, file
content, model settings and checkpoint code. Answers never rewrite permanent profiles.

## Release Evidence

- `python3 -m unittest discover -s scripts/tests -p 'test_*.py'`: offline contracts.
- `scripts/tests/run_semantic_classification_benchmark.py`: frozen full-checkpoint repeats.
- `scripts/tests/run_semantic_plan_audit.py --live ...`: paid saved positive/negative controls.
- `scripts/tests/evaluate_release_readiness.py`: fail-closed evidence gate, never a commit/push command.

Freeze runtime and expectations before paid runs. Retain every failure. Reserve
unseen families until the development gate passes; an exposed failure becomes
regression data, not an unseen test again. Release requires repeated known/held-out
cases, auditor controls, offline suites, long-package integration and documented
semantic/repository review. An automatic pass still requires semantic review.
Neither unit success nor a perfect isolated auditor score proves full capture ready.

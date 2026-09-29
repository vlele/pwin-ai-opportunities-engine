# Preliminary Capture Assessment: Product Contract

## Goal and Implementation Status

The primary product is a Preliminary Capture Assessment for a capture manager's
early pursue, investigate-further or decline decision. Proposal Readiness Review
is a reference appendix in the same report, not a prerequisite for publishing
independently supported capture findings.

The runtime implements a separate `--depth preliminary` path. The existing
`--depth full_360` path retains its strict inventory/audit gates unchanged. A failed
legacy graph is never relabeled or reused as accepted preliminary evidence.
Preliminary mode reviews all supplied source spans in bounded ranges, audits
source-faithful findings, synthesizes workstream-level judgments and independently
audits those judgments. It preserves unsupported rows in an audit quarantine.
Offline tests establish routing and publication behavior, not live model quality.
Live quality must be reported from each run's saved requests and responses.

## Main Assessment

The body should be concise, requirement-specific and useful with a sparse vendor
profile. It should answer:

1. What work and outcomes is the customer buying, and why do they matter?
2. Where is there plausible alignment with the supplied vendor capabilities?
3. What relevant delivery experience is actually evidenced, and what is unknown?
4. Which access, eligibility, staffing, schedule, commercial or performance issues
   could change the pursuit decision?
5. What is the competitive position, based on available and attributed evidence?
6. Is there a concrete role for a teaming partner, and what gap would it address?
7. What requirement-based win hypotheses deserve validation, and what proof would
   the vendor need to support them?
8. What should the capture manager do next, and what would change the recommendation?

Organize the body around coherent workstreams, not every contract clause or every
vendor-profile field. Public research is enrichment, not a prerequisite for
reasoning about supplied requirements. Unavailable market information is disclosed;
incumbents, funding and competitors must not be invented.

## Evidence and Decision Boundaries

Strategic alignment and demonstrated qualification are separate findings. A
specific self-reported capability can support tentative alignment with related
work. A generic company statement is not proof of specific work, credentials,
delivery history or eligibility. No new project experience may be inferred.

Distinguish reported capability, concrete self-reported delivery, independently
corroborated delivery, missing proof, unrelated work and unresolved ambiguity.
Self-reported delivery need not be independently verified to be described as
self-reported; it must not be labeled independently verified.

Missing profile information is not proof of inability and is not automatically a
clarification question. Requesting an existing ambiguous reference's meaning is
different from listing absent evidence as a next diligence action. A poor-fit
vendor does not receive a teaming recommendation merely because a gap exists.

Every material factual assertion needs current source support. Every win hypothesis
needs a requirement anchor, an explicit inference, and a statement of what vendor
proof would be required. Evidence anchoring does not justify generic strategy
language or an unsupported claim that the vendor has a discriminator.

Keep recommendation, report availability, confidence, and appendix completeness
separate. A useful report can recommend investigate further. A report's existence
does not mean the vendor is qualified, the opportunity is current, the proposal
is compliant or the system has established a win probability.

## Proposal Readiness Review Appendix

Title: "Appendix: Proposal Readiness Review - Reference for Capture Managers".

Include available, source-grounded detail on submission instructions, formatting,
volumes, evaluation and experience criteria, certifications, forms, staffing,
pricing/CLIN structures, contract terms, acceptance/remedies, amendments and Q&A.
For each item, retain the source location, the relevant instruction, the evidence
or action still needed, and the review status. Separate proposal-stage obligations
from post-award deliverables. Preserve mixed pricing rather than collapsing it to
one contract type.

Explicitly label the appendix's coverage and limitations. It is not a certification
of proposal compliance, and incomplete or unreviewed items must not look checked.
Do not invent generic checklist rows when the current package supplies none.

Placement follows decision impact, not a blanket administrative/technical label.
A form required before site access, an ownership restriction, a hard eligibility
rule, a near-term submission deadline or an onerous liability term can be
decision-changing. Summarize such matters in the main body and retain their
details in the appendix. A material issue must never be hidden by reclassification.

## Failure Containment

Code should own source identity, quotation retrieval, exact duplicate accounting
and provenance. A model should not need to reconstruct redundant reverse indexes
merely to make a capture judgment. Equivalent-looking text is not permission to
merge different legal entities, source roles, time periods or qualifications.

Invalid evidence remains invalid. Exclude or quarantine the affected finding and
disclose the limitation; do not silently repair its meaning or turn a failed audit
into a passing one. Independently supported findings can still be published if
their inputs and dependencies are intact.

An appendix-only omission or duplicate profile-tag accounting issue should not
automatically block unrelated capture reasoning. If a missing or unreliable item
could change the pursuit decision, flag that limitation in the main body and
withhold a definitive recommendation. If reliable core scope cannot be established,
do not publish a strategic assessment as though it could.

This requires explicit materiality and dependency handling. Simply ignoring all
audit failures, disabling coverage, returning READY for every failure, or relabeling
the existing blocked result is not an implementation of this contract.

## Acceptance Scenarios

| Scenario | Required behavior |
| --- | --- |
| Relevant stated capabilities but no supplied project history | Tentative alignment; history unknown; targeted diligence actions, not invented experience. |
| Clearly unrelated supplied delivery history | Explicitly unrelated; no assumed hidden experience or automatic teaming recommendation. |
| Duplicate capability values in compatible fields | One capability with retained provenance; no extra credit and no whole-report block solely for duplication. |
| Citation pointing to another entity or unrelated passage | Reject affected finding; do not infer identity from matching words. |
| Formatting detail not fully inventoried | Mark appendix coverage incomplete; preserve otherwise supported capture findings. |
| Access prerequisite or mandatory eligibility not verified | Prominent main-body risk and conditional recommendation; detail in appendix. |
| Conflicting government terms | Show both terms with sources and the decision consequence; do not silently choose precedence. |
| Scope-bearing attachment unreadable | Disclose missing scope; withhold conclusions depending on it, including the overall recommendation when material. |
| Credible workstream evidence but no useful market research | Reason about the work; disclose market gaps without inventing incumbent or competitor facts. |
| Requirement has an action plus an unproven condition | Preserve supported action and missing condition separately; no all-or-nothing fit judgment. |
| Proposal rule and post-award obligation in one paragraph | Retain both with correct purpose and lifecycle; promote either if decision-changing. |
| Model cannot support a strong win hypothesis | Produce fewer hypotheses, not generic filler or raw clause restatement. |

Test these across unrelated solicitation families, sparse and missing profiles,
negative controls and repeated model runs. Measure decision usefulness and evidence
correctness, not predetermined scores, number of facts or uninterrupted execution.

## Implementation Boundaries

- `scripts/common/preliminary_capture.py`: bounded source review, source audit,
  workstream assessment, judgment audit, failure containment and recommendation policy.
- `scripts/capture/run_capture_research.py`: explicit preliminary dispatch; legacy
  clarification/resume flags require `full_360` and cannot bypass a failed graph.
- `scripts/capture/preliminary_render.py`: main assessment, material conditions,
  limitations, reference appendix and original-quotation evidence notes.
- `scripts/tests/test_preliminary_capture.py`: mocked acceptance and negative
  controls, request-budget and source-partition accounting, fresh artifact routing.
- `references/semantic-prompts/PRELIMINARY-PROMPT.md`: generated exact runtime prompts.

Initial scope is local/package-based assessment. No external market enrichment is
performed by this path. Appendix coverage is expressly non-exhaustive. Every source
span is assigned to a review range; this does not certify every clause was retained.
Material gaps cap the recommendation at investigate-further. Models can still make
semantic mistakes; source citations and audit agreement are not a guarantee.

Preserve the historical failed runs and the currently tested candidate. Do not
change receipt identities or promise warm reuse across incompatible runtimes.
Paid runs require separate user authorization; this document alone does not authorize them.

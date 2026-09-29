# Preliminary Capture: Product and Release Boundary

The product supports an early pursuit decision, not an exhaustive compliance
certification. Read the supplied sources in bounded ranges; reason about coherent
workstreams, vendor alignment, pursuit barriers, evidence gaps and next actions.
Do not require an atomized inventory of every clause before producing an assessment.

## Who Owns What

- Models interpret source meaning and strategic relevance. No customer-specific
  parser rules determine capability, staffing obligations or eligibility.
- Code retrieves the exact selected quotation, preserves document provenance,
  constrains valid structural combinations and controls publication.
- Auditors evaluate the assertions proposed for publication and material coverage,
  not exhaustive administrative completeness. An auditor is a model, not ground truth.
- The renderer displays admitted factual qualifiers beside capture analysis.
  Draft/anticipated/optional terms cannot be silently promoted to issued mandates.

## Proportionate Failure

No supported core scope means no substantive capture conclusion. Missing vendor information means
unknown fit, not invented experience or inability. A material source or eligibility
uncertainty stays in the main report as a research caveat, not an automatic pursuit
veto. Conditional discovery is allowed when supported by audited core scope and
alignment; it is not bid authorization. An uncertain form reading is not an official
government conflict. A report containing only review notes must state that no fit
conclusion was established. No readable package still means a technical block.

Reconciliation failures leave the affected entry and its actual governing/document
dependencies unverified, not everything in its topic group. The auditor still sees
the entire catalog to check for missed conflicts. A bad incoming link does not poison
an independently approved target. Missing audit checks never imply approval; no
invalid relationship is silently repaired. Provider interruptions do not permit
indefinite retries or approval of unaudited rows.

Unsupported interpretations are documented, not erased. The separate review log
retains the interpretation, reason, earlier source-fidelity status and independently
retrievable quotations. Bad citations receive no fabricated quotation. Review items
are not accepted finding IDs and cannot supply positive fit/experience credit or
adverse eligibility conclusions. Unsupported strategy remains labeled review prose,
not a fallback win theme.

The source auditor classifies relevance independently. Material eligibility, access,
core scope, major staffing and experience stay visible in the main report. Routine
commercial terms such as price validity, submission mechanics and readiness-only
uncertainties belong in the appendix and are excluded from the strategy input.
An unaudited candidate cannot declare itself harmless: unknown relevance stays
visible in the main review log. Do not treat a price-hold period as an automatic
no-bid trigger or capability mismatch. The appendix remains a preliminary reference,
not a submission-ready compliance matrix.

## Audit Display Convention

Mark automated approvals as **Audited\*** in the main assessment and readiness
appendix, including findings, judgments and the recommendation. The asterisk
means the item's meaning or attached evidence may be incomplete even though a
model approved it. Show the explanation prominently near the recommendation and
again in the appendix. It is not human verification, vendor-capability proof, or
proposal-readiness certification.

Do not apply the approval label to missing, failed or uncertain audits. A source
assertion that passed an earlier audit but failed later reconciliation remains an
Unverified interpretation, with the limited earlier approval explained separately.
The renderer does not change verdicts, citations, recommendation, or release status.
The asterisk does not fix a known false statement or incomplete citation and must
not be used to claim those defects are resolved. Preserve specific review notes.

## Token-Limited Test Runs

A provider response ending with `finish_reason=length` is unfinished generation,
not malformed requirement data or a semantic rejection. Preliminary capture records
the stage, usage and affected source ranges, skips the unfinished reading/audit, and
continues other ranges and assessment on independently admitted evidence. A failed
supplement preserves the earlier checked findings. Unfinished reconciliation does
not approve its proposed terms; unfinished judgment auditing does not publish its
candidate strategy. No cap increase, automatic retry or evidence relaxation occurs.

Every rendered report ends with **Requirements not processed because of token limits
in the test environment**. List document/page/extracted-character ranges and the
unfinished processing stage, not invented requirement descriptions. Distinguish an
unread source from a source whose audit or downstream judgment was unfinished.
If no such limit occurred, say `None recorded.` Do not relabel quota errors, refusals,
malformed JSON, bad citations or adverse semantic verdicts as token-limit omissions.

Token exhaustion alone does not suppress the report. If no core workstream could
be audited, render a clearly limited source-coverage report with no invented vendor
judgment. Otherwise continue a qualified preliminary assessment. Unknown material
coverage remains prominent and prevents an unqualified positive recommendation.
An incomplete response is never saved as a successful stage checkpoint. Raw failed
provider receipts remain audit history. The normal strict/full_360 callers still
fail closed on incomplete generation; this continuation policy is preliminary-only.

## Human-Reviewed Beta Acceptance (2026-09-29)

The maintainer explicitly authorized merging the current candidate to main as a
human-reviewed preliminary-capture beta, with the known limitations documented in
[the beta release notes](../docs/human-reviewed-beta.md). This is a deliberate
acceptance of residual risk for supervised use, not a claim that the strict
semantic gate below passed. The Audited* display change does not repair the
IETSS conditional-summary or CES citation-attachment defects. The full_360 path
and unrelated workflows are not certified by this beta evaluation.

Keep failed/uncertain interpretations visible, retain the source checks and audit
history, and require human verification before acting on decision-changing advice.
Do not label this release semantic-stable or proposal-ready.

## Strict Semantic-Stability Gate (Still Open)

Use the existing IETSS, EBMS, FMBT and CES corpus plus focused transfer controls.
Each must produce useful workstream reasoning without invented eligibility,
vendor delivery, strengthened obligations, or unsupported citations in accepted
findings and judgments. Material uncertainty must inform visible diligence caveats,
not mechanically force a recommendation label. Routine administrative
completeness is not the release gate; model approval alone is not a passing score.

First run offline saved-response and negative tests. These prove structural gates
and failure isolation, not semantic model accuracy. Then freeze the candidate for
a separately authorized, cost-bounded live evaluation and inspect the rendered
reports. Do not rerun until a desired answer appears. Retain adverse results.

The saved-response fixture deliberately retains the rejected CES reference bundle;
code does not salvage a count from unsupported prose. Its interpretation may be
documented as unverified, but a future model response must select sufficient evidence
before a reference-count assertion is accepted. Likewise,
a new qualifier audit field is an explicit check, not a guarantee that the model
will never misread anticipated staffing. Stable promotion remains gated on live
output review; the explicitly authorized human-reviewed beta is a separate
release decision, not an override of any runtime validation rule.

## Local Verification

```bash
python3 -m unittest scripts.tests.test_preliminary_scope
python3 -m unittest scripts.tests.test_preliminary_token_limits
python3 -m unittest scripts.tests.test_preliminary_review_policy
python3 scripts/tests/replay_preliminary_review_policy.py --output /new/audit/documented-review
python3 scripts/tests/replay_preliminary_scope.py --output /new/audit/saved-admission.json
python3 scripts/tests/export_semantic_prompts.py --check
python3 scripts/tests/run_release_offline.py --output /new/audit/offline-release
```

Neither offline command spends API credits or generates a new live capture report.
The strict full_360 implementation and its request/evidence limits are unchanged.

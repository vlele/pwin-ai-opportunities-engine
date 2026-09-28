# Preliminary Capture: Decision Fidelity

This patch serves an early capture decision. It does not reinstate an exhaustive
proposal-readiness inventory or clause-by-clause vendor comparison. The Proposal
Readiness Review remains a non-certifying reference appendix.

## Contracts

1. **Selected options, not printed alternatives.** Native PDF checkbox/radio values
   are recorded with page, bounding box and extraction basis. Small vector controls
   and selection markers prioritize a page for the existing bounded vision review.
   Visual observations distinguish selected, unselected and uncertain. A control
   citation must name an actually selected, cited option; an unchecked sibling or
   printed option list cannot establish an acquisition selection. Unreviewed pages
   and conflicting observations remain explicit limitations. Scanning more pages
   for candidates does not increase the configured vision-call cap.
   A page-level form flag does not turn a narrative funding or submission statement
   into a checkbox claim. Code verifies actual selected-control IDs, labels, states
   and citations. The independent source-fidelity auditor verifies that a claimed
   narrative selection is a real statement, not printed alternatives mislabeled
   as prose. Passing this mechanical gate is not semantic approval.
2. **Reconcile before synthesis.** Package ranges are still read and audited
   separately. A cross-range decision catalog is then reconciled and independently
   audited. Only source-supported explicit replacement can supersede a term. File
   order and timestamps do not establish precedence. Different periods/roles can
   remain independently active. Superseded terms are retained as appendix history,
   excluded from synthesis. Unresolved terms retain both sides and a formal question.
   Cycles, missing IDs and cross-topic replacements are rejected by code. Failed
   reconciliation withholds disputed terms rather than publishing both as active.
   Reconciliation uses the retained original quotations, not another full copy of
   the PDF text. Source coverage is still checked independently in bounded ranges.
   The provider schema now binds relationship state to its link shape: active has
   an empty `governing_ids` array; superseded/unresolved require other eligible IDs.
   Self-IDs are not offered in the link enum. Python retains the reciprocal-link,
   distinct-ID and cycle checks. Invalid responses remain invalid, not normalized.
   Acquisition findings have a required `acquisition_dimension`; set-aside status,
   competition method, vehicle, funding, evaluation and submission are distinct.
   Cross-dimension conflict/replacement links are not offered or accepted. Mappers
   split mixed-dimension assertions, and auditors must reject unsplit mixtures.
3. **Document stage is not obligation strength.** Every finding records both.
   Same-document RFI/draft context is attached to findings across source fragments
   and passed to synthesis and its auditor. Anticipated, optional and conditional
   obligations are not firm mandatory minima. An obligation written with `shall`
   inside a draft remains draft. The renderer shows these qualifiers in the main
   assessment rather than relying on an appendix caveat.
4. **Decision quantities must survive.** Staffing amounts and units, base versus
   option periods, and required experience/reference counts have explicit fields.
   The package audit checks five focused dimensions: acquisition selections,
   precedence, document status, staffing quantities and experience quantities.
   A missing material detail permits one append-only supplement and a new audit,
   not indefinite resampling. Persistent gaps restrict the recommendation. Staffing
   and experience findings appear in the main report even if initially classified
   as reference material. Repeated option-year CLINs and fee lines are not summed
   into base staffing.

## Evidence and Failure Behavior

- Model-selected source ranges still resolve to original extraction text in code.
  No evidence validator, 8,000-character selection bound, or 640,000-character
  request ceiling is relaxed.
- Form observations are labeled derived observations, not represented as verbatim
  PDF prose. Their appended offsets do not overlap the native extraction. Page and
  bounding-box provenance are retained.
- Existing package findings must pass source-fidelity review. A valid citation alone
  does not establish the truth of a model's interpretation.
- Failed judgment rows are excluded; no stock win themes replace them. Unresolved
  precedence or failed reconciliation cannot produce `pursue_discovery`.
- Source records, candidate maps, audits and superseded history remain in the audit
  result/receipts. Cached attachment identity includes the form-observation code;
  new preliminary contracts use a new version and request identities.
- Package-native incumbent/market statements are allowed with citations. The report
  does not claim that live external market research occurred or deny package facts
  through a blanket disclaimer.
- Missing profiles use an empty, zero-length evidence array, not a source selector
  compiled against an empty registry. This permits an unknown-fit assessment without
  fabricating vendor evidence. Missing proof is not a document-ambiguity question.

## Saved Live Contract Regressions

`scripts/tests/fixtures/preliminary_saved_contracts.json` contains the three original
reconciliation responses and seven rejected narrative rows from the frozen
three-package replay. It preserves original statements, quotations, metadata and
receipt hashes. It contains public-package excerpts, not vendor profiles or API
credentials. These recorded failures are not synthetic semantic gold labels.

`test_preliminary_saved_contracts.py` verifies that the original self-link responses
are rejected by the new provider schema as well as Python. Explicitly labeled
test-only expected variants empty the active links without changing source text;
they do not change the saved response or reclassify the recorded semantic conflicts.
The saved narrative rows are tested through admission, independent scripted audit
and rendering, with both approval and rejection controls. Additional synthetic
controls cover different acquisition attributes, real same-attribute conflicts,
unchecked/uncertain controls, invalid IDs, absent profiles and withheld judgments.

Version `3-preliminary-relationship-contract` invalidates earlier stage identities.
Old paid receipts are not silently relabeled or admitted under the new contract.
An independent reconciliation audit is still required before capture synthesis.

## Offline Acceptance

The synthetic tests cover native controls, flattened controls, uncertain marks,
conflicting observations, missing bounding boxes, review-budget overflow, late-page
controls, annotation offsets, cache invalidation, cross-partition amendments,
unresolved conflicts, failed reconciliation, draft-context propagation, rejected
strengthening of anticipated staffing, base/optional quantities, and required
reference counts varied across unrelated examples.

Run the focused tests:

```bash
python3 -B -m unittest scripts.tests.test_preliminary_decisions \
  scripts.tests.test_preliminary_saved_contracts \
  scripts.tests.test_preliminary_decision_pipeline \
  scripts.tests.test_pdf_form_choices scripts.tests.test_preliminary_capture \
  scripts.tests.test_pdf_page_coverage
python3 -B scripts/tests/export_semantic_prompts.py --check
```

For the broader offline release suites, use `scripts/tests/run_release_offline.py`
with a new `--output` folder. It removes provider credentials from child processes
and records command exit codes, logs and source hashes.

## What Offline Success Does Not Establish

Mocked model responses demonstrate wiring, provenance, failure isolation and
rendering. They do not establish live model accuracy or perfect detection of every
flattened/raster control. A checkbox observation can still be uncertain or wrong;
classification and materiality audits still depend on model reasoning.

Before promotion, replay the unchanged packages and profiles in fresh workspaces.
Inspect the selected acquisition option, explicit price-validity replacement,
draft/anticipated staffing language, base versus optional staffing, and required
reference count in the actual rendered reports. Preserve all failed runs. Do not
merge merely because the offline scorecard passes.

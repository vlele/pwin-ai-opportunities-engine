# Evidence Selection Contract

The live understanding pipeline selects evidence; it does not ask the model to
transcribe source quotations. This is a transport change, not a relaxation of
semantic auditing or the capture completion gate.

## Model Interface

- Source fragments retain immutable IDs such as `D3:1600`.
- Each fragment displays numbered evidence lines. Long single-line prose can be
  partitioned at sentence boundaries. No source characters are deleted.
- Select `start` and `end`, each containing `ref` and `line`. Endpoints are inclusive.
- The provider schema binds each fragment ID to its actual line count. Code groups
  fragments with equal bounds in a shared definition; a line valid in one fragment
  is not valid in another with fewer lines. Empty fragments are not selectable.
- Runtime validation still rejects reversed, overlong, cross-document, gapped,
  or out-of-scope ranges. Valid endpoints do not prove semantic support.
- Code retrieves exact source text and materializes the existing `ref` / `quote`
  graph. Cross-fragment selections become separate exact anchors, not invented
  concatenated quotations.
- Isolated component comparisons select only `evidence_id` entries from their
  declared claim/context choices. Broader source context does not grant credit.
- Component wording is input data, not a fixed schema literal or model-echoed
  response field. The comparator returns code-owned identity fields and a finding;
  validation binds that identity to the original component text without stripping
  quotes, measurements, negations or PDF punctuation. Source wording does not change
  the provider schema. Component-to-reason fidelity still requires semantic auditing.

Unknown IDs, invalid bounds, reversed ranges, document/role crossings, gaps,
overlaps, and selections longer than 8,000 characters fail closed. A shared enum
constrains model output to actual fragment IDs without duplicating it throughout
the schema. The context budget is checked on the actual model request, including
instructions, schema and selection labels, not the larger persisted provenance registry. No truncation is
used to meet that budget.

The base inventory and evidence-selection prompts expose the 8,000-character
selection limit before the first attempt. It is a character limit, not a page
allowance. Narrow focus citations must not lose material tasks, exceptions or
qualifications: retain additional passages as separate bounded selections in
supporting context, or separate records for genuinely distinct subjects. An
introduction alone is not a substitute for the operative requirement text.

Source roles come from span metadata, not fragment-ID prefixes. Requirement
`focus` and `supporting_context` must cite `kind="package"`, including metadata
and precedence records. Private profile assertions belong in `claims`.
`quoted_vendor_context` preserves package-provided references, not profile text
relabelled as government evidence. Existing runtime source-role checks remain.

When evidence selections are invalid, the single allowed contract correction is
restricted to those selections. The request keeps every original source span but
does not repeat the entire generated inventory. Code-owned repair IDs identify
invalid locations; the model may return bounded replacement ranges, not changed
claims, requirements, classifications or questions. Unaffected draft fields stay
unchanged, and the merged graph must pass the full original validator. This does
not increase range/context limits or turn a negative semantic verdict into a retry.

There is one narrow exception for independent ambiguity detection: a range or
source-role error permits category review for the affected signals and any
`official_conflict` signals in that draft. The repair receives the exact validation
error and corrected sources. `official_conflict` requires contradictory government
terms, not missing vendor eligibility or compliance proof. Genuine vendor ambiguity
uses an existing schema dimension; missing information stays a gap, not a question.
No claim, requirement, decision, or unaffected signal may be rewritten.

A separate source-based audit must approve each category change or gap disposition.
Original signals, proposed edits, exact citations and the audit verdict are retained
in checkpoint metadata. Unsupported or uncertain edits stop the run and remain
rejected on restart; they do not earn another repair attempt. The same single
contract-correction limit still applies.

## General Contract Correction

A different contract error, such as a private-source requirement with otherwise
valid ranges, can use the general whole-response correction rather than the
selection-only repair. Its `contract_correction.instruction` now explicitly
requires retention of previously valid claims and unrelated records, evidence,
package references, questions and resolved IDs. It prohibits clearing arrays or
dropping valid records to save space. If an invalid record cannot be corrected
faithfully and must be removed, question and `supersedes` indexes must be remapped
to the same retained subjects using existing zero-based indexes, not retargeted.

This general-path preservation rule is a model instruction, not a new immutable
merge mechanism. Structural validation rejects dangling indexes and invalid
sources; downstream source-coverage and semantic audits still determine fidelity.
Do not claim that prompt wiring tests guarantee a live model will preserve every
valid record. Only the selection-only repair mechanically preserves untouched
fields. Both paths still allow only one correction, with no larger evidence limit.

## Ledger Provenance Versus Selected Evidence

The ledger-to-inventory handoff has two independent checks, not a weaker standard
for records called definitions. `inventory_handoff.py` structurally checks that
every ledger fact maps to existing records with valid original package quotations.
Code keeps immutable ledger refs separately from the model's selected passages.

Each `fact_provenance` entry records `ledger_refs`, `selected_refs`,
`unselected_ledger_refs`, and `additional_selected_refs`. These are bookkeeping
fields generated by Python, not a model-supplied verdict. They survive batch merge
and exact-record interning. An unselected original reference is not automatically
a lost proposition: a definition can have sufficient evidence in one of several
original passages. Conversely, merely citing every reference does not prove that
the selected quotations retained a qualifier.

The independent handoff auditor receives the unchanged fact, retained records,
provenance, and the union of original and selected source spans. Provenance and raw
context do not automatically become selected evidence. The auditor must not repair
an incomplete record by reading omitted words from that context. A cropped actor,
negation, quantity, staffing allocation, condition, exception or operative reference
still fails. Definitions must retain restrictive language too; no record kind has
a blanket exemption. Headcount alone does not establish full-time hours or pricing.

Unknown sources, private-source requirements, fabricated quotations and invalid
fact/record links remain structural failures. Link diagnostics identify the fact
ID and record index so the existing single correction can target an actual error.
An unrelated but structurally valid package citation is rejected semantically, not
by assuming identical source IDs imply identical meaning. Unsupported or uncertain
handoff verdicts still block before decomposition and vendor comparison. No larger
selection budgets, automatic source additions or semantic retries are introduced.

Offline tests establish source preservation, request wiring, and gate behavior with
mocked verdicts. They do not establish live auditor accuracy. Saved-response replay
keeps the original blocked run unchanged and only shows which records can now reach
semantic review. Use `scripts/tests/replay_handoff_provenance.py --run <run-folder>
--output <private-output.json>`; do not commit the live source/profile artifacts.

## Lossless Coverage-Audit Encoding

Package-coverage auditing compares the inventory with every package source span,
in one request when it fits or in explicitly accounted partitions below. Before sizing and sending a request,
`scripts/common/audit_evidence_encoding.py` interns repeated, identical `ref` / `quote`
objects into a request-local `evidence_registry`. Their original positions contain
standard JSON pointers such as `{"$ref": "#/evidence_registry/E<sha256>"}`. The registry
contains the exact source reference and quotation, not a summary or external lookup.

Only repeated anchors that save space are interned. Different references never
share an identity merely because their text matches. Unique or short anchors remain
inline. Every source span, including uncited material needed to detect omissions,
remains available. All requirement/component fields, ordering, status, logic,
exceptions, precedence and package-reference records remain unchanged. The encoder
does not infer meaning, change verdicts or normalize source text.

The encoder restores the original wire payload and checks exact equality before
admitting the encoded form. Content-addressed registry entries and a canonical
payload digest detect dangling references, altered quotations or source spans,
lost records and unused registry entries. A complete encoded request must be
smaller than its original representation; otherwise the original is retained.
The codec operates after the existing transport's metadata handling, so round-trip
equality refers to that original model payload, not the larger on-disk span registry.

Both `audit_request_chars()` and the actual provider invocation use this same
transport. Receipts in `understanding_audit.stages[].audit_payload_encoding` record
the format, canonical digest, original/encoded payload sizes, registry entry count,
source-span count and successful round-trip check. Changed payloads invalidate
old request identities. The immutable canonical audit targets and verdict schema
are unchanged; response validation and downstream rendering still use those targets.
No LLM system prompt is changed for this representation.

The codec does not itself partition sources. The 640,000-character complete-request
limit remains. If an indivisible dependency still exceeds it, the run fails explicitly
without dropping evidence. Offline round-trip tests prove fidelity
of the representation, not live auditor comprehension or semantic accuracy.

## Accounted Source Partitions

`semantic_plan.preflight_audits()` runs after decomposition and before any vendor
comparison calls. It sizes all known source/claim audit requests, using the same
payload, prompt, encoding and schema as invocation. Comparison-result requests
cannot be sized exactly before their generated findings exist; they receive their
own exact size check afterward. This is not an advance guarantee about model output.

`audit_partitioning.py` keeps a fitting package-coverage request unchanged. Otherwise
it splits primary ownership into contiguous document/span ranges, shrinking ranges
until every request fits. It retains whole original inventory records, their exact
source anchors, adjacent-fragment context, and transitive explicit precedence links.
Uncited source text is still assigned to a primary range so omissions can be found.
Nothing is summarized, truncated or reclassified by the partitioner.

Each primary range receives a coverage check. Every pair of primary ranges also
receives a joint check for cross-range definitions, exceptions, conflicts and
precedence, including across documents. This is deliberately more conservative
and potentially more expensive than unrelated map-only checks. It does not prove
that a model will recognize every subtle dependency. An indivisible dependency
that cannot fit fails before comparison; it is not silently dropped.

`understanding_audit.coverage_manifest` records each original span exactly once
as a primary owner, with source hash, document/character range and available page
locations. `coverage_partition_audit` preserves cross-range check identities,
pending/supported/unsupported/uncertain verdicts, reasons and measured request sizes.
Supporting context may repeat; primary ownership may not. Unknown page metadata
stays unknown. The upstream attachment coverage gate remains in force.

The reduce gate verifies exact source/inventory identity, unchanged records, complete
range ownership, every cross-range dependency and every required verdict. A missing,
stale, unsupported or uncertain receipt cannot become a package coverage pass.
Neither an existing `passed` flag nor a model's general statement of completeness
substitutes for the required receipts. The canonical package-coverage verdict is
derived from all checks; other source-fidelity and vendor-fit audits remain required.
`source_audit_preflight` records size feasibility before comparison. Request receipts
remain keyed to source, prompt, schema, runtime code and settings by the existing
checkpoint layer, preventing reuse against changed inputs.

The partition auditor appends interface instructions defining primary/context scope
and original inventory IDs. Existing semantic rules and verdict enums are unchanged.
The exact assembled prompt is exported in `references/semantic-prompts/AUDITOR-PROMPT.md`.

Offline checks: `scripts/tests/test_audit_partitioning.py`. Use
`scripts/tests/replay_audit_partitions.py --run-dir /path/to/saved-run --output-dir /new/output`
to replay saved pre-audit responses and check both known-source and comparison-result
request sizes without a provider call. Synthetic reducer verdicts exercise wiring,
not semantic acceptance. That harness deliberately stops before the model auditor
and does not produce a capture memo.

## Provenance and Meaning

Audit stages retain the raw selection, retrieved response, exact quotations, and
document/page/character locations. Character offsets are zero-based, end-exclusive
Unicode positions in the retained extraction text, not PDF bytes or glyph boxes.
Native extraction and vision-derived text retain separate provenance. Vision text
is not independently verified just because a model produced it. If page metadata
does not exist for a historical packet or non-PDF source, its page is unknown.

Whitespace changes no longer need quotation repair: code supplies original text.
No fuzzy matching, number rewriting, negation removal, or synonym substitution is
performed. Source identity is not semantic support. The independent auditor still
checks numbers, qualifiers, negations, attribution, and whether a citation supports
the exact claim. A semantically unsupported verdict still blocks capture.

## Parent-Scoped Decomposition

Production inventory records preserve evidence, focus, claim attribution, package
references, questions and precedence, but do not pre-generate components or logic.
An undecomposed inventory cannot pass final plan validation. Component interpretation
runs only in the subsequent parent-scoped stage.

On the model wire, a parent declares `focus` and `supporting_context`, not an
independent duplicate `evidence` list. Code constructs its context once from those
explicit source selections. This is initial parent assembly, not a post-failure
union of child citations. Scope/meaning fidelity still requires the unchanged audit.

`scripts/common/requirement_context.py` freezes each validated parent's selected
context and assigns parent-specific, content-addressed evidence IDs. Decomposition
selects those IDs; code attaches their original quotations. The same paragraph in
another parent does not have the same admissible ID. Component text still requires
the independent source-fidelity audit; an ID is not semantic proof.

Requests are batched without source truncation, at most four parents and 64,000
payload/schema characters per batch. The existing total model-request budget still
applies. A parent too large for that contract fails explicitly rather than losing
qualifiers. Existing selected passages and the original selection/page/character
receipts remain available in the understanding audit.

When the parent context is insufficient, decomposition returns `needs_context`,
a reason and a retrieval query, not fabricated components. A separate package-only
selection call proposes passages; an independent audit sees the full package and
decides applicability to this exact subject. Only a supported proposal is attached.
The parent focus, status and precedence links do not change. Unsupported or uncertain
proposals stop without semantic resampling. Unavailable context remains explicit.
One expansion per parent and at most three per run are permitted; exhaustion blocks
without dropping the remaining parents. These are internal evidence requests, not
automatic questions to the user. Real ambiguity and official conflicts retain their
existing question channel.

`understanding_audit.requirement_contexts` records original catalogs, requests,
proposals, audit decisions, accepted expansions and bound components, including on
failure. Checkpoint identity includes the new code and each context-bearing request.
Historical combined-inventory and unrestricted decomposition helpers remain for
saved probe compatibility; the production orchestrator no longer calls them.

## Verification

`scripts/tests/test_evidence_selection.py` covers retrieval and negative controls.
`scripts/tests/test_inventory_prompt_guards.py` checks base/repair prompt wiring,
the exact range boundary, role metadata independent of ID prefixes, dangling links,
preservation in selection-only repair and the unchanged one-correction limit.
`scripts/tests/test_coverage_evidence_encoding.py` checks lossless round trips,
source-role isolation, integrity failures, budget measurement, runtime receipts
and preservation of negative audit verdicts across restart.
`scripts/tests/replay_coverage_encoding.py --run-dir /path/to/saved-run --output-dir /new/output`
reconstructs requests from saved live responses without API calls, verifies original
versus encoded payload equality, and checks all audit batches against the unchanged
budget. It stops before independent auditing; it does not fabricate successful
verdicts or declare a capture complete. Private saved runs stay outside the repository.
`scripts/tests/test_pdf_page_coverage.py` covers PDF coverage and page locations.
`scripts/tests/test_ambiguity_repair.py` covers bounded category review, genuine
conflict retention, missing-proof gaps, source-role rejection and restart integrity.
`scripts/tests/test_component_wire.py` covers content-independent comparator schemas,
exact text restoration, immutable identity and shared burden-of-proof policy. Its
three live tests require explicit `PWIN_LIVE_COMPONENT_TEST=1` and a fresh
`PWIN_LIVE_TEST_AUDIT_DIR`; they incur API charges and check real HTTP 200 responses
and decisions, not mocked provider success. Generic offerings must remain missing,
while explicit relevant reported delivery can receive credit within its stated scope.
Existing pipeline fixtures use a test-only wire adapter; their verdicts, routing
expectations, and negative semantic assertions remain unchanged. Production code
does not accept legacy model-generated quotes or use that test adapter.

A full local-file replay must use an unchanged input PDF/profile and a fresh
workspace. Passing citation tests alone does not establish an end-to-end capture
success. Report the exact stopping gate, provider usage, and unresolved questions.

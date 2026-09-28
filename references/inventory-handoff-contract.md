# Inventory Handoff Contract

## Inline Fact Ownership

The package inventory model selects `originating_fact_ids` on every requirement
and package-provided vendor-context record. It does not return `fact_coverage` or
count positions in a separate fact-to-record map. The IDs are constrained to the
current batch's fact ledger. The list form supports one fact with several
material propositions and several facts legitimately retained in one record.

```json
{
  "originating_fact_ids": ["F0", "F1"],
  "area": "timing",
  "task": true,
  "status": "current",
  "record_kind": "requirement",
  "supersedes": [],
  "focus": [
    {"start": {"ref": "D0:0", "line": 1}, "end": {"ref": "D0:0", "line": 2}}
  ],
  "supporting_context": []
}
```

This is a schema example, not a validated assertion or a solicitation-specific
rule. The supplied source must actually support the selected fact identities.

Python rejects missing, unknown, duplicate-within-record, empty or wrongly typed
fact IDs and checks that every ledger fact is represented. It derives the
internal `fact_coverage` receipt from enumerating the validated record arrays.
Exact-record interning deduplicates internal links without erasing any fact's
ownership or source lineage. Reordering records cannot leave a model-generated
fact pointer dangling.

Questions, explicit precedence relationships and vendor-source dispositions
retain their existing separate interfaces and strict index checks. This patch
does not claim to eliminate every positional interface in the pipeline.

## Complete Vendor Citations

Every claim listed under `vendor_coverage[ref].claims` must explicitly cite that
same source ref in that claim's `evidence` array. Consolidated duplicate fields
still retain separate source selections, even when the words are identical.
A citation in another claim or a coverage reason does not satisfy this check.
Do not attach unrelated text merely to satisfy coverage. Non-assertion sources
retain an explicit empty claim list and a source-grounded disposition for audit.

This clarification changes the vendor inventory prompt, not the existing
validator or schemas. Both initial generation and the bounded contract correction
use the assembled vendor prompt. A mocked response with both citations tests
structural acceptance only; the independent semantic auditor remains required.
Saved failed responses are never rewritten, promoted or used as passing receipts.

## Unchanged Evidence Gates

Fact accounting is structural, not semantic. The independent handoff auditor
still compares each fact and the original sources against its retained records.
An unrelated selection or omitted actor, deadline, trigger, exception or negation
must fail or remain uncertain. Source lineage is not permission to fill missing
selected evidence automatically. Source-role, bounded-selection, full-source
coverage, question and downstream component gates are unchanged.

Administrative requirements are not silently discarded by this change. Existing
component routing separates proposal formatting from vendor-fit comparison.
Changing a full capture product into a capability-only assessment would require
an explicit scope policy, disclosure and corresponding tests; it is not an
auditor bypass or a fix for malformed references.

## Receipts and Tests

The handoff and understanding versions change. Old model responses or semantic
receipts must not be rekeyed to the new contract. Historical replay tooling may
translate only valid explicit legacy fixture links into inline ownership for an
offline comparison. It must reject dangling links, preserve original artifacts,
and label transformed fixtures separately from actual model outputs.

Offline tests cover row reordering, 30-row inventories, missing/unknown/duplicate
IDs, one-to-many and many-to-one ownership, package references, source roles,
unchanged question/precedence validation and rejection of cropped evidence.
Mocked audit verdicts test gate behavior, not live model accuracy. A live run
remains necessary before claiming end-to-end success.

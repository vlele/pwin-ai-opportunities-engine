# Preliminary Capture Assessment: Human-Reviewed Beta

Release decision: authorized on 2026-09-29 for supervised preliminary research.
This is not a semantic-stable release, an autonomous pursuit decision, or a
proposal-readiness certification. The earlier strict semantic gate did not pass;
the maintainer has explicitly accepted the limitations below for a beta on main.

## Intended Use

Use `--depth preliminary` with the supplied solicitation package and vendor
profile. The engine reads bounded source ranges, develops workstream-level
capture reasoning, checks it with model auditors, and renders a preliminary
assessment with a Proposal Readiness Review appendix.

A capture manager remains responsible for checking the decision-changing
interpretations. Generic vendor positioning is not independently verified
experience. Missing proof does not establish inability. Routine commercial terms,
such as an ordinary price-hold period, should be reference items rather than
automatic reasons to reject a pursuit.

Preliminary mode does not perform live public, SAM.gov, USAspending or GovTribe
enrichment. An issued historical solicitation is not proof of a currently open
opportunity. Verify procurement status and later amendments separately. The
legacy `full_360` CLI default still exists; pass the intended depth explicitly.
This beta evaluation does not certify all strict, discovery, enrichment, or
integration workflows.

## Meaning of Audited*

**Audited\*** means an automated model audit approved the item; its meaning or
attached evidence may be incomplete. It is not human verification, vendor proof,
or assurance that every cited quotation supports every part of a conclusion.

The asterisk qualifies all automated approvals, not just defects the pipeline
has detected. Failed or uncertain model-audit verdicts remain **Unverified**.
Earlier source approval is distinct from later interpretation or precedence
approval. Rejected interpretations remain visible with reasons and trustworthy
quotations when available; they do not become positive fit evidence.

The label is a disclosure, not a semantic repair. The beta does not turn a false
claim into a true one, replace missing evidence, or waive existing validation.

## Known Limitations

### BETA-01: Conditional Rules Can Be Broadened in a Summary

In the IETSS evaluation, the source findings correctly separated Veterans
Involvement evaluation-credit conditions from the subcontracting-plan obligation
for a large-business award. Judgment A-7 combined the conditions with "or" and
made VETCert proof sound mandatory for a large business merely because it was
large. The automated auditor accepted that summary.

The underlying finding identifiers were F5-7 and F5-9. Treat the combined A-7
interpretation as needing correction; do not infer that large-business status
alone triggers the veteran-credit condition. This is a recorded model error in
that supplied package, not a general procurement-law determination.

Follow-up: retain each condition and its own consequence when summarizing several
findings. Regression tests should reject conclusions that apply one branch's
consequence to a different branch. Do not add an IETSS-specific parser exception.

### BETA-02: A Correct Fact Can Have an Incomplete Attached Citation

CES finding F1-18 correctly says five recent/relevant past-performance references
are requested. However, its attached quotations selected D13:0 and D13:3200,
omitting D13:1600, the intervening paragraph that actually states the count. The
audit accepted the evidence attachment and judgment A-3 repeated the finding.

The count exists in the source; it was not invented. The defect is the claim's
evidence attachment. Exact-substring validation proves a quotation is present,
not that it supports every assertion. Reviewers must locate the count in the
original instructions rather than treat the audit label as sufficient proof.

Follow-up: test exact claim-to-selected-evidence support while preserving adjacent
fragment provenance. Do not drop the requirement or unrelated accepted findings.

### BETA-03: The Auditor Can Produce False Positives

The FMBT extractor retained "anticipates" and `force: anticipated` for the draft
staffing counts, but the auditor objected as if the counts had become firm
mandates. That rationale appears inconsistent with the saved extraction. The
report retains the anticipated quantities as an unverified interpretation and
continues; it does not silently erase them or establish vendor inability.

Follow-up: use this record as a negative control against over-rejection, alongside
tests that still reject genuine changes from anticipated to required.

### Other Practical Limits

- The sample reports are verbose. Main bodies ranged from about 3,200 to 8,300
  words; repeated qualifiers and source quotations can obscure the main decision.
- Historical deadlines sometimes receive overly current wording despite the
  current-status disclaimer. Confirm dates and status before action.
- Generic profile tags can produce tentative alignment or teaming hypotheses.
  These are diligence ideas, not verified delivery, named partners, or proof that
  a company can perform every suggested role.
- Coverage is scoped, not an exhaustive clause/compliance inventory. Partial
  assessments and disclosed token-limit omissions are legitimate outputs.
- The four-family replay used cases seen during development. One run per family
  is neither blind validation nor a reliability/stability estimate.

## Human Review Before Use

1. Confirm the package version, amendments, procurement stage and current dates.
2. Check eligibility, OCI, access, significant staffing, experience and pricing
   structure against the original sources. Preserve conditions and qualifiers.
3. Confirm the selected quotations support each decision-changing assertion,
   including numbers, exclusions, roles, timing and negations.
4. Distinguish vendor self-report, verified delivery, missing evidence and
   speculation. Do not adopt a proposed teaming role without supporting evidence.
5. Read Unverified interpretations and the token-limit disclosure. Use the
   readiness appendix as a reference, not a completed compliance checklist.
6. Record human corrections or unresolved questions before using a report to
   commit proposal resources. An Audited* label alone is not sign-off.

## Validation Evidence and Acceptance

The 2026-09-29 frozen preliminary replay completed IETSS/PSI, EBMS/PSI, FMBT/PSI
and CES/CSEngineering. All four rendered partial preliminary assessments with
readiness appendices. There were 64 successful API requests, no provider errors,
and no completion-token stops. Estimated usage cost was $3.29 under the existing
harness assumptions, not a provider invoice or account-balance check.

| Case | Accepted package findings | Audited judgments | Visible review notes |
| --- | ---: | ---: | ---: |
| IETSS | 50 | 13 | 8 |
| EBMS | 72 | 8 | 6 |
| FMBT | 23 | 12 | 5 |
| CES | 19 | 9 | 2 |

The new failure-isolation policy preserved IETSS hybrid pricing and OCI findings.
EBMS retained Unrestricted separately from sole source and kept the superseding
180-day price hold in the readiness appendix without making it a pursuit veto.
FMBT preserved its OCI warning. CES retained civil-engineering scope, staffing
structure and the five-reference requirement. Those improvements coexist with
the known defects above; successful generation is not semantic certification.

After adding Audited*, offline validation recorded 800 passing tests, 6 opt-in
live tests skipped (806 collected), all 16 release suites passing, prompt-export
wiring passing, and a clean diff check. The four reports were re-rendered without
new model calls or changes to decisions/evidence. Original live artifacts remain
preserved locally. They are not published in this repository as full vendor
profiles, credentials, provider requests, or private workspace reports.

The beta accepts those residual issues for supervised experimentation. It does
not reinterpret the prior NO-GO for an unqualified main release as a semantic
pass, and it does not authorize unattended bid/no-bid decisions.

## Reproducing Offline Checks

From the repository root, use a new output directory:

```bash
python3 -m unittest scripts.tests.test_preliminary_audit_labels
python3 scripts/tests/export_semantic_prompts.py --check
python3 scripts/tests/run_release_offline.py --output /absolute/new/offline-output
```

These checks do not run a paid capture. Live replays require separate credentials,
inputs, a bounded budget, and manual review. Preserve adverse results instead of
rerunning until a preferred answer appears.

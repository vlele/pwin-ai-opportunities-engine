# Capture Research Playbook

Use this playbook only when the `research` mode is selected.

## Principle

The output must be a fresh brief for the current request.

Old briefs are context only.

The target is a 360-degree GovCon research brief, not a thin notice memo.

## Deliverables

Every capture run should try to produce:

1. An executive brief that explains:
   - each objective in plain English
   - why it matters now
   - mission, policy, and funding pressure
   - risks, constraints, and likely success metrics
   - incumbent and competitor posture
   - recommended win themes and proof points
2. An evidence annex that includes:
   - a dated source log
   - objective-linked snippets or quotes
   - traceable confidence scores

## Required flow

1. Resolve the entry.
2. Write the request log.
3. Reserve request-specific paths.
4. Gather local notice context and attachments.
5. Decompose the requirement into multiple objective statements when evidence permits.
6. Pull fresh public enrichment across:
   - agency mission and strategy
   - policy and compliance
   - budget and acquisition timing
   - oversight and audit
   - stakeholder and leadership signals
   - related procurements, incumbents, and vehicle clues
7. Render the full section set.
8. Validate.
9. Answer from the rendered brief.

## Research expectations

Official sources should be attempted first.

High-value categories include:

- agency or bureau strategic plan
- IT, digital, data, AI, or zero-trust strategy
- budget in brief or congressional budget justification
- acquisition forecast or industry-day artifact
- GAO or OIG findings tied to the objective
- policy references explicitly named in the solicitation or attachments
- SAM.gov attachments, amendments, and Q&A
- USAspending award history and related performers
- official leadership bios, testimony, or public priorities

## Partial is allowed

`PARTIAL_CAPTURE_RESEARCH` is valid only when:
- the brief contains the full section set
- unavailable sections say why they are unavailable
- the evidence object reflects the same gaps
- the objective matrix still renders objective-by-objective rows, even if some cells are provisional

## Not allowed

- seed stub as final answer
- menu-only response before the brief exists
- direct reuse of `*-capture.md` as current output
- claiming `360_DEEP_RESEARCH_COMPLETE` without broad public-source coverage beyond the notice alone

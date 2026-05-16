# Capture Research Playbook

Use this playbook only when the `research` mode is selected.

## Principle

The output must be a fresh brief for the current request.

Old briefs are context only.

## Required flow

1. Resolve the entry.
2. Write the request log.
3. Reserve request-specific paths.
4. Gather local notice context.
5. Attempt fresh public enrichment.
6. Render the full section set.
7. Validate.
8. Answer from the rendered brief.

## Partial is allowed

`PARTIAL_CAPTURE_RESEARCH` is valid only when:
- the brief contains the full section set
- unavailable sections say why they are unavailable
- the evidence object reflects the same gaps

## Not allowed

- seed stub as final answer
- menu-only response before the brief exists
- direct reuse of `*-capture.md` as current output

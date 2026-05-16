# Security guidance

This `v15` bundle includes small local Python scripts in addition to Markdown and JSON templates.

## What is in scope

- Markdown skill instructions
- JSON and Markdown templates
- small local Python scripts
- examples and reference notes
- release metadata files

## What is not in scope

- embedded credentials
- third-party Python dependencies
- automatic email sending
- automatic proposal submission

## Security posture for `v15`

### 1. Keep the scripts deterministic

The scripts in `scripts/` should:
- use the Python standard library only
- avoid dynamic code execution
- avoid shelling out except where the operator explicitly allows it
- write only inside the active workspace

### 2. Keep secrets out of logs

- never print `SAM_API_KEY`
- never persist secret values into `procurement/`
- never write secret fragments into drafts, evidence, or run logs

### 3. Prefer official sources

Use:
- `SAM.gov`
- `USAspending.gov`
- `SBA SUBNet`
- `Acquisition.gov`

Treat commercial sources as optional enrichment only when explicitly enabled.

### 4. Treat browser automation as higher risk

Browser retrieval may be necessary, but it is less deterministic than direct API use.

Use it only when:
- official API retrieval is unavailable or incomplete
- the page is JS-wrapped
- the user explicitly asked for browser execution

### 5. No automatic outbound communications

Drafting emails is allowed.

Sending emails, outreach, submissions, or forms should require:
- explicit user approval
- sender identity details
- a clear send action outside the passive research path

### 6. Validate before presenting

The model should not present:
- a seed stub as a final brief
- a legacy brief as if it were fresh
- a menu-only response as completed research

### 7. Recommended deployment posture

- use a dedicated agent and workspace
- keep network access constrained where practical
- review script changes like code, not like prompt text
- keep a golden example set for regressions

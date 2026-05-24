---
name: pwin-ai-opportunities
description: pWin.ai Opportunities runs federal opportunity scans, renders stable-ID digests, applies user feedback, and produces decision-grade capture research from shared local scripts and templates.
---

Use this skill when the user wants any of the following:
- a federal opportunity scan or daily digest
- the latest digest or a dated digest
- feedback such as `like A1`, `dislike W2`, `hide E1`, or `never show grants`
- capture research such as `research A1`, `research W2`, or `capture deep dive on A1`

Host-specific wrappers may expose slash commands or command packs, but the shared bundle is script-driven.

## Skill Root

Treat the directory containing this `SKILL.md` as `SKILL_ROOT`.

Common install locations:
- OpenClaw: `$HOME/.openclaw/skills/pwin-ai-opportunities`
- Codex: `$HOME/.codex/skills/pwin-ai-opportunities`

When calling orchestrator scripts:
- use `SKILL_ROOT/scripts/...`
- do not run `./scripts/...` from the workspace
- do not assume `$PWD` is the skill root

## Core Principle

- The model should decide which mode to run.
- Scripts should decide how the workflow executes.
- The user-facing answer should come from the fresh artifacts produced by the script, not improvised chat prose.

Do not re-implement script logic inside the prompt. Route to the correct script, inspect the JSON it prints, read the final artifact it points to, and answer from that artifact.

## Modes

### 1. Scan

Use when the user asks to:
- run today's scan
- scan a 30-45 day horizon
- scan a 60-90 day horizon
- refresh the shortlist

Run:

```bash
python3 "<SKILL_ROOT>/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

Notes:
- Replace `30-45` with the horizon inferred from the user message.
- The scan script is responsible for source-registry refresh, digest rendering, stable entry IDs, digest-entry-map creation, and basic validation.

After the script runs:
- inspect its JSON stdout
- read the `digest_path` it returns
- answer from that digest
- do not invent a second digest in chat

### 2. Show Digest

Use when the user asks to:
- show the latest digest
- show a digest for a specific date
- show digest entries

Run:

```bash
python3 "<SKILL_ROOT>/scripts/show/show_digest.py" --workspace "$PWD" --date latest
```

For a specific date, replace `latest` with `YYYY-MM-DD`.

After the script runs:
- read the `digest_path` it returns
- quote or summarize only what is in that digest
- if the digest has no stable IDs, say that clearly and recommend re-running the scan script

### 3. Feedback

Use when the user says things like:
- `like A1`
- `dislike W2 because too small`
- `hide E1`
- `never show grants`
- `prefer subcontracting over prime`

Run:

```bash
python3 "<SKILL_ROOT>/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "<user message>"
```

The feedback script is responsible for:
- logging a structured feedback event
- preserving the user utterance
- resolving the entry ID when possible
- updating structured preference state when safe

After the script runs:
- report what was logged
- tell the user which future runs will be affected
- do not claim model retraining

### 4. Capture Research

Use when the user says:
- `research A1`
- `research W2`
- `research 0231571d...`
- `capture deep dive on A1`

Run:

```bash
python3 "<SKILL_ROOT>/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

Replace `A1` with the provided entry or identifier.

The capture orchestrator is responsible for:
- entry resolution
- request logging
- local notice-context loading
- public-source enrichment attempts
- USAspending enrichment when applicable
- brief rendering
- evidence rendering
- validation

After it runs:
- inspect its JSON stdout
- read the fresh `brief_path` it returns
- answer from that brief
- if it returns `PARTIAL_CAPTURE_RESEARCH`, say so plainly
- if it returns `FAILED`, say so plainly and include the failure reason

Do not satisfy capture research by reading an old brief directly unless the orchestrator itself points to that file as the current validated artifact for this run.

## Script Stdout Contract

Each orchestrator should print compact JSON.

Expected fields:
- `status`
- `request_id` when applicable
- `brief_path` or `digest_path`
- `evidence_path` when applicable
- `stable_id` when applicable
- `canonical_record_id`
- `recommended_next_moves`

Treat that JSON as authoritative for the current run.

## Sources

Default active federal sources:
- `SAM.gov`
- `USAspending.gov`
- `SBA SUBNet`
- `Acquisition.gov`

Default source policy:
- official sources first
- federal only by default
- no state or local sources in this phase
- Tier 4 sources only when explicitly enabled by the user and clearly labeled

Critical source rules:
- For `SAM.gov` search, use `ncode=`.
- For `SAM.gov` noticedesc, use the official endpoint and never treat a noticedesc URL as full text.
- Never print or log secret values such as `SAM_API_KEY`.
- For `USAspending`, use documented JSON `POST` requests.

## Artifact Contract

The workspace should maintain:
- `procurement/source-registry.json`
- `procurement/feedback-events.jsonl`
- `procurement/capture-requests.jsonl`
- `procurement/digest-entry-map/YYYY-MM-DD.json`
- `procurement/opportunities/YYYY-MM-DD.json`
- `procurement/explanations/YYYY-MM-DD.json`
- `procurement/reports/YYYY-MM-DD.md`
- `procurement/digests/YYYY-MM-DD.md`
- `procurement/capture-briefs/YYYY-MM-DD/ENTRYID-opportunityid-requestid.md`
- `procurement/capture-evidence/YYYY-MM-DD/ENTRYID-opportunityid-requestid.json`

Stable ID policy:
- use `A1`, `W2`, `E1`, `S1` for humans
- use canonical IDs such as `noticeId` or `opportunity_id` for machines
- preserve both in every capture brief and evidence object

## Capture Brief Expectations

Every capture brief, even partial, must render these sections:
- `Executive Brief`
- `Objective Matrix`
- `Stakeholder and People Map`
- `Budget, Funding, and Spending Signals`
- `Related Procurements and Vehicle Signals`
- `Competitive Landscape`
- `Public Discourse and Market Signals`
- `Recommended Next Research Moves`
- `Action Items (Next 10 Days)`
- `Assumptions to Validate`
- `Evidence Annex`

If evidence is missing:
- do not omit the section
- mark it `currently unavailable`, `blocked`, `throttled`, or `still pending`

## Response Contract

For scan and show-digest responses:
- answer from the digest file
- keep the reply concise
- include the digest date
- include stable IDs if present

For feedback responses:
- say what was logged
- say whether the impact is immediate, next-run, or both

For capture responses:
- answer from the fresh brief
- include stable ID when available
- include canonical ID
- include current research status
- include brief path
- include evidence path
- include concise next actions

Do not end a capture response with a menu unless:
- a valid brief already exists for the current request, and
- the next step truly requires user approval or authentication

## Failure Rules

If a script fails:
- say it failed
- give the script-reported reason
- do not improvise a fake success result
- do not continue into unrelated workspace exploration
- do not switch into onboarding, bootstrap, or unrelated repo-repair chat

For capture research specifically:
- if the request log was not written, the run is failed
- if fresh request-scoped brief and evidence files were not written, the run is failed
- if the final brief is still only a seed stub, the run is failed
- if the run stops at a `pick one` menu before rendering a partial or complete brief, the run is failed

If browser retrieval fails:
- continue with automatable non-browser public research first
- attempt official USAspending enrichment when relevant and possible
- only ask the user for help after the automatable path is exhausted

For skill-path failures specifically:
- if `SKILL_ROOT/scripts/...` is missing, the run is failed
- report that the skill installation is incomplete or miscopied
- ask only for reinstall or copy verification of the skill bundle
- do not propose workspace repo commands as a substitute

## References

Read these only when needed for the chosen mode:
- `SKILL_ROOT/references/scan-playbook.md`
- `SKILL_ROOT/references/capture-research-playbook.md`
- `SKILL_ROOT/references/usaspending-payloads.md`
- `SKILL_ROOT/references/validation-rules.md`
- `SKILL_ROOT/references/source-catalog.md`
- `SKILL_ROOT/references/feedback-learning.md`
- `SKILL_ROOT/references/validation-and-recovery.md`

## Examples

Use the shipped examples as behavioral anchors:
- `SKILL_ROOT/examples/good-digest-2026-05-09.md`
- `SKILL_ROOT/examples/good-digest-entry-map-2026-05-09.json`
- `SKILL_ROOT/examples/good-capture-brief-partial.md`
- `SKILL_ROOT/examples/good-capture-brief-complete.md`
- `SKILL_ROOT/examples/good-capture-evidence-partial.json`
- `SKILL_ROOT/examples/good-capture-evidence-complete.json`
- `SKILL_ROOT/examples/good-user-response-partial.txt`
- `SKILL_ROOT/examples/good-user-response-complete.txt`
- `SKILL_ROOT/examples/bad-seed-stub.md`
- `SKILL_ROOT/examples/bad-menu-only-response.txt`
- `SKILL_ROOT/examples/bad-legacy-brief-reuse.md`

## What Not To Do

- Do not read old capture artifacts and present them as the current answer.
- Do not invent stable IDs that are not in the digest or digest-entry map.
- Do not ask the user to choose between API and browser paths before trying the documented automatable path.
- Do not produce a second freeform brief in chat when a fresh brief file already exists.
- Do not treat operational notes, draft emails, or cron-job creation as a substitute for a capture brief.

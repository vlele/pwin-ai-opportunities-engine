---
name: pwin-ai-opportunities
description: pWin.ai Opportunities runs federal opportunity scans, renders stable-ID digests, applies user feedback, and produces decision-grade capture research from shared local scripts and templates.
---

Use this skill when the user wants any of the following:

- onboarding or bootstrap from a company website
- seeding `vendor-profile.json` or starter workspace files
- a federal opportunity scan or daily digest
- the latest digest or a dated digest
- feedback such as `like A1`, `dislike W2`, `hide E1`, or `never show grants`
- capture research such as `research A1`, `research W2`, or `capture deep dive on A1`

Host-specific wrappers may expose slash commands or command packs, but the shared bundle is script-driven. If a helper or playbook is not present in the installed bundle, do not assume an alternate onboarding path exists.

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

- The model should decide which shipped mode to run.
- Scripts should decide how the workflow executes.
- The user-facing answer should come from the fresh artifacts produced by the script, not improvised chat prose.

Do not re-implement script logic inside the prompt. Route to the correct script, inspect the JSON it prints, read the final artifact it points to, and answer from that artifact.

## Modes

### 0. Bootstrap / Onboarding

Use when the user asks to:

- bootstrap a workspace from a company website
- seed `vendor-profile.json`
- create starter onboarding files
- get started from a company URL

Run:

```bash
python3 "<SKILL_ROOT>/scripts/bootstrap/bootstrap_workspace.py" --workspace "$PWD" --company-url "<company url>"
```

If the user supplies NAICS codes, add:

```bash
--naics "541511,541512"
```

If the user says the NAICS are only tentative, add:

```bash
--naics-status candidate
```

After the script runs:

- inspect its JSON stdout
- read the `starter_profile_path` it returns
- report the files created
- summarize the inferred company summary, candidate competencies, and candidate NAICS
- clearly label website-derived facts as provisional until confirmed

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
- The scan script refreshes the runtime source registry, writes dated snapshots, builds stable entry IDs, and renders the report and digest.
- The shipped source set is federal-only and currently implemented for `SAM.gov` plus `USAspending.gov` enrichment.

After the script runs:

- inspect its JSON stdout
- read the `digest_path` it returns
- answer from that digest
- do not invent a second digest in chat
- if the scan reports `no_naics`, say plainly that the current workspace does not have usable NAICS for SAM retrieval

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
- use `digest_entry_map_path` when present for stable IDs
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
- recomputing learned preferences in `preferences.json`

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
- `run capture on these local files`

Run:

```bash
python3 "<SKILL_ROOT>/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
```

Replace `A1` with the provided entry or identifier.

For direct local-file capture, provide one or more files plus enough metadata to label the opportunity:

```bash
python3 "<SKILL_ROOT>/scripts/capture/run_capture_research.py" \
  --workspace "$PWD" \
  --file "/absolute/path/to/PWS.pdf" \
  --file "/absolute/path/to/QA.docx" \
  --title "Example opportunity" \
  --buyer "Department of Example" \
  --solicitation-number "ABC123" \
  --depth full_360
```

You can also combine tracked capture with extra local files:

```bash
python3 "<SKILL_ROOT>/scripts/capture/run_capture_research.py" \
  --workspace "$PWD" \
  --entry "A1" \
  --file "/absolute/path/to/amendment.pdf" \
  --depth full_360
```

The capture orchestrator is responsible for:

- entry resolution
- request logging
- local notice-context loading
- public-source enrichment attempts
- USAspending enrichment when applicable
- brief rendering
- evidence rendering
- brief validation

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

The shipped runtime contract is federal-only.

Currently implemented sources:

- `SAM.gov` live contract opportunities
- `USAspending.gov` award-history enrichment

Source rules:

- official sources first
- federal only by default
- no state or local sources in this release
- do not describe stale source IDs from older revisions as active shipped behavior

Critical source rules:

- For `SAM.gov` search, use `ncode=`.
- For `SAM.gov` noticedesc, use the official endpoint and never treat a noticedesc URL as full text.
- Never print or log secret values such as `SAM_API_KEY`.
- For `USAspending`, use documented JSON `POST` requests.

Not in the shipped source contract:

- SBA SUBNet
- Acquisition.gov forecasts
- GSA eBuy Open
- grants sources
- commercial enrichment portals

## Runtime Files

Operator-managed inputs commonly read by the shipped modes:

- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/vendor-profile.json`

Notes:

- `vendor-profile.json` is optional at the file-system level, but the scan path will return `no_naics` if it cannot derive usable NAICS from the current workspace inputs.

The workspace should maintain these shipped runtime artifacts:

- `procurement/vendor-profile.json`
- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/STARTER_PROFILE.md`
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
- preserve both in digest-entry-map data and capture outputs

## Capture Brief Expectations

The shipped capture validator currently requires these headings:

- `## 1. Executive Capture Judgment`
- `## 2. Opportunity Snapshot`
- `## 3. Pursuit Recommendation and Score`
- `## 4. Evidence Ledger`
- `## 5. Document Inventory and Missing Items`
- `## 6. Customer and Mission Analysis`
- `## 7. Funding and Spending Trend Analysis`
- `## 8. Acquisition Strategy`
- `## 9. Incumbent Analysis`
- `## 10. Contracting Office and Stakeholder Map`
- `## 11. Competitive Landscape`
- `## 12. Partner and Teaming Analysis`
- `## 13. Fit Against Our Capabilities and Past Performance`
- `## 14. Subtle Signals and Capture Implications`
- `## 15. Recommended Win Strategy`
- `## 16. Questions to Ask`
- `## 17. Action Plan`
- `## 18. Assumptions, Unknowns, and Confidence`

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
- if the final brief still contains placeholders or is missing required headings, the run is failed
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

- `SKILL_ROOT/references/onboarding-playbook.md`
- `SKILL_ROOT/references/scan-playbook.md`
- `SKILL_ROOT/references/capture-research-playbook.md`
- `SKILL_ROOT/references/usaspending-payloads.md`
- `SKILL_ROOT/references/validation-rules.md`
- `SKILL_ROOT/references/source-catalog.md`
- `SKILL_ROOT/references/feedback-learning.md`
- `SKILL_ROOT/references/validation-and-recovery.md`

## Examples

Use the shipped examples as behavioral anchors:

- `SKILL_ROOT/examples/commands-bootstrap.txt`
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

- Do not ask the user to hand-author starter files when the bootstrap script can seed them.
- Do not read old capture artifacts and present them as the current answer.
- Do not invent stable IDs that are not in the digest or digest-entry map.
- Do not ask the user to choose between API and browser paths before trying the documented automatable path.
- Do not produce a second freeform brief in chat when a fresh brief file already exists.
- Do not treat operational notes, draft emails, or cron-job creation as a substitute for a capture brief.
- Do not claim unsupported sources are active just because they appeared in older revisions of the bundle.

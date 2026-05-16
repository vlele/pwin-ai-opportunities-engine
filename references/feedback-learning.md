# Feedback learning playbook

The learning loop should be simple for the user and explainable for reviewers.

## User-facing rule

A user should be able to react to any report entry in plain language.

Examples:
- `like A1`
- `dislike W2 because too small`
- `more like A1`
- `hide N1`
- `wrong buyer for A3`
- `right work, wrong vehicle for W1`
- `never show grants`
- `prefer subcontracts`

## Entry IDs

Each digest item should carry a short ID:
- `A#` for Action Now
- `W#` for Worth a Look
- `N#` for Near Miss
- `S#` for Suppressed note when shown

The learning system should resolve those IDs against the most recent digest unless the user specifies a report date.

## Preferred reason codes

Normalize free-text feedback into reason codes when possible:
- `right_buyer`
- `wrong_buyer`
- `right_work`
- `wrong_work`
- `too_small`
- `too_large`
- `wrong_location`
- `wrong_vehicle`
- `wrong_timing`
- `teaming_only`
- `subcontract_only`
- `bad_eligibility`
- `unclear_evidence`

## Enterprise-safe reinforcement-learning-style adaptation

Do not claim black-box retraining.

Use an explicit reward ledger:
- pursue / perfect fit: `+2`
- like / more like this: `+1`
- watch / neutral: `0`
- dislike / less like this: `-1`
- hard exclude / never: `-3` and create a hard filter when appropriate

Apply rewards only to dimensions that actually contributed to the recommendation:
- capability keywords
- buyers
- NAICS or other taxonomy tags
- opportunity class
- location preferences
- contract-size bands
- teaming / vehicle signals

## Promotion and decay

- first signal: tentative
- second similar signal: medium preference
- third similar signal: strong preference
- explicit `never` or `always` language: immediate hard rule
- stale weak signals should decay over time so the system can adapt

## Guardrails

- low-confidence opportunities should not get promoted into the top bucket from one positive signal alone
- repeated negative reasons from the same source should trigger source-quality review
- high-confidence false positives should trigger a visible drift note in the next report
- every material preference change should appear in both `feedback-events.jsonl` and `MEMORY.md`

## Report footer

Each delivered digest should end with a short footer like:

- `Reply with: like A1 | dislike W2 because too small | more like A1 | hide N1`

That keeps the learning loop frictionless.

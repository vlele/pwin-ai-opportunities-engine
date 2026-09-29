# Semantic Classification Acceptance

This is an understanding checkpoint benchmark, not a final capture score benchmark.
A finite test cannot prove correctness for all solicitations. It can establish
bounded, reproducible evidence and expose a failed release candidate.

## Frozen Protocol

- Eight known regressions, three runs each, for the explicitly selected model and
  effort. The current cost-controlled campaign uses mini/low; high-effort or
  flagship comparisons require a separate run, not an implicit escalation.
- Twelve sealed synthetic controls, three runs each, for a candidate that meets the
  known-case gate. Six pairs change vendor evidence or official precedence while
  holding the key requirement constant. No real company profiles are used.
- Corpus, expectations, source hashes, runtime and prompts freeze before provider calls.
  Expected labels/rubrics are never model input. No prompt changes during a campaign.
- One bounded contract correction per stage; no rerunning failed samples until success.
- Technical blocks fail usability; they do not count as correct rejection of ambiguity.
- Grade three independent dimensions, targeted question routing, actual fact retention
  and consistency. READY is not a semantic grade; no target pursuit totals are used.
- Manual review checks meaning, entailment, false experience credit, question usefulness,
  hallucinated conditions and preserved pricing/timing. Automated label checks alone
  cannot produce a release PASS.

## Acceptance Gate

Require zero critical semantic failures: unsupported positive experience credit,
missing data labeled inability, missed material ambiguity/conflict, wrong acronym
meaning, invented partner/eligibility, or lost pricing/precedence facts. Require no
rescue or verification-only blocking questions on clear controls. Every repeated
run must respect those decision invariants; synonymous wording is allowed.

Require at least 95 percent usable completed checkpoints, but any safety/meaning
failure is still a no-go. A candidate passing short controls must also pass saved
long-package replays before a production reliability claim. Do not run expensive
long-package replays when small controls already fail the acceptance gate.

If a sealed control fails, report it without tailoring a rule to that family. Any
later repair needs a new unseen holdout; this corpus becomes regression data.
Do not silently weaken the scorecard to label a preferred model successful.

## Exact-Claim Extension (Current Version 3)

Version 3 grades supplied performed-work, work-reference and capability records,
not question rows or unrelated identity/date/preference records. Separate absent
coverage remains unknown rather than inheriting the known-work label. Every
supplied work record still needs the correct classification; secondary records
still require evidence audit and semantic review. Historical grades are retained.

The production auditor control entry point is `run_semantic_plan_audit.py`: nineteen
synthetic plans, three repeats, including false assertions, legitimate questions,
partial matches, ongoing work, future proposals, mixed pricing and source injection.
Require no false acceptances/rejections or technical failures. The older
`run_claim_evidence_benchmark.py` exercises retained legacy facet helpers, not the
current production semantic-plan path. Neither control set proves generalization.

The number of production calls is variable: extraction, semantic inventory,
code-enumerated comparison batches and homogeneous audit batches. All supplied
original spans reach the inventory and auditor, including uncited context. This is
not independent document authentication. Negative verdicts are not resampled into
approval. Supported questions may be returned while every fit judgment is withheld;
that is a non-READY state, not a passed semantic release check.

## Reproduction

Both benchmark entry points default to low reasoning effort for cost-controlled
testing. Pass `--effort low` explicitly in saved commands; use medium/high only
for a separately budgeted comparison. This does not change the production checkpoint's
high-effort default. Results at different efforts are distinct configurations, not
interchangeable evidence of production accuracy.

Use `scripts/tests/run_semantic_classification_benchmark.py prepare --folder /new/audit`
to freeze the corpus/runtime. Use `run` with an explicit `--model`, `--effort low`,
`--split known` or `sealed`, and a fresh `--label`. Each label saves raw provider
requests/responses, packet hashes, independent workspaces, grades and review data.
The high effort default applies to the understanding checkpoint only, not every
scan/capture model call. An environment override remains explicit and audited.

Run `scripts/tests/run_release_offline.py --output /new/offline-results` for the
credential-free fixture suites. `scripts/tests/evaluate_release_readiness.py`
requires both corpus splits, auditor controls, matching code/model settings and
documented semantic/integration/repository review. A failing benchmark or release
gate exits nonzero. The gate never stages, commits or pushes.

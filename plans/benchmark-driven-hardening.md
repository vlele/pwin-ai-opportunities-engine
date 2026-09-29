# Benchmark-Driven Hardening Plan

## Summary

Stop optimizing the latest bad memo one defect at a time.

The next phase should treat `scan`, `local capture`, and `stable-ID capture`
as a benchmarked system with frozen corpora, explicit scorecards, release
invariants, and a ranked hardening backlog.

The goal is to make progress measurable and finite:

- better benchmark scores
- fewer invariant violations
- fewer regressions across unrelated packages
- less dependence on memo-by-memo hand tuning

## Why This Plan Exists

The current pattern is real:

- a parser fix improves one package and exposes a ranking problem
- a ranking fix improves one memo and exposes a phrase-compaction problem
- a compaction fix improves one family and creates another literal echo

That means the issue is no longer one isolated bug. It is an architectural
stability problem across three layers:

1. extraction
2. reasoning
3. rendering

The way out is to freeze evaluation inputs and only accept changes that improve
the system across held-out cases.

## Current Failure Pattern

Observed across recent local-capture and regression work:

1. Scope extraction is improving faster than strategy rendering.
   Real section blocks and promoted facts now surface more often, but final win
   themes still over-abstract or echo clause text.

2. Secondary control evidence still competes too successfully with primary
   workstream evidence.
   QA, access, surveillance, reporting, and review language often outrank the
   actual mission workstream.

3. Some win-theme and discriminator rows are still too literal.
   The renderer sometimes converts extracted clause fragments directly into
   strategy language instead of compacting them into capture-manager phrasing.

4. Scan surfacing has historically allowed broad alignment to survive.
   Buyer, NAICS, and keyword overlap have sometimes been enough to surface a
   notice even when the fit narrative did not show clear positive alignment.

5. Public-source research is valuable enrichment but still too thin to serve as
   the backbone of many capture judgments.
   Mission, budget, forecast, and incumbent signals vary sharply by package.

6. Deterministic code still has too much influence in some late-stage strategy
   choices.
   The model is live, but some surviving rows are still shaped more by ranking
   heuristics than by capture judgment.

## Benchmark Plan

### 1. Freeze the Corpora

Create a benchmark corpus with three partitions.

#### A. Local-capture held-out corpus

Target: `20-30` unrelated solicitation families.

Coverage mix:

- civil engineering / facilities
- IT modernization
- logistics / supply chain
- records / workflow
- healthcare / admin
- services with CLIN tables
- packages with heavy amendments and Q&A
- packages with poor PDF structure
- packages with thin public signals

Purpose:

- evaluate extraction, reasoning, and rendering on real package variability
- keep the benchmark independent of the packages used to inspire recent fixes

#### B. Stable-ID scan corpus

Target: `100+` notices across:

- Action Now
- Worth a Look
- Watchlist
- Suppressed

Each record should have:

- vendor profile used
- expected bucket
- expected posture
- expected positive-fit rationale
- expected suppression reason when relevant

Purpose:

- prevent scan surfacing from drifting back toward broad keyword optimism

#### C. Negative-control corpus

Target: `15-20` cases intentionally designed to provoke old failure modes.

Examples:

- generic support notice with low-signal `support`
- policy-only or admin-only package
- package with visible QA clauses but weak scope detail
- package where government-property or access clauses should not become main
  win themes
- packages where prior code invented hot buttons

Purpose:

- make sure the memo gets shorter and more explicit when evidence is weak

### 2. Store Benchmark Fixtures Explicitly

Recommended layout:

```text
scripts/tests/fixtures/benchmark/
|- scan/
|  |- vendor-a.json
|  `- ...
|- local-capture/
|  |- family-001/
|  |  |- manifest.json
|  |  |- inputs/
|  |  `- expected.json
|  `- ...
`- negative-controls/
   `- ...
```

Each fixture manifest should include:

- family id
- package type
- mode: `scan` or `local_capture`
- source files or record inputs
- expected minimum signals
- forbidden phrases
- expected bucket or memo posture
- whether public-source anchors are expected

### 3. Separate the Eval Layers

Every benchmark run should score four layers independently.

#### Layer A. Scan surfacing

Question:
Did we surface the right opportunities for the vendor, for the right reasons?

#### Layer B. Extraction

Question:
Did we recover the real scope-bearing evidence blocks and promoted facts?

#### Layer C. Reasoning

Question:
Did the model select the right hot buttons, win themes, and proof asks from
the current package?

#### Layer D. Rendering

Question:
Did the final memo stay compact, honest, and requirement-specific?

### 4. Add an A/B Evaluation Mode

Every major change should support:

- baseline run
- candidate run
- score delta report

This is especially important for:

- parser changes
- row-ranking changes
- reasoning prompt changes
- public-source admission changes

## Scorecard

Use one weighted release score plus layer-level drilldowns.

### Overall Release Score

Suggested weights:

- Scan surfacing quality: `25`
- Extraction quality: `25`
- Capture reasoning quality: `30`
- Rendering honesty and compaction: `20`

Total: `100`

### Scan Surfacing Metrics

- Surfaced precision at `Action Now` and `Worth a Look`
- Suppression accuracy on negative controls
- Explicit-positive-alignment rate
- Semantic reasoning lift rate
- Bucket-regression count

Release bar:

- no surfaced records without explicit positive alignment
- no regression in gold bucket set

### Extraction Metrics

- Scope-bearing section recovery rate
- Table / CLIN / matrix extraction coverage
- Conflict detection rate across RFQ / PWS / amendments / Q&A
- Hard-page detection recall
- Parsed-but-thin warning rate

Release bar:

- at least one primary scope anchor on every anchored local-capture case
- no silent success on parse-poor packages with expected attachments

### Capture Reasoning Metrics

- Scope-first row rate
- Secondary-control overtake rate
- Requirement-specific hot-button relevance
- Requirement-specific win-theme relevance
- Proof-artifact usefulness rate
- Competitor / incumbent usefulness rate

Release bar:

- at least one of the first two hot buttons must be scope-bearing when such
  evidence exists
- at least one of the first two win themes must be scope-bearing when such
  evidence exists

### Rendering Metrics

- Raw-clause echo rate
- Overlong-row rate
- Generic strategy warning rate
- Thin-evidence honesty rate
- Anchor-citation completeness

Release bar:

- zero raw-clause-leading win themes in the benchmark release set
- thin cases must render explicit fallbacks, not generic strategy prose

## Invariants

These should be treated as release blockers, not soft goals.

1. No surfaced scan result without explicit positive alignment.
   Buyer, NAICS, or keyword overlap alone cannot justify surfacing.

2. Every final hot button and win theme must cite current-package evidence.
   No uncited strategy rows in final memo sections.

3. If evidence is thin, the memo must get shorter and more explicit.
   It must not get more specific, more strategic-sounding, or more verbose.

4. No raw clause echo in final strategy rows.
   Final hot buttons, win themes, and differentiators cannot start with or
   mirror solicitation clauses.

5. No package-specific contamination in core reasoning code.
   Core files cannot contain customer-, program-, or test-package-specific
   nouns.

6. Attachments expected but poorly parsed cannot count as complete capture.
   This already aligns with the tightened completion-gate direction.

7. Public-source signals are enrichment, not substitute scope.
   Mission, budget, and forecast anchors cannot compensate for missing
   requirement-bearing package evidence in local capture.

8. Deterministic code may validate and reject.
   It may not silently replace reasoning with generic strategy language.

## Ranked Hardening Backlog

### P0. Build the Benchmark Harness

Impact: Highest

Why first:
Without this, every improvement remains anecdotal.

Patch targets:

- `scripts/tests/`
- `scripts/tests/fixtures/benchmark/`
- `plans/`

Concrete work:

- add benchmark fixture manifests
- add scan benchmark runner
- add local-capture benchmark runner
- add A/B comparison report
- add invariant-failure summary output

Acceptance:

- one command runs the frozen benchmark and prints score deltas plus invariant
  failures

### P0. Make Reasoning the Owner of Strategy Rows

Impact: Highest

Why first:
This is the main architectural escape from endless deterministic patching.

Patch targets:

- `scripts/common/openai_reasoning.py`
- `scripts/common/openai_reasoning_types.py`
- `scripts/capture/capture_decision.py`

Concrete work:

- restrict final hot buttons and win themes to model-owned row candidates
- let deterministic code only:
  - validate anchors
  - rank scope over control
  - dedupe
  - reject literal or weak rows
- never let deterministic code inject generic strategy filler when model output
  is absent

Acceptance:

- anchored cases still produce strong rows
- thin cases fall back explicitly
- no deterministic generic replacement paths remain in final strategy sections

### P0. Clause-Echo and Phrase-Compaction Repair

Impact: Highest

Why first:
Even with better ranking, literal clause echoes destroy user trust.

Patch targets:

- `scripts/capture/capture_decision.py`
- `scripts/capture/run_capture_research.py`

Concrete work:

- compact clause fragments before rendering
- reject rows whose focus is still an instruction fragment
- add a row-level `strategy_language_quality` check
- add forbidden leading-pattern tests for final strategy lines

Acceptance:

- zero raw-clause-leading win themes in the benchmark release set

### P1. Scope-Bearing Fact Promotion

Impact: High

Why:
The renderer needs better primitive facts than long clause fragments.

Patch targets:

- `scripts/capture/fetch_notice_attachments.py`
- `scripts/capture/run_capture_research.py`
- `scripts/capture/capture_decision.py`

Concrete work:

- promote workstream facts, deliverable facts, staffing facts, transition facts,
  evaluation facts, and conflict facts into short normalized rows
- ensure section-C / PWS scope facts are first-class inputs to reasoning

Acceptance:

- reasoning rows can cite compact promoted facts instead of clause-length anchors

### P1. Hard-Page OCR / Vision Path

Impact: High

Why:
Tables, CLINs, matrices, and image-heavy pages remain real blockers.

Patch targets:

- `scripts/capture/fetch_notice_attachments.py`
- `scripts/capture/run_capture_research.py`

Concrete work:

- detect hard pages heuristically
- OCR / vision only on those pages
- extract section blocks and table rows from those pages
- merge OCR rows with the standard attachment model

Acceptance:

- improved CLIN / matrix / acceptance-table recovery without full-document OCR

### P1. Scan Surfacing Calibration

Impact: High

Why:
The system should not hand weak fits to capture in the first place.

Patch targets:

- `scripts/scan/run_scan.py`
- `scripts/common/openai_reasoning.py`

Concrete work:

- keep explicit-positive-alignment gating
- add benchmark checks for false-positive surfacing
- make semantic audit reporting first-class in scan outputs

Acceptance:

- negative-control notices stay suppressed
- lifted notices show real semantic rationale, not just score nudges

### P1. Public-Source and Competitor Cleanup

Impact: Medium

Why:
These signals matter, but they should enrich, not overpower, package evidence.

Patch targets:

- `scripts/capture/fetch_public_context.py`
- `scripts/capture/usaspending_enrich.py`
- `scripts/common/evidence_model.py`

Concrete work:

- keep strict requirement-bearing public-source admission
- broaden competitor inference with evidence scoring
- separate incumbent proof from adjacent-competitor hints
- score mission, budget, forecast, and award anchors independently

Acceptance:

- richer evidence when available
- no generic public-context filler when not available

### P2. Stable-ID / Local-Capture Parity

Impact: Medium

Why:
Local capture is currently stronger than stable-ID capture on many packages.

Patch targets:

- `scripts/capture/run_capture_research.py`
- `scripts/capture/fetch_notice_attachments.py`
- `scripts/intel/`

Concrete work:

- reduce gap between downloaded-package capture and stable-ID capture
- improve attachment retrieval normalization
- preserve provenance so users know which mode produced which evidence quality

Acceptance:

- stable-ID mode degrades gracefully and honestly when package evidence is thin

## Recommended Working Model

Use this operating sequence for future work:

1. Add or update a benchmark fixture
2. Run baseline benchmark
3. Apply one narrow architectural change
4. Run A/B benchmark
5. Accept only if:
   - release score improves or stays neutral
   - no invariant breaks
   - held-out transfer remains intact

This is the key behavior change:

- no more memo-by-memo tuning as the primary workflow
- benchmark-first, patch-second, release-third

## Initial Acceptance Suite

Use this as the first release gate for the benchmark phase:

```bash
python3 -m py_compile scripts/scan/run_scan.py scripts/capture/capture_decision.py scripts/common/openai_reasoning.py
python3 scripts/tests/run_gold_bucket_tests.py
python3 scripts/tests/run_openai_reasoning_tests.py
python3 scripts/tests/run_capture_reasoning_primary_tests.py
python3 scripts/tests/run_capture_guardrail_tests.py
```

Then add one benchmark command once the harness exists.

## Exit Criteria For This Phase

This phase is complete when:

- the frozen benchmark corpus exists
- the scorecard is implemented
- invariant failures are machine-detected
- at least the P0 backlog is complete
- a new patch can be judged by benchmark deltas instead of by one memo

At that point the project stops being an endless loop and becomes a controlled
hardening program.

# v28 Architecture and Semantic Patch

This candidate addresses standalone-criterion routing, bounded transport retries,
missing proof versus ambiguity, isolated affirmative claims, and missing-history
questions. It is not a declaration of live semantic stability or main-branch readiness.

## Exact Routing Code

In `scripts/common/semantic_plan.py`:

```python
def comparison_pairs(inventory):
    from common.semantic_contract import is_comparable_requirement
    return [{"id": f"C{i}.R{j}", "claim": i, "requirement": j, "claimed": c, "required": r}
            for i, c in enumerate(inventory["claims"])
            for j, r in enumerate(inventory["requirements"])
            if is_comparable_requirement(r) and _comparable(c, r)]


def _comparable(claim, requirement):
    from common.semantic_contract import is_standalone_criterion
    return claim["form"] in WORK_FORMS or (claim.get("assertion_basis") == "work_denial" and claim["attribution"] == "self") or (claim["form"] == "qualification"
           and (is_standalone_criterion(requirement) or any(x["kind"] == "qualification" for x in requirement.get("components", []))))
```

The shared eligibility helpers in `scripts/common/semantic_contract.py` are also
used by full-matrix validation, so a routed criterion cannot be silently omitted:

```python
def is_standalone_criterion(requirement):
    parts = requirement.get("components", [])
    return (bool(parts) and not has_work(requirement)
            and requirement.get("record_kind", "requirement") == "requirement"
            and (any(p["kind"] == "qualification" for p in parts)
                 or (requirement.get("area") in {"evaluation", "eligibility"}
                     and any(p["kind"] != "pricing" for p in parts))))


def is_comparable_requirement(requirement):
    return requirement["status"] == "current" and (
        "components" not in requirement or has_work(requirement)
        or is_standalone_criterion(requirement))


def _criterion_claim_can_support(claim):
    return claim["attribution"] == "self" and (
        (claim["form"] == "performed_task" and claim.get("execution") == "affirmative_actual")
        or (claim["form"] == "qualification" and claim.get("execution") == "not_execution"))
```

Necessary companion changes, not a new extraction architecture:

- `component_jobs()` marks an immutable job as `standalone_criterion` or `operational_work`.
- `comparison_schema()` and `component_response_schema()` allow a criterion typed context to be assessed instead of forcing `not_applicable`.
- `validate_component_response()` preserves that code-owned mode when validating an isolated component; it must not infer a different role from a single component of a work requirement.
- `aggregate_components()` keeps criterion findings and `fit_label` visible, but returns operational `relationship=not_applicable`, `coverage=not_applicable`, and empty `matched_work` for standalone criteria. Qualification/experience credit is not operational-task proof.
- Ordinary metadata, superseded/draft terms, precedence rules, and pricing-only records are not newly routed. No company, acronym, solicitation number, or package-specific phrase selects the route.
- Claim-local citation checks, positive-credit restrictions, source-fidelity audits, and independent clarification routing remain enforced.

The original S02 coarse relevance scorecard may still need an explicit distinction
between operational relevance and accepted-experience satisfaction. This patch does
not force operational relevance to direct or change old scorecards to make them pass.

## Exact Transport Retry Code

In `scripts/common/openai_reasoning.py`, the optional SDK import supplies
`APIConnectionError` and `APITimeoutError` as `TRANSPORT_ERRORS`.
`TRANSPORT_MAX_RETRIES = 3`; `logger = logging.getLogger(__name__)`.

```python
def _create_with_transport_retries(create, **request):
    """Retry only transport failures, never semantic, schema or quota failures."""
    for attempt in range(TRANSPORT_MAX_RETRIES + 1):
        try:
            return create(**request)
        except TRANSPORT_ERRORS as error:
            if attempt == TRANSPORT_MAX_RETRIES:
                logger.warning("OpenAI transport exhausted after %d attempts: %s",
                               attempt + 1, type(error).__name__)
                raise
            delay = 2 ** attempt + random.uniform(0, 0.25)
            logger.warning("OpenAI transport retry %d/%d in %.2fs: %s",
                           attempt + 1, TRANSPORT_MAX_RETRIES, delay, type(error).__name__)
            time.sleep(delay)
```

The call site in `_call_openai_json()` is:

```python
# One transport retry owner; no multiplicative SDK or semantic retries.
create = client.with_options(timeout=effective_timeout, max_retries=0).chat.completions.create
completion = _create_with_transport_retries(create,
    model=model or DEFAULT_REASONING_MODEL,
    **({"reasoning_effort": reasoning_effort} if reasoning_effort is not None else {}),
    response_format={"type": "json_schema", "json_schema": response_schema} if response_schema is not None else {"type": "json_object"},
    messages=[
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": message},
    ],
)
```

This means at most four attempts: the initial request plus three retries, separated
by 1, 2, and 4 seconds plus up to 0.25 seconds of jitter. The exact model, payload,
reasoning effort, and response schema are reused. No retries for authentication,
quota/rate-limit responses, invalid JSON, invalid structured output, or a semantic
audit rejection. The existing bounded contract-correction step remains separate.

After exhaustion, the wrapper raises the original error. The existing JSON-call
boundary fails closed with `None`, and the understanding stage records a technical
block rather than proceeding with invented output. Logs contain error class and
attempt/delay only, not credentials or provider error bodies. The replay client
continues to save every transport attempt, including recovered errors. Future replay
reports must distinguish recovered attempts from terminal provider interruptions.

Retries can increase latency and token charges if a timed-out request reached the
provider. This is bounded recovery, not a guarantee of zero network failures or
exactly-once generation. The error-class distinction follows
[OpenAI's error guidance](https://developers.openai.com/api/docs/guides/error-codes).

## Exact Prompt Additions

These blocks are in the shared runtime policies, not just Markdown. Applicable
comparison/audit prompts inherit them through `apply_policies()`. Package-only
source-fidelity and Decomposer stages remain isolated from vendor-fit decisions.

### Missing Vendor Proof

```text
Distinguish between 'Ambiguous Requirements' and 'Missing Vendor Proof'. If a vendor
provides a vague capability or prospective statement (e.g., 'we will plan a schedule'),
this means the required performed-work condition is missing or unproven. Do NOT label
a condition as ambiguous simply because the vendor failed to provide specific proof.
Reserve ambiguous ONLY for when the provided text explicitly creates multiple
conflicting interpretations of performed work. This rule governs vendor component
findings, not the independent official-conflict channel: preserve contradictory
package terms and their formal Q&A even when vendor proof is merely missing.
```

### Independent Affirmative Claim

```text
You MUST respect the Comparator's right to label an affirmative claim as unrelated
independently. If a vendor supplies an unrelated affirmative claim (e.g., photography),
do NOT demand it be marked contradicted just because a sibling negative statement
(e.g., denying lab work) exists in the same graph. An unrelated claim is unrelated;
do not force contradiction across isolated claims.
```

### Absent History

```text
If the text explicitly states that references, project descriptions, or histories
'have not been supplied', 'are missing', or 'are omitted', you
MUST NOT generate clarification questions asking what those missing references describe.
Acknowledge the data gap as a missing condition and output NO question about that gap.
```

The existing exception is preserved: an actual supplied reference with unclear duties
or performer still warrants clarification. An absent-history statement does not erase
a different, existing ambiguous reference or an official package conflict.

### Standalone Criterion Interpretation

```text
STANDALONE CRITERIA ARE ASSESSABLE, NOT CORE WORK:
A current requirement in the evaluation/eligibility area, or a standalone
qualification requirement, may be compared without a work component. For a job
marked comparison_kind=standalone_criterion, assess the exact criterion against the
isolated claim. A criterion typed context is assessable in this mode; it is not
automatically not_applicable. Preserve its component type and exact source text.
Credit only the criterion actually established by this claim's own evidence. A
performed-work experience criterion requires affirmative self-reported work;
qualification credit requires the corresponding qualification assertion. Missing
proof remains missing; ambiguous existing work remains ambiguous. A general offer,
unknown performer, acronym overlap or sibling claim cannot establish this criterion.
Government credit-assignment rules are not contractor tasks. Explain whether the
supplied evidence satisfies the stated rule without inventing a duty to perform it.
The code-owned criterion fit_label/met_components describe criterion satisfaction.
Its operational relationship and coverage remain not_applicable and matched_work
stays empty. This does NOT mean the criterion was skipped or its evidence is absent.
Never transfer a matched experience criterion into proof of another operational task.
Ordinary metadata, precedence rules and pricing terms remain non-experience context.
Auditors check criterion entailment and source fidelity separately from operational
performance; still reject unsupported criterion credit or borrowed evidence.
```

## Prompt Inspection and Tests

`EXTRACTOR-PROMPT.md`, `COMPARATOR-PROMPT.md`, `AUDITOR-PROMPT.md`, and
`QUESTION-ROUTER-PROMPT.md` are generated exact exports of the runtime strings.
Run `python3 scripts/tests/export_semantic_prompts.py --check` to detect drift.

The new `scripts/tests/test_v28_contracts.py` covers routing of context/condition/
qualification criteria, negative routing controls, isolated schema/validator parity,
criterion credit without operational credit, missing matrix entries, immutable
evidence, unknown performers, transport recovery/exhaustion, non-retryable failures,
and prompt/export wiring. These are deterministic tests, not live semantic verdicts.

No v27 trial was overwritten or regraded. Live v28 semantic stability must be tested
separately before any main-branch release decision.

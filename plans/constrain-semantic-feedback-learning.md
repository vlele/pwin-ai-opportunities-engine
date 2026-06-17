# Constrain Semantic Feedback Learning Plan

## Summary

Fix issue #25 by separating semantic context detected on an opportunity from the semantic traits the user actually accepted or rejected in feedback.

For the DemoGov feedback:

```text
dislike E6 because reseller hardware and equipment buys are not a target fit
```

the system should learn a specific caution for reseller hardware/equipment buys without penalizing data management, set-aside posture, no-set-aside text, or prime-possible posture.

## Implementation Notes

- Add deterministic detection for explicit non-fit work patterns in `scripts/common/openai_reasoning.py`, including reseller hardware/equipment buy language mapped to `reseller_hardware_equipment_buy`.
- Constrain feedback interpretation after heuristic/model coercion so explicit free-text reasons become the learning target and broad unrelated inferred rejects are removed.
- Keep `resolved_entities` as opportunity context only.
- Use `feedback_interpretation.accepted_*` and `feedback_interpretation.rejected_*` as the only semantic dimensions eligible for learned preference scoring.
- Update semantic aggregation so broad context such as mission domain, contract posture, set-aside signals, vehicle signals, and teaming posture is not scored unless it is explicitly accepted or rejected.
- Preserve the existing CLI and stored preference schema. The only new persisted value is the semantic facet string under existing aggregate/preference arrays.
- Document the context-vs-target distinction in `references/feedback-learning.md`.

## Test Commands

```bash
python3 scripts/tests/run_openai_reasoning_tests.py
python3 scripts/tests/run_bootstrap_tests.py
python3 scripts/tests/run_gold_bucket_tests.py
python3 scripts/tests/run_intel_provider_tests.py
python3 scripts/tests/run_commercial_intel_tests.py
python3 scripts/tests/run_scan_bootstrap_guidance_tests.py
python3 scripts/tests/run_source_policy_tests.py
python3 -m py_compile scripts/common/openai_reasoning.py scripts/tests/run_openai_reasoning_tests.py
git diff --check
```

## Acceptance Criteria

- The DemoGov regression learns `reseller_hardware_equipment_buy` as the rejected semantic facet.
- The same feedback does not create negative learning signals for `data_management`, `set_aside_restricted`, `no set aside used`, or `prime_possible`.
- Explicit mission-domain feedback such as `data management is not a target fit` still creates an avoided mission-domain preference.
- Recomputing existing feedback ledgers applies the same target constraint, so old over-broad events do not keep polluting semantic aggregates.

## References

- Issue: https://github.com/vlele/pwin-ai-opportunities-engine/issues/25
- Pull request: https://github.com/vlele/pwin-ai-opportunities-engine/pull/29

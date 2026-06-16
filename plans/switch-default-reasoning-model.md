# Switch Default Reasoning Model Plan

## Summary

Update the skill's built-in mini reasoning model from `gpt-5-mini` to `gpt-5.4-mini`, matching issue #12 and OpenAI's June 11, 2026 GPT-5 mini deprecation guidance.

Preserve the current override order:

- `PWIN_REASONING_MODEL`
- `OPENAI_MODEL`
- built-in default

## Implementation Notes

- Change `scripts/common/openai_reasoning.py` so `DEFAULT_REASONING_MODEL` falls back to `gpt-5.4-mini`.
- Add `scripts/tests/run_openai_reasoning_tests.py` to re-import `common.openai_reasoning` under controlled environment values and verify:
  - no `PWIN_REASONING_MODEL` or `OPENAI_MODEL` defaults to `gpt-5.4-mini`
  - `OPENAI_MODEL` overrides the built-in default
  - `PWIN_REASONING_MODEL` overrides `OPENAI_MODEL`
- Update `docs/quickstart-one-pager.md` to recommend `OPENAI_MODEL="gpt-5.4-mini"` and describe that default.
- Regenerate tracked quickstart artifacts from the Markdown source:
  - `docs/quickstart-one-pager-styled.html`
  - `docs/quickstart-one-pager-styled.pdf`

## Test Commands

```bash
python3 scripts/tests/run_openai_reasoning_tests.py
python3 scripts/tests/run_source_policy_tests.py
python3 scripts/tests/run_commercial_intel_tests.py
python3 scripts/tests/run_scan_bootstrap_guidance_tests.py
git diff --check
rg -n "gpt-5-mini|gpt-5\\.4-mini"
pdftotext docs/quickstart-one-pager-styled.pdf /tmp/pwin-quickstart-pdf.txt
pdftoppm -png docs/quickstart-one-pager-styled.pdf /tmp/pwin-pdf-render/quickstart
```

Any remaining `gpt-5-mini` mention should be historical/deprecation context only.

## Assumptions

- Do not change environment variable names, OpenAI API key behavior, timeout behavior, or call sites.
- Use the recommended alias `gpt-5.4-mini`, not a dated model snapshot.
- Treat tracked HTML and PDF quickstart files as release artifacts that should stay in sync with the Markdown quickstart.
- Avoid live OpenAI API calls in tests; import-time environment fallback coverage is sufficient.

## References

- Issue: https://github.com/vlele/pwin-ai-opportunities-engine/issues/12
- OpenAI deprecations: https://developers.openai.com/api/docs/deprecations#2026-06-11-gpt-5-and-o3-model-deprecations

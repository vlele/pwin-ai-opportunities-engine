# Hide Invalid Feedback Examples for Empty Digests

## Summary

Fix issue #24 by making rendered digest and report feedback guidance data-aware.
When no stable entry IDs are generated, the output should explain that there are
no entries to act on and point the user to source issues or a retry after source
recovery. When entries exist, examples should use actual generated stable IDs,
not hardcoded sample IDs.

## Implementation Notes

- Replace the static feedback examples in `templates/daily-digest.template.md`
  and `templates/daily-report.template.md` with a renderer-filled placeholder.
- Add renderer logic in `scripts/scan/render_digest.py` that:
  - renders entry-specific examples only when the digest entry map contains
    stable IDs;
  - uses IDs from the current run, such as `E1`, instead of hardcoded `A1`,
    `W2`, or `E1` examples;
  - renders a no-entry message when `len(entries) == 0`, including source issue
    and retry guidance.
- Preserve existing generated artifact paths, digest-entry-map schema, and scan
  JSON output fields.
- Leave general documentation examples unchanged because they teach valid
  feedback syntax outside a specific empty digest.

## Test Commands

```bash
python3 scripts/tests/run_render_digest_tests.py
python3 scripts/tests/run_scan_bootstrap_guidance_tests.py
python3 -m compileall scripts
git diff --check
```

## Acceptance Criteria

- Empty digests and reports do not include entry-ID-specific examples such as
  `like A1`, `dislike W2 because too small`, `research A1`, or
  `capture deep dive on A1`.
- Empty digests and reports include a clear no-stable-entries message with
  source issue and retry guidance.
- Non-empty digests and reports continue to show useful feedback examples, but
  only with stable IDs that exist in the rendered artifact.
- Rendered digest and report markdown contain no unresolved template
  placeholders.

## References

- Issue: https://github.com/vlele/pwin-ai-opportunities-engine/issues/24
- PR: https://github.com/vlele/pwin-ai-opportunities-engine/pull/28

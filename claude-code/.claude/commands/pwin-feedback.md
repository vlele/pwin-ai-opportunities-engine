Apply user feedback to the pWin.ai preference state through the shared script bundle.

Inputs:
- workspace path
- raw feedback text

Steps:
1. Resolve `PWIN_AI_OPPS_ROOT`.
2. Run:
   `python3 "$PWIN_AI_OPPS_ROOT/scripts/feedback/apply_feedback.py" --workspace "<workspace>" --text "<feedback text>"`
3. Inspect the JSON stdout.
4. Report what was logged and whether the impact is immediate, next-run, or both.

Rules:
- Preserve the user's wording.
- Do not claim model retraining.

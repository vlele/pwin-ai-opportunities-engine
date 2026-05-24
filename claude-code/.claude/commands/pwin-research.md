Run decision-grade capture research for a stable ID or canonical opportunity ID.

Inputs:
- workspace path
- entry such as `A1`, `W2`, or a canonical ID

Steps:
1. Resolve `PWIN_AI_OPPS_ROOT`.
2. Run:
   `python3 "$PWIN_AI_OPPS_ROOT/scripts/capture/run_capture_research.py" --workspace "<workspace>" --entry "<entry>" --depth full_360`
3. Inspect the JSON stdout.
4. Read the returned `brief_path` and `evidence_path`.
5. Answer from the fresh brief.

Rules:
- Include the stable ID when available, canonical ID, current status, brief path, evidence path, and concise next actions.
- If status is `PARTIAL_CAPTURE_RESEARCH`, say that plainly.
- If the script fails, do not improvise a successful memo.

Show the latest or a dated pWin.ai digest from the shared script bundle.

Inputs:
- workspace path
- date value, default `latest`

Steps:
1. Resolve `PWIN_AI_OPPS_ROOT`.
2. Run:
   `python3 "$PWIN_AI_OPPS_ROOT/scripts/show/show_digest.py" --workspace "<workspace>" --date "<date>"`
3. Inspect the JSON stdout.
4. Read the returned `digest_path`.
5. Summarize only what is in that digest.

Rules:
- If the digest has no stable IDs, say so clearly.
- Recommend rerunning scan only when the digest itself indicates the need.

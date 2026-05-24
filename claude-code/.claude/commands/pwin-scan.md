Run a fresh pWin.ai federal opportunity scan from the shared script bundle.

Inputs:
- workspace path
- horizon, default `30-45`

Steps:
1. Resolve `PWIN_AI_OPPS_ROOT`. Prefer the environment variable. If it is unset, locate the repo root that contains `SKILL.md` and `scripts/scan/run_scan.py`. If that still fails, ask the user for the repo root.
2. Run:
   `python3 "$PWIN_AI_OPPS_ROOT/scripts/scan/run_scan.py" --workspace "<workspace>" --horizon "<horizon>" --federal-only`
3. Inspect the JSON stdout.
4. Read the returned `digest_path`.
5. Answer from the digest only.

Rules:
- Do not invent a second digest in chat.
- Report the digest date and stable IDs when present.
- If the script fails, report the failure plainly.

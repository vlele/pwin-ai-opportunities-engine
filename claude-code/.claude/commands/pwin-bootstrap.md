Bootstrap a pWin.ai workspace from a company website.

Inputs:
- workspace path
- company URL
- optional NAICS list
- optional NAICS certainty: `confirmed` or `candidate`

Steps:
1. Resolve `PWIN_AI_OPPS_ROOT`.
2. Run:
   `python3 "$PWIN_AI_OPPS_ROOT/scripts/bootstrap/bootstrap_workspace.py" --workspace "<workspace>" --company-url "<company url>"`
3. If NAICS were provided, add:
   `--naics "<comma-separated codes>"`
4. If the NAICS are tentative, also add:
   `--naics-status candidate`
5. Inspect the JSON stdout.
6. Read the returned `starter_profile_path`.
7. Summarize the inferred profile, the files created, and the next confirmations needed.

Rules:
- Clearly label website-derived facts as provisional until the user confirms them.
- Do not ask the user to hand-author starter files if the bootstrap script can create them.

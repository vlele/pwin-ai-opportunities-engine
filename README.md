# pWin.ai Opportunities for OpenClaw

If you can clone a repo and run one bootstrap command, you can use this skill.

`pwin-ai-opportunities` turns OpenClaw into a lightweight federal opportunity scanner and capture-research assistant. Install the skill, set one extra API key, point it at a company website, and it will create the starter workspace files for you.

## Why it feels easy

- You talk to it in normal English.
- The first-run bootstrap creates the starter files for you.
- Every run writes real files into your workspace, so nothing is trapped in chat.
- The workflow is simple: bootstrap, scan, research, and give feedback.

## 3-minute setup

1. Clone the repo into the OpenClaw skills folder:

```bash
git clone git@github.com:vlele/pwin-ai-opportunities-engine.git "$HOME/.openclaw/skills/pwin-ai-opportunities"
export PWIN_AI_OPPS_ROOT="$HOME/.openclaw/skills/pwin-ai-opportunities"
```

2. Export the only skill-specific secret:

```bash
export SAM_API_KEY="your-sam-gov-key"
```

3. Keep your normal OpenClaw model credential in place.

If OpenClaw already works on your machine, you usually do not need any new LLM setup for this skill.

4. Open any workspace folder.

The skill writes everything under `procurement/` inside that workspace.

## Easiest first use

Bootstrap the workspace from the company site:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/bootstrap/bootstrap_workspace.py" \
  --workspace "$PWD" \
  --company-url "https://example.com"
```

If you already know NAICS, add them too:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/bootstrap/bootstrap_workspace.py" \
  --workspace "$PWD" \
  --company-url "https://example.com" \
  --naics "541511,541512"
```

That creates:

- `procurement/vendor-profile.json`
- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/STARTER_PROFILE.md`
- `MEMORY.md`

Then run your first scan:

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/scan/run_scan.py" --workspace "$PWD" --horizon "30-45" --federal-only
```

## What you get back

- A dated digest with stable IDs like `A1`, `W2`, and `E1`
- A full report for the same scan
- Fresh capture briefs for opportunities you want to pursue
- Evidence files that show what the research run used
- Feedback logging so future shortlists improve

## Copy-paste commands

```bash
python3 "$PWIN_AI_OPPS_ROOT/scripts/show/show_digest.py" --workspace "$PWD" --date latest
python3 "$PWIN_AI_OPPS_ROOT/scripts/capture/run_capture_research.py" --workspace "$PWD" --entry "A1" --depth full_360
python3 "$PWIN_AI_OPPS_ROOT/scripts/feedback/apply_feedback.py" --workspace "$PWD" --text "like A1"
```

## Good to know

- The current shipped scope is federal-only.
- The only extra key this skill needs is `SAM_API_KEY`.
- Website-derived bootstrap fields are provisional until you confirm them.
- Detailed setup notes live in `docs/install-openclaw.md`.
- The broader walkthrough lives in `docs/quickstart-one-pager.md`.

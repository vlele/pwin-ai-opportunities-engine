# pWin.ai Opportunities for OpenClaw

If you can clone a repo and paste one OpenClaw prompt, you can use this skill.

`pwin-ai-opportunities` turns OpenClaw into a lightweight federal opportunity scanner and capture-research assistant. Install the skill, configure either SAM.gov or GovTribe access, point it at a company website, and OpenClaw will create and pre-populate the starter workspace files for you.

## Why it feels easy

- You talk to it in normal English.
- The first-run bootstrap creates and pre-populates the starter files for you.
- Every run writes real files into your workspace, so nothing is trapped in chat.
- The workflow is simple: bootstrap, scan, research, and give feedback.

## 3-minute setup

1. Clone the repo into the OpenClaw skills folder:

```bash
git clone git@github.com:vlele/pwin-ai-opportunities-engine.git "$HOME/.openclaw/skills/pwin-ai-opportunities"
export PWIN_AI_OPPS_ROOT="$HOME/.openclaw/skills/pwin-ai-opportunities"
```

2. Export at least one opportunity-retrieval credential.

For the official SAM.gov path:

```bash
export SAM_API_KEY="your-sam-gov-key"
```

For the GovTribe MCP path:

```bash
export GOVTRIBE_MCP_API_KEY="your-govtribe-mcp-key"
```

SAM.gov remains the default official-source retrieval path. When the workspace enables `govtribe_mcp_commercial_intel`, GovTribe MCP can also participate in scan retrieval alongside SAM.gov and downstream enrichment. Set `provider_options.scan_retrieval_enabled` to `false` in `procurement/source-registry.json` only when you want GovTribe enrichment without GovTribe-sourced scan candidates.

3. Keep your normal OpenClaw model credential in place.

If OpenClaw already works on your machine, you usually do not need any new LLM setup for this skill.

4. Open any workspace folder.

The skill writes everything under `procurement/` inside that workspace.

## Easiest first use

Ask OpenClaw:

```text
Use pwin-ai-opportunities and bootstrap this workspace from https://example.com.
```

If you already know NAICS, say:

```text
Use pwin-ai-opportunities and bootstrap this workspace from https://example.com
with confirmed NAICS 541511 and 541512.
```

If you already have a GovTribe vendor profile and `GOVTRIBE_MCP_API_KEY` is configured, you can bootstrap from that record instead:

```text
Use pwin-ai-opportunities and bootstrap this workspace from https://govtribe.com/vendors/demogov-services-demo1.
```

That creates or updates:

- `procurement/vendor-profile.json`
- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/STARTER_PROFILE.md`
- `MEMORY.md`

Bootstrap also pre-populates `procurement/vendor-profile.json` with:

- Bootstrap metadata and a `needs_user_confirmation` status
- `company.website` plus an inferred company name and summary
- Inferred `core_competencies`, `other_taxonomy_tags.keywords`, and a starter `fit_narrative`
- Confirmed `naics.confirmed` values when you provide confirmed codes
- Candidate `naics.candidates` values from tentative input plus website inference
- Candidate buyer notes, provenance facts, and a reminder that website-derived facts are still provisional

GovTribe bootstrap uses GovTribe vendor fields when available, including UEI, NAICS, certifications, contract vehicles, award and buyer signals, and AI summary text. GovTribe subscription-derived facts are labeled separately from website-derived facts and remain provisional until confirmed.

It also seeds `procurement/preferences.json` to exclude `grants` by default, prefer `contracts`, `subcontracts`, and `forecasts`, and reuse the inferred capability keywords. If `vendor-profile.json` already exists, bootstrap merges into it instead of wiping your existing work.

Then ask for your first scan:

```text
Use pwin-ai-opportunities and run a federal opportunity scan for the next 30 to 45 days in this workspace.
```

## What you get back

- A dated digest with stable IDs like `A1`, `W2`, and `E1`
- A full report for the same scan
- Fresh capture briefs for opportunities you want to pursue
- Evidence files that show what the research run used
- Feedback logging so future shortlists improve

## Copy-paste prompts

```text
Use pwin-ai-opportunities and show the latest digest.
Use pwin-ai-opportunities and research A1 with full capture depth.
never show grants
like A1
```

## Good to know

- The current shipped scope is federal-only.
- `SAM_API_KEY` enables official SAM.gov opportunity retrieval.
- `GOVTRIBE_MCP_API_KEY` enables direct GovTribe enrichment and GovTribe-sourced scan retrieval when the workspace enables the GovTribe MCP source.
- Website-derived bootstrap fields are provisional until you confirm them.
- OpenClaw should normally be invoked in chat; the Python scripts are the implementation layer underneath the skill.
- Detailed setup notes live in `docs/install-openclaw.md`.
- The broader walkthrough lives in `docs/quickstart-one-pager.md`.

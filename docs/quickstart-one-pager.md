# pWin.ai Opportunities Quick Start

`pWin.ai Opportunities` helps you scan federal opportunities, turn promising items into capture briefs, and improve future matching with plain-English feedback.

## Minimum requirements

- One working host: `OpenAI Codex`, `OpenClaw`, or `Claude Code`
- `python3` available in your shell
- A workspace folder where the skill can write artifacts
- A `SAM.gov` API key exposed as `SAM_API_KEY`
- Your host's normal LLM credential already configured
- This skill does not introduce a new LLM auth scheme
- If your host uses OpenAI-style env vars, that usually means `OPENAI_API_KEY`
- Internet access

## 1. Install the skill

### OpenAI Codex

Clone the repo into your Codex skills folder:

```bash
git clone https://github.com/vlele/pwin-ai-opportunities-engine.git "$HOME/.codex/skills/pwin-ai-opportunities"
```

If Codex does not pick it up immediately, restart Codex or refresh skill discovery.

### OpenClaw

Clone the repo into your OpenClaw skills folder:

```bash
git clone https://github.com/vlele/pwin-ai-opportunities-engine.git "$HOME/.openclaw/skills/pwin-ai-opportunities"
```

### Claude Code

Claude Code uses this repo as a shared bundle plus a Claude-specific adapter:

```bash
git clone https://github.com/vlele/pwin-ai-opportunities-engine.git "$HOME/src/pwin-ai-opportunities"
export PWIN_AI_OPPS_ROOT="$HOME/src/pwin-ai-opportunities"
mkdir -p "$HOME/.claude/commands/pwin-ai-opportunities"
cp -R "$PWIN_AI_OPPS_ROOT/claude-code/.claude/commands/." "$HOME/.claude/commands/pwin-ai-opportunities/"
```

Then copy or merge `claude-code/CLAUDE.md` into the Claude Code project context you normally use.
After that, Claude Code users can call the command pack with prompts such as `/pwin-scan`, `/pwin-research`, `/pwin-feedback`, and `/pwin-show-digest`.

## 2. Add your keys

In the shell where your host runs, export your keys:

```bash
export SAM_API_KEY="your-sam-gov-key"
export OPENAI_API_KEY="your-llm-key"   # only if your host uses OpenAI-style credentials
```

If your tool already works today, keep using the same LLM credential that tool already expects. The only skill-specific secret is `SAM_API_KEY`.

## 3. Pick a workspace

Create or open a folder for one company or client:

```bash
mkdir -p "$HOME/work/acme-capture"
cd "$HOME/work/acme-capture"
```

This skill writes its outputs into `procurement/` inside that workspace.

## 4. Seed the vendor profile from a company URL

The easiest start is to give the tool the company's website and let it create the starter files. Use a prompt like this:

```text
Use pwin-ai-opportunities. My company website is https://example.com.
Seed procurement/vendor-profile.json, procurement/preferences.json,
procurement/source-registry.json, procurement/STARTER_PROFILE.md, and MEMORY.md.
Infer candidate NAICS from the site, keep website-derived facts provisional until I confirm them,
and ask me only for the most important missing facts.
```

If you already know NAICS codes, add them to the same prompt.

Note: `preferences.json` and `source-registry.json` will be created automatically on the first scan if they do not exist, but results are better if you seed the profile first.

## 5. Run the first scan

Once the workspace is seeded, ask your tool:

```text
Use pwin-ai-opportunities and run a federal opportunity scan for the next 30 to 45 days in this workspace.
```

You should get a dated digest with stable IDs like `A1`, `W2`, or `E1`.

## 6. Run capture research

Pick a stable ID from the digest and ask:

```text
Use pwin-ai-opportunities and research A1 with full capture depth.
```

That produces a fresh capture brief and evidence file under `procurement/capture-briefs/` and `procurement/capture-evidence/`.

## 7. Give feedback so the shortlist improves

After reviewing the digest or a capture brief, give quick natural-language feedback such as:

```text
like A1
dislike W2 because too small
never show grants
more like A1
```

The skill logs that feedback to `procurement/feedback-events.jsonl` and updates learned preferences for the next run.

## What gets created in your workspace

- `procurement/vendor-profile.json`
- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/digests/YYYY-MM-DD.md`
- `procurement/digest-entry-map/YYYY-MM-DD.json`
- `procurement/capture-briefs/...`
- `procurement/capture-evidence/...`
- `procurement/feedback-events.jsonl`

## Short version

1. Install the repo in the folder your host expects.
2. Set `SAM_API_KEY` and keep your normal LLM key in place.
3. Open a workspace folder.
4. Seed the company profile from the website URL.
5. Run a scan.
6. Research a stable ID.
7. Give feedback in plain English.

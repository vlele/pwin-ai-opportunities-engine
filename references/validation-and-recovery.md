# Validation and Recovery

This document describes the artifact validation and auto-recovery system for pWin.ai Opportunities.

## Overview

Daily runs produce five required artifacts. If any are missing, the run is incomplete. The skill can auto-recover certain missing artifacts if their source data exists.

## Required Artifacts

| Artifact | Path | Recoverable | Source Data |
|----------|------|-------------|-------------|
| opportunities | `procurement/opportunities/YYYY-MM-DD.json` | No | Primary source |
| explanations | `procurement/explanations/YYYY-MM-DD.json` | No | Primary source |
| report | `procurement/reports/YYYY-MM-DD.md` | **Yes** | opportunities + explanations |
| digest | `procurement/digests/YYYY-MM-DD.md` | **Yes** | opportunities + explanations + report |
| near-misses | `procurement/near-misses/YYYY-MM-DD.md` | **Yes** | opportunities + explanations |

## Validation Command

After running the daily scan, validate completion:

```
validate-artifacts {date}
```

### Returns

- `complete` — all required artifacts present
- `recovered` — artifacts were missing but successfully rebuilt
- `incomplete: [list]` — artifacts still missing after recovery attempts

## Auto-Recovery Logic

When `autoRecover: true` is set in `manifest.json`:

1. Check for missing required artifacts
2. For each missing recoverable artifact:
   - Verify all `recoverFrom` source artifacts exist
   - Rebuild the missing artifact using templates and source data
   - Write to the expected path
3. Re-validate after recovery
4. Return `recovered` if all artifacts now present, `incomplete` if not

## Recovery Scenarios

### Scenario 1: Report Missing, Sources Present

**Cause:** Agent stopped after writing digest but before report.

**Recovery:**
- Read `opportunities/{date}.json`
- Read `explanations/{date}.json`
- Render `templates/daily-report.template.md`
- Write `reports/{date}.md`

### Scenario 2: Digest Missing, Sources Present

**Cause:** Agent stopped after scoring but before digest.

**Recovery:**
- Read `opportunities/{date}.json`
- Read `explanations/{date}.json`
- Render `templates/daily-digest.template.md`
- Write `digests/{date}.md`

### Scenario 3: Near-Misses Missing, Sources Present

**Cause:** Agent excluded near-miss section or stopped early.

**Recovery:**
- Read `opportunities/{date}.json` (filter for near-miss tier)
- Read `explanations/{date}.json`
- Write `near-misses/{date}.md`

## Non-Recoverable Failures

These require a full re-run:

- `opportunities` missing — source data lost
- `explanations` missing — scoring rationale lost
- Multiple artifacts missing with insufficient source data

## Manual Recovery

If auto-recovery fails, manually rebuild:

1. Check which source files exist
2. Use the appropriate template from `templates/`
3. Render from structured data
4. Write to the expected path
5. Re-run `validate-artifacts {date}`

## Cron Job Integration

Recommended cron prompt pattern:

```
Run the pwin-ai-opportunities daily scan for {vendor}.
After completion, run validate-artifacts {date} with auto-recovery enabled.
If status is 'incomplete', fail the run and report missing artifacts.
If status is 'complete' or 'recovered', proceed to WhatsApp delivery.
```

## Failure Behavior

- **Validation fails, no recovery possible:** Run marked failed, no delivery
- **Validation fails, recovery succeeds:** Run marked success with recovery note
- **Validation passes:** Normal completion

## Version History

- v1.1.0 — Added validation and auto-recovery system

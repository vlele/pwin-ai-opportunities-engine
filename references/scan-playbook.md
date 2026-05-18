# Scan Playbook

Use this playbook only when the `scan` mode is selected.

## Goals

- refresh the runtime source registry
- use federal sources only by default
- produce a digest with stable IDs
- produce a digest-entry map that explicitly links `A1/W1/E1/S1` to canonical identifiers

## High-level flow

1. Refresh `procurement/source-registry.json` from the template when missing or stale.
2. Determine the target horizon.
3. Use the latest structured opportunity snapshot when available.
4. Render the digest from structured records, not from memory.
5. Build `procurement/digest-entry-map/YYYY-MM-DD.json`.
6. Validate that every digest entry ID has a mapping row.

## Minimum output

- `procurement/digests/YYYY-MM-DD.md`
- `procurement/digest-entry-map/YYYY-MM-DD.json`

## If there are no opportunities

Produce a degraded digest with:
- `Run status: DEGRADED`
- an explanation of why there are no entries
- no fake `A1/W1/E1` rows

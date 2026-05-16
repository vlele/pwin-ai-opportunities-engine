# Trust and confidence patterns

A good shortlist is not enough. The user should be able to see **why** something appeared, why it ranked where it did, and how their feedback changed the model.

## 1. Keep fit and confidence separate

Use two scores for every opportunity:

- **Match score**: how well the work appears to fit the vendor
- **Confidence score**: how trustworthy and complete the evidence is

A high-fit / low-confidence item belongs in a quarantine or near-miss bucket, not in the top picks.

## 2. Show an evidence card for each shortlisted opportunity

Every top result should show:
- source name
- source trust tier
- direct URL
- buyer / agency
- due date
- opportunity type
- matched competencies
- matched codes or taxonomy tags
- main caveat
- unresolved assumptions

## 3. Use a source trust ladder

- **Tier 1** - official API, structured record, stable identifier
- **Tier 2** - official public page with stable visible fields
- **Tier 3** - official page requiring browser extraction or brittle parsing
- **Tier 4** - user-added or manually curated source

Lower-tier sources should never outrank higher-tier sources on confidence without a very clear reason.

## 4. Keep a preference drift log

Every time the skill changes a meaningful preference, record:
- what changed
- why it changed
- whether the change is hard or soft
- which feedback event triggered it

This helps with explainability and rollback.

## 5. Use a low-confidence quarantine bucket

Rather than mixing uncertain opportunities with strong opportunities:
- keep top picks clean
- keep uncertain items separate
- explain why they were quarantined

## 6. Maintain a near-miss review habit

Near misses reduce blind spots. They are also the fastest way to learn what the user actually wants.

A near miss should say exactly why it failed:
- wrong size
- wrong agency
- wrong location
- wrong contract type
- weak capability match
- unclear evidence

## 7. Keep a golden set for regression testing

Maintain a small set of labeled historical examples:
- should show
- should suppress
- near miss
- wrong source / low confidence

When onboarding logic or scoring logic changes, compare the new behavior against the golden set before promoting the change.

## 8. Explain suppressions when they matter

If a strong hard rule hides something that would otherwise rank well, mention that in a suppression or rules note. This builds confidence that the system is following the user's stated preferences rather than acting randomly.

## 9. Track source health

If a source is stale, temporarily unavailable, or requires login, say so in the digest. A silent failure looks like a weak market; a visible failure looks like an operational issue.

## 10. Prefer reversible learning

Treat feedback changes as:
- hard rules only when explicitly stated
- soft weights otherwise

That keeps the system adaptable and reduces accidental overfitting.

## 11. Keep a provenance ledger for profile facts

Not all profile facts are equal. Label them clearly:

- **user_confirmed** - the user explicitly confirmed it
- **website_inferred** - inferred from the official company site
- **source_extracted** - taken from an opportunity source or other official record
- **manual_override** - intentionally changed by an admin or reviewer
- **user_supplied_naics** - directly entered by the user as a startup constraint

Website-derived facts should influence ranking, but they should not become hard filters until the user confirms them.

## 12. Add a calibration summary

At least periodically, report:
- how many Action Now items were accepted vs rejected
- which sources create the most false positives
- which preference changes improved precision
- whether any website_inferred facts are still waiting for confirmation

This turns trust from a feeling into a measurable operating signal.

## 13. Make the learning loop visible

Every announced digest should show users how to respond:
- `like A1`
- `dislike W2 because too small`
- `more like A1`
- `hide N1`

The easier it is to react, the faster the shortlist improves.

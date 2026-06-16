# Onboarding playbook

The goal is to let the user start in plain language and only introduce codes after the skill has already done most of the interpretation work.

For this release, onboarding should prepare the workspace for federal opportunity scanning only. Do not steer the user toward state or local procurement portals.

## Stage 0: website, domain, or GovTribe vendor bootstrap

If the user gives a company website or domain, start there.

If the user gives a GovTribe vendor URL, vendor name, UEI, or asks to bootstrap from GovTribe vendor search, use GovTribe first when `GOVTRIBE_MCP_API_KEY` is configured. If GovTribe is unavailable, not configured, or returns no match, fall back to website bootstrap only when the user also provided a company website.

If the user also gives NAICS, use those codes immediately to tighten the first pass:
- treat them as confirmed if the user presents them as authoritative
- treat them as candidate codes if the user sounds unsure

Use the official site first and prioritize pages like:
- About
- Solutions
- Industries
- Contract Vehicles
- Partners
- Case Studies
- Contact

From the official site, extract:
- a plain-English company summary
- named capabilities and technologies
- buyer or industry families served
- contract vehicles, SINs, or teaming clues
- location and delivery-model clues

Treat every website-derived fact as **provisional** until the user confirms it or until it is corroborated by a higher-confidence official source.

From GovTribe vendor bootstrap, extract available:
- vendor name, UEI, GovTribe profile URL, summary, location
- NAICS and taxonomy fields
- SBA certifications and business types
- contract vehicles, federal award, IDV, buyer, and agency signals
- GovTribe AI summary and similar market context when returned

Treat every GovTribe-derived fact as **GovTribe subscription-derived commercial intelligence** until the user confirms it. Keep those facts separate from website-derived and user-confirmed facts in provenance.

## Stage 1: plain-language business intake

Ask the user for:

1. **What do you do?**
   - one-sentence description
   - three strongest service or product lines

2. **What are you best at?**
   - highest-confidence deliverables
   - what buyers praise most often

3. **What should never show up?**
   - bad-fit work
   - unwanted agencies
   - unwanted places of performance
   - bad contract sizes
   - bad opportunity classes

4. **What proof do you have?**
   - 3 to 5 past projects, buyers, outcomes, or references
   - contract or grant sizes if known
   - industries or agency families served

5. **How do you like to win?**
   - prime
   - subcontract
   - teaming
   - grants
   - research partnerships

6. **What constraints matter?**
   - geography
   - certifications
   - set-asides
   - staffing model
   - delivery model
   - minimum viable award size
   - maximum realistic award size

## Stage 2: infer a starter preference pack

From the business description, infer:

- capability statements
- keyword include list
- keyword exclude list
- candidate buyer list
- candidate NAICS
- candidate federal taxonomy tags where relevant
- likely set-aside / certification relevance
- opportunity classes to include by default

## Stage 3: present codes in plain English first

Do **not** ask:
- "What are your NAICS codes?"

Instead ask:
- "Which of these descriptions sounds like your work?"
- "Which of these would you never want to be matched against?"

Then show the candidate code next to the description.

Use three buckets:
- confirmed
- candidate / still learning
- rejected

## Stage 4: build the starter files immediately

A website URL alone should be enough to create:
- `procurement/vendor-profile.json`
- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/STARTER_PROFILE.md`
- `MEMORY.md`

A website URL plus optional NAICS should produce the same files, but with tighter initial scoring and source filtering.

## Stage 5: start narrow, then widen carefully

Until the user gives feedback:
- show only high-confidence opportunities
- include a few near misses
- ask for quick reaction after the first shortlist

## Stage 6: learn from reasons, not just thumbs up/down

Whenever possible, capture the reason:
- right buyer
- wrong buyer
- right work
- too small
- too large
- wrong location
- wrong vehicle
- wrong timing
- good for teaming only
- good for subcontracting only
- wrong eligibility type

Those reasons are more useful than a bare "good" or "bad."

## Stage 7: convert repeated feedback into preferences

Use a simple maturity model:

- 1 signal: tentative
- 2 similar signals: medium preference
- 3 or more similar signals: promote to strong preference
- explicit "never" or "always": hard rule immediately

## Stage 8: preserve explainability

Each onboarding decision should remain explainable:
- what the skill inferred
- why it inferred it
- what the user confirmed
- what is still tentative

## Suggested first conversation script

1. "Give me your website, or tell me what your company does in plain English."
2. "If you know any NAICS codes, give me those too."
3. "What are the 3 types of work you are strongest at?"
4. "What work would waste your time if I showed it to you?"
5. "Name a few past projects, buyers, or outcomes."
6. "Do you want prime contracts, subcontracts, grants, or some combination?"
7. "What contract sizes and geographies are realistic for you?"
8. "Here is the starter preference pack I inferred. Confirm, reject, or adjust."

## Output of onboarding

At the end of onboarding, the skill should have enough information to create:
- `procurement/vendor-profile.json`
- `procurement/preferences.json`
- `procurement/source-registry.json`
- `procurement/STARTER_PROFILE.md`
- durable notes in `MEMORY.md`

The user should feel that they gave business language, not procurement jargon.

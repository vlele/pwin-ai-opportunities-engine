# Source catalog

This catalog favors official repositories first. It is designed to answer the question: "what should this skill check besides SAM.gov within the current federal-only release?"

## Default-on sources

### 1. SAM.gov Contract Opportunities
- **Type:** federal procurement notices
- **What it covers:** active and archived federal opportunity notices, with structured fields such as NAICS, set-aside, deadlines, notice type, and buyer
- **Access pattern:** official public API
- **Why it matters:** this is the primary federal contracts source
- **Trust tier:** 1
- **Portal:** https://sam.gov/content/opportunities
- **API docs:** https://open.gsa.gov/api/get-opportunities-public-api/
- **All SAM.gov API calls — Pass 1 (search) and Pass 2 (noticedesc) — must use exec+curl with SAM_API_KEY. Never use web_fetch (cannot inject env vars). Never use DEMO_KEY (does not work for authenticated endpoints). SAM_API_KEY is pre-configured; use it on the first and only attempt.**
- **Retrieval method:** Use exec+curl with SAM_API_KEY environment variable for both Pass 1 and Pass 2. Never use web_fetch (cannot inject env vars). Never use DEMO_KEY (does not work for authenticated endpoints).
- **Pass 1 — Search (one call per NAICS code):**
  `curl -s "https://api.sam.gov/opportunities/v2/search?ncode={NAICS}&postedFrom={MM/DD/YYYY}&postedTo={MM/DD/YYYY}&status=active&limit=25&api_key=${SAM_API_KEY}"`
  Use `ncode=` for NAICS filtering. Parameters `naics=`, `naicsCode=`, and `keywords=` are silently ignored by the v2 API. Confirmed 2026-04-01.
- **Pass 2 — Full notice description (one call per Pass 1 survivor, batched in one exec script):**
  `curl -s "https://api.sam.gov/prod/opportunities/v1/noticedesc?noticeid={noticeId}&api_key=${SAM_API_KEY}"`
  Path is `/prod/opportunities/v1/noticedesc` — NOT `/v2/` (returns 404). Full SOW text required for accurate scoring. If unavailable, apply -15 confidence penalty and note fallback.
- **Pass 2 verification requirements:** saved `summary` text must contain extracted prose, not the noticedesc URL or another placeholder. Record `noticedesc_fetched: true|false` plus `raw_match_evidence.full_desc_loaded: true|false` for every survivor. If a top candidate lacks usable Pass 2 text, it must not remain in the Action Now bucket.
- **Undocumented fallback (Pass 1 only, use only if v2 API is confirmed down):** `https://sam.gov/api/prod/sgs/v1/search/` with `naics=` param. No auth required but undocumented — may change without notice.
- **Notes:** best starting point for federal prime contract opportunities

### 2. SBA SUBNet
- **Type:** subcontracting opportunities
- **What it covers:** opportunities posted by large federal prime contractors seeking small subcontractors
- **Access pattern:** official public website
- **Why it matters:** catches opportunities that SAM.gov does not cover well
- **Trust tier:** 2
- **Portal:** https://www.sba.gov/federal-contracting/contracting-guide/prime-subcontracting/subcontracting-opportunities
- **Notes:** strong fit for vendors that prefer subcontracting or teaming

### 3. Acquisition.gov Agency Procurement Forecasts
- **Type:** forecast directory
- **What it covers:** links to recurring agency procurement forecast pages
- **Access pattern:** official public directory
- **Why it matters:** helps the user see likely future buys before formal solicitations appear
- **Trust tier:** 2
- **Portal:** https://www.acquisition.gov/procurement-forecasts
- **Notes:** treat as pipeline intelligence, not as a substitute for live notices

## Default-off or opt-in sources

### 4. Grants.gov / Simpler.Grants
- **Type:** grant opportunities
- **What it covers:** grant and assistance opportunities
- **Access pattern:** official API / official public docs
- **Why it matters:** useful for nonprofits, universities, public-sector innovation work, and grant-eligible vendors
- **Trust tier:** 1 when using the API
- **Portal:** https://simpler.grants.gov/developer
- **API docs:** https://api.simpler.grants.gov
- **Default status:** off unless the user wants grants or the profile clearly indicates grant eligibility

## Auth-required or special-case sources

### 5. GSA eBuy Open
- **Type:** RFQ / RFP market research and archive environment
- **What it covers:** historical or research-oriented access to eBuy RFQ/RFP information
- **Access pattern:** official portal with authentication requirements
- **Why it matters:** good for market research and past-buy pattern analysis
- **Trust tier:** 2 when accessible
- **Portal:** https://hallways.cap.gsa.gov/app/#/gateway/ebuy-open/
- **Default status:** disabled by default
- **Notes:** enable only when the user confirms they have access and wants it included

## Out of scope for this release

State and local procurement portals are intentionally excluded from the v1 scan scope.

Examples:
- Virginia eVA / Virginia Business Opportunities
- New York State Contract Reporter
- California Cal eProcure
- Texas ESBD / TxSmartBuy

## Operational guidance

1. Start with federal prime, federal subcontract, and forecast sources.
2. Enable grants only when appropriate.
3. Do not add state or local procurement portals in this release.
4. Keep auth-required portals disabled until explicitly requested.
5. Prefer structured API sources when both API and browser paths exist.
6. Track which taxonomy each source uses:
   - NAICS
   - grant categories
   - set-aside or eligibility labels

## Taxonomy note

For this release, center matching on federal taxonomies such as NAICS, set-aside signals, buyer labels, and award types. State and local commodity-code systems are deferred to a later phase.

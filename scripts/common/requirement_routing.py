"""Source-classified component routing; no keyword or customer-specific filters."""
from copy import deepcopy
from common.semantic_policy import CATEGORIZED_MISSING_PROOF_POLICY, CATEGORIZED_AUDIT_LABEL_POLICY

VERSION = "2"
CATEGORIES = ("technical_capability", "past_performance", "compliance_certification",
              "administrative_formatting", "contract_terms")
FIT_CATEGORIES = frozenset(CATEGORIES[:3])
APPLICABILITIES = ("prime_contractor", "not_prime_contractor", "unclear")
FIELDS = frozenset({"category", "applicability", "routing_reason"})

DECOMPOSITION_POLICY = """COMPONENT CATEGORY AND APPLICABILITY CONTRACT:
For EVERY component return category, applicability and a concise source-grounded
routing_reason, as well as kind, text and evidence. Category is independent of kind.
Use exactly these categories:
- technical_capability: required delivery effort and its technical performance,
  staffing, scale, acceptance and timing constraints, including project management.
- past_performance: required relevant experience, project counts, recency, reference
  relevance and evaluation of that experience, NOT proposal layout for references.
- compliance_certification: required credentials, authorizations, eligibility,
  certifications and technical/regulatory compliance. An eligibility registration
  is not mere formatting just because it is checked at proposal submission.
- administrative_formatting: PROPOSAL page limits, fonts, margins, upload mechanics,
  file formats, submission portals, proposal deadlines and proposal assembly rules.
  A technical deliverable's dimensions/format can be a technical requirement instead.
- contract_terms: payment, price basis/allocation, ordinary place of performance,
  commercial rights, document precedence and package background/definitions.
Split mixed clauses before categorizing: installation is technical_capability and
its fixed-price allocation is contract_terms. A required credential is separate from
instructions to attach its certificate. A binding task-specific response time or
capacity is technical_capability, not a disposable contract term. Do not hide work,
eligibility, experience criteria or acceptance limits in the bypass categories.

SOCIOECONOMIC THRESHOLDS AND SUBMISSION MECHANICS:
Small-business participation percentages, socioeconomic eligibility and associated
evaluation thresholds are compliance_certification, NOT technical_capability.
Preserve the exact threshold, denominator, eligible entities and exceptions. Preserve
conditional evaluation credit as conditional; do not convert bonus-credit criteria
into mandatory eligibility or infer that the prime must hold a subcontractor's status.
Separately classify instructions to rename a file, upload proof, fill a proposal
worksheet or put evidence in a named volume as administrative_formatting. Those
mechanics do not replace the underlying substantive compliance criterion.
Not every quantitative threshold is socioeconomic compliance. Technical response times,
availability, capacity and accuracy thresholds remain technical_capability. Relevant
project counts and recency remain past_performance. Classify the proposition, not
its percentage sign, number, document title or the fact that it is evaluated.

applicability is prime_contractor when the package assigns the duty/criterion to
this offeror/prime, including responsibility for its team. Government evaluation of
the offeror's experience/eligibility is an applicable criterion, not a government-only
duty. not_prime_contractor requires source support: another inapplicable track,
historical/background context, definition or a government-only duty. unclear means
the supplied text leaves applicability genuinely unresolved; never guess a track or
treat missing vendor credentials as proof that an official requirement does not apply.
Preserve conditional language. Vendor information must not decide applicability.
Code uses unrelated ONLY for a supported not_prime_contractor disposition. This is
not a vendor-fit label. Missing vendor proof never makes a requirement unrelated.
Administrative and commercial rules remain recorded obligations/checklist entries,
not satisfied requirements. Keep original status, sources, conflicts and precedence.
"""

POST_AWARD_POLICY = """POST-AWARD DELIVERABLES VERSUS PROPOSAL FORMATTING:
Classify the obligation's lifecycle and substance, not its document title. Preparing
or updating a performance deliverable after award/exercise/restoration (such as a
transition plan, staff roster or incident report) is not administrative_formatting.
Technical/project-management delivery and task-specific deadlines are
technical_capability. Pure commercial/payment notices and their deadlines may be
contract_terms. Do not hide actual delivery work in contract_terms to skip comparison.
Proposal page limits, margins, filenames, bid deadlines and proposal upload rules
are administrative_formatting. Distinguish a plan submitted WITH the proposal from
the operational plan delivered AFTER award, even when both have the same name.
For mixed clauses split bid-submission mechanics from performance obligations,
retaining each actor, timing trigger and exception. No keyword-based override.
"""
DECOMPOSITION_POLICY += "\n" + POST_AWARD_POLICY

COMPARISON_POLICY = """CATEGORIZED VENDOR PROOF CONTRACT:
Evaluate only the supplied isolated claim against THIS component. Category and
applicability are immutable, source-classified inputs; do not reclassify to avoid
missing proof. Administrative formatting and contract terms are routed by code and
are not vendor-fit jobs. Conditional technical performance and eligibility still are.
missing: the government requires this capability, qualification, experience or
action but this vendor claim supplies no specific evidence establishing it. This
includes a generic offering or a concrete different project with no demonstrated
overlap. Describe the supplied project's actual scope without inventing outside work.
unrelated: ONLY a package statement that is not a requirement/criterion for this
prime contractor. Code routes those separately; NEVER return unrelated for a vendor
comparison. Missing proof does not mean inability or ambiguity and needs no rescue
question. not_applicable is also not a vendor response in this categorized path.
matched/partial/transferable require specific claim-local affirmative evidence.
partial means an evidenced subset of the same work; transferable requires a concrete
method shared by different work, not a generic industry/technology word. For actual
work, only self-attributed affirmative execution can receive positive work credit;
dates, assets, future offers and denials cannot. An explicit qualification may prove
that reported qualification, never unstated conditions or independently verified status.
contradicted is reserved for an explicit denial naming THIS exact duty/condition;
never widen it to unstated locations, validations, other tasks or sibling claims.
ambiguous requires genuinely unclear supplied text/attribution, not absent proof.
Keep timing, certification and other conditions missing if only core work is proven.
Use evidence only from the isolated claim or permitted linked negative context.
An evidence ID proves provenance, not entailment. Government instructions never prove
vendor compliance. supported_scope contains only the exact supported scope for a
positive result and is empty otherwise. Each reason must address this component,
not another component sharing its quotation. The schema owns the allowed statuses.
""" + "\n" + CATEGORIZED_MISSING_PROOF_POLICY

ROUTING_FIDELITY_POLICY = POST_AWARD_POLICY + "\n" + """CATEGORIZED ROUTING AUDIT:
Where components carry category/applicability, independently check those labels and
routing_reason against original package evidence. Reject disguised scope, technical
acceptance, experience or eligibility that was classified as formatting/ordinary
contract terms to skip fit evaluation. Reject unsupported not_prime_contractor labels.
Government scoring of offeror experience is an applicable criterion even though the
Government scores it. Preserve nonapplicable and superseded material as context.
Code compares only prime_contractor components in technical_capability,
past_performance and compliance_certification. Excluded components have NO vendor
finding and never improve or dilute vendor-fit coverage. That deliberate exclusion
is not an omission if the complete source component remains in the routing ledger.
Administrative and contract checklists do not prove compliance. Applicable contract
terms remain commercial obligations/risks even though not vendor capability proof.
This check audits package classification/applicability, not the vendor's ability
to comply. No vendor comparison verdict is requested in a source-fidelity audit.
"""

AUDIT_POLICY = ROUTING_FIDELITY_POLICY + """
For categorized comparisons missing and unrelated are NOT interchangeable. Missing
means no supplied proof of an applicable component, including concrete different work
without supported overlap. unrelated is reserved for a source-supported non-prime
package disposition, never a vendor finding or fit label. Reject an unrelated vendor
finding even when withholding positive credit would otherwise be appropriate.
Audit every reported finding against its own component and the isolated vendor claim.
Do not demand findings for bypassed components or credit them as satisfied. A source-
fidelity check still judges package recording, never whether the vendor can comply.
Aggregated fit covers ONLY vendor-assessable components, never proposal readiness.
For standalone experience/certification criteria the record-level operational
relationship/coverage is not_applicable, while component findings and fit_label
still explicitly assess the criterion. Do not confuse that record-level relationship
with a forbidden not_applicable component response. Purely missing components give
Missing Proof; an explicit denied component without positive credit gives Contradicted.
The operational relationship can remain unknown when no work match is established;
read each component status, not that summary alone. Mixed supported and missing or
denied components give Partial Fit, with the unsatisfied components preserved.
""" + "\n" + CATEGORIZED_AUDIT_LABEL_POLICY


def schema_fields():
    return {"category": {"type": "string", "enum": list(CATEGORIES)},
            "applicability": {"type": "string", "enum": list(APPLICABILITIES)},
            "routing_reason": {"type": "string", "minLength": 1}}


def validate_part(part):
    if part.get("category") not in CATEGORIES or part.get("applicability") not in APPLICABILITIES:
        raise ValueError("Every current component requires a valid category and applicability; re-decompose legacy records.")
    if not isinstance(part.get("routing_reason"), str) or not part["routing_reason"].strip():
        raise ValueError("Component routing requires a source-grounded reason.")


def categorized(requirement):
    """Unclassified historical graphs remain readable, never a production default."""
    parts = requirement.get("components", [])
    found = any(FIELDS & set(part) for part in parts)
    if found:
        for part in parts:
            validate_part(part)
    return found


def route(part, status="current"):
    validate_part(part)
    if status != "current":
        return "inactive_context"
    if part["applicability"] == "not_prime_contractor":
        return "unrelated"
    if part["applicability"] == "unclear":
        return "applicability_review"
    if part["category"] in FIT_CATEGORIES:
        return "vendor_comparison"
    return {"administrative_formatting": "proposal_checklist",
            "contract_terms": "contract_terms_checklist"}[part["category"]]


def assessed_components(requirement):
    modern = categorized(requirement)
    return {f"K{i}": part for i, part in enumerate(requirement.get("components", []))
            if not modern or route(part, requirement.get("status", "current")) == "vendor_comparison"}


def ledger(requirements):
    rows = []
    for ri, req in enumerate(requirements):
        if not categorized(req):
            continue
        for ki, part in enumerate(req["components"]):
            rows.append({"requirement_id": f"R{ri}", "component_id": f"K{ki}",
                         "status": req["status"], "route": route(part, req["status"]),
                         "compliance_status": "not_assessed", **deepcopy(part)})
    return rows


def checklists(requirements, spans):
    from common.semantic_plan import _anchors
    from common.evidence_selection import source_locations
    result = {"proposal_formatting_submission_checklist": [], "contract_terms_checklist": [],
              "requirement_applicability_notes": []}
    routes = {"proposal_checklist": "proposal_formatting_submission_checklist",
              "contract_terms_checklist": "contract_terms_checklist",
              "unrelated": "requirement_applicability_notes", "applicability_review": "requirement_applicability_notes",
              "inactive_context": "requirement_applicability_notes"}
    for row in ledger(requirements):
        key = routes.get(row["route"])
        if key is None:
            continue
        _anchors(row["evidence"], spans, package=True)
        row["citations"] = [{**deepcopy(a), "source_id": spans[a["ref"]]["source_id"],
                             "locations": source_locations(spans[a["ref"]])} for a in row["evidence"]]
        result[key].append(row)
    return result


def add_applicability_questions(inventory):
    """Unclear applicability is reviewed, never silently treated as out of scope."""
    result = deepcopy(inventory)
    for i, req in enumerate(result["requirements"]):
        unclear = [p for p in req.get("components", []) if route(p, req["status"]) == "applicability_review"]
        if unclear and not any(q["dimension"] == "requirement_meaning" and i in q["requirements"] for q in result["questions"]):
            result["questions"].append({"dimension": "requirement_meaning", "claims": [], "requirements": [i],
                "reason": "Applicability to this prime is unresolved: " + "; ".join(p["routing_reason"] for p in unclear),
                "decision": "scope"})
    return result

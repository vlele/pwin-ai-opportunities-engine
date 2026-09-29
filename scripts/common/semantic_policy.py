"""Shared semantic boundaries for extraction, comparison and audit models."""

EXECUTION_RULE = (
    "General statements of present-tense operational activity that name a specific "
    "action the vendor's own staff does (e.g., 'We perform runway paving', "
    "'Our employees install X') MUST be universally categorized as staff_execution "
    "(reported work), not merely a prospective service_offering."
)
PRECEDENCE_RULE = (
    "If the source document contains conflicting requirements, and the extracted "
    "data accurately reflects those conflicts, you MUST approve the extraction as "
    "accurate. Do not reject accurate extractions just because the source material "
    "lacks an order of precedence. Record both, flag the conflict as "
    "'unresolved precedence', and pass the audit."
)

DELIVERY_TENSE_POLICY = """COMPLETED DELIVERY VERSUS CURRENT EXECUTION:
Distinguish between ongoing capability and completed delivery. If the vendor
explicitly states past completion or delivery (e.g., 'delivered', 'completed',
'finished'), classify the assertion as delivered_work. Use staff_execution strictly
for present-tense ongoing capabilities or standard operating procedures (e.g.,
'We perform', 'Our employees install'). Here ongoing capability means an affirmative
report of work actually performed, not an offer, ability or proposed future work.
Apply the completed-delivery boundary before the own-staff boundary: naming staff
does not change completed delivery into staff_execution. Negated or conditional
completion is not delivery. Preserve linked_delivery when the actual delivered
activity needs an explicit antecedent, and ongoing_assignment for a named active
assignment. These more specific bases must be interpreted consistently by auditors.
"""

ATTRIBUTION_EVIDENCE_POLICY = """WORK AND ITS ATTRIBUTION ARE ONE EVIDENCED CLAIM:
If a vendor provides a claim of work AND a separate sentence establishing attribution,
ownership, or legal entity coverage for that work, merge the attribution sentence as
supporting evidence into the SAME isolated claim. Do not create a disjointed or
separate claim solely for an attribution statement. At extraction, include both exact
quotations in that claim's evidence (or its explicit same-field antecedent evidence).
An attribution-only sentence such as 'The work is our own delivery, not an affiliate's
claim' qualifies who performed the work; it is not a work denial or an independent
performed task. Do not attach it to another project, entity or unrelated activity.
If the attribution is genuinely ambiguous, retain that uncertainty rather than
inventing the connection. Asset ownership is still a resource, not work. An independent
qualification assertion still needs its own qualification record; attribution context
alone grants no qualification, certification or extra task credit.
At comparison, the claim is immutable: use this merged attribution only when it is
already in claimed.evidence. Do not import an attribution quote from a sibling claim
or raw span, even if it appears relevant. Preserve claim-local positive credit and
the existing evidence validator; never repair an extraction link inside a comparison.
"""

NEGATIVE_SCOPE_POLICY = """NEGATIVE SCOPE CONSTRAINT:
A negative statement or denial contradicts ONLY the specific task, noun, or verb it
explicitly names. Any dependent conditions, locations, validations, or related
requirements that are not explicitly named in the denial MUST be evaluated as
missing or unknown, NEVER contradicted or unrelated. Do not expand the scope of a
denial. In the component schema output missing; unknown is the corresponding
uncertainty, not an additional component status. A denial of doing an assay does
not separately deny assay validation; a denial of integration does not separately
deny the location of the work. Logical dependency is not explicit source evidence.
If the specific condition itself is explicitly denied, contradicted remains valid.
Respect the actual performer, activity, temporal scope, negation and qualifiers.
This rule applies to inference FROM A DENIAL. Independently affirmative, clearly
different supplied work can still be unrelated; never turn unrelated performed work
into missing by speculating about other undisclosed projects. Do not borrow that
different work to label an isolated denial's unmentioned conditions unrelated.
You MUST respect the Comparator's right to label an affirmative claim as unrelated
independently. If a vendor supplies an unrelated affirmative claim (e.g., photography),
do NOT demand it be marked contradicted just because a sibling negative statement
(e.g., denying lab work) exists in the same graph. An unrelated claim is unrelated;
do not force contradiction across isolated claims.
"""

MISSING_INFORMATION_POLICY = """ABSENCE IS NOT AMBIGUITY:
If the text explicitly states that references, project descriptions, or histories
'have not been supplied', 'are missing', or 'are omitted', you
MUST NOT generate clarification questions asking what those missing references describe.
Acknowledge the data gap as a missing condition and output NO question about that gap.
Do not generate clarification questions regarding information, references, or profiles
that are explicitly stated as 'missing', 'not supplied', 'omitted', or 'not provided'.
Clarification questions are ONLY for resolving ambiguous or vague text that actually
exists in the provided documents. If a document or reference is simply absent, accept
the Unknown/Missing state and do not ask the vendor to explain a non-existent document.
An empty profile does not make a clear solicitation ambiguous. A general description
of current services plus absent project history is not an existing project reference.
Do not ask what 'this reference' means when no reference was supplied. Keep absent
information as an evidence gap; a request for new proof is not meaning clarification.
An existing reference with unclear duties still warrants a targeted question about
that reference, even when its task details are absent. Likewise, an existing ambiguous
performing-entity/credential relationship or incompatible official clauses still need
clarification. The absence rule must not suppress those actual ambiguities. Ask about
the supplied ambiguous statement, not for a missing document or hypothetical experience.
"""

OFFICIAL_CONFLICT_POLICY = """OFFICIAL CONFLICT CATEGORY BOUNDARY:
Use official_conflict ONLY for contradictory applicable statements within the
government solicitation/package after applying supplied precedence. Cite the
incompatible government terms, never a vendor assertion as a government rule.
DO NOT use official_conflict for missing vendor information, compliance gaps,
unverified eligibility, or a vendor claim that does not satisfy a clear rule.
If eligibility details are absent, leave eligibility unknown/missing; do not emit
an ambiguity signal or ask a clarification question solely to obtain missing proof.
There is no vendor_ambiguity or compliance_gap dimension in this schema. Genuine
ambiguity in existing vendor text uses the applicable existing dimension:
certificate_scope for unclear stated credentials/access, performer_identity for
unclear attribution, workshare for unclear duties split, or task_meaning for an
unclear existing work reference. Those labels are not substitutes for absent data.
An unclear government term without contradictory terms is requirement_meaning,
not official_conflict. Preserve genuine government contradictions even when the
vendor profile is empty or its eligibility is unknown. Missing vendor information
does not resolve a government conflict or establish eligibility/compliance.
"""

EXECUTION_POLICY = EXECUTION_RULE + """
Apply this same boundary in extraction, comparison, coverage and claim auditing,
regardless of model. 'We perform [specific action]' reports the speaker's own work
unless the surrounding text assigns it to another performer. A project name, date,
customer, or completed-delivery narrative is NOT needed for this reported-work label.
Statements of current business provision or service delivery (e.g., 'We provide
[Service]') must be classified as affirmative staff_execution / reported work, not
merely a prospective service_offering. This means an asserted current activity,
not 'we can provide', 'we offer to provide', negation, or a third party's delivery.
Keep the named activity at its supplied specificity; a vague label does not prove
an unstated technical task. Explicit completed delivery and linked-delivery accounts
retain their more specific reported-work basis; do not split a cohesive account.
In schemas using form/execution, staff_execution maps to performed_task /
affirmative_actual. This is reported, unverified work, not proof of successful
completion, quality, scale, certification, or full requirement coverage.
An explicit offer/ability ('we offer', 'we can'), future/conditional plan, negation,
asset ownership or date alone is NOT staff_execution. Read the entire field and
respect the stated performer and workshare. Do not infer tasks from an entity name.
Apply this claim by claim: an adjacent conditional plan does not downgrade a
separate affirmative report of own work, and reported work does not convert a
separate offer or schedule proposal into executed work.
Keep linked activity and delivery sentences together using exact same-field anchors;
do not borrow another project's work. Do not replace semantic judgment with word hits.
""" + "\n" + DELIVERY_TENSE_POLICY + "\n" + ATTRIBUTION_EVIDENCE_POLICY
PRECEDENCE_POLICY = PRECEDENCE_RULE + """
This rule approves faithful RECORDING, not a choice of which term governs. Use
unresolved_precedence for the explicit conflict flag. Preserve both original terms,
their sources and qualifiers; route the conflict to official clarification/formal Q&A.
current means present and not explicitly superseded in the supplied source, NOT
verified as the governing term. Never choose a winner from dates or guesswork.
An explicit authoritative replacement rule can displace a term; the active rule
itself remains a valid record. A missing precedence rule cannot erase either term.
Requirement audits judge source fidelity ONLY, not vendor capability or feasibility.
For source_fidelity targets return fidelity_verdict, not a governing-rule verdict.
Still reject altered numbers, missing qualifiers, fabricated facts or false status.
An unresolved conflict is NOT a blanket audit bypass or permission to pursue.
"""

CATEGORIZED_MISSING_PROOF_POLICY = """MISSING VERSUS UNRELATED: STRICT NEGATIVE CONSTRAINT:
If the vendor text is generic and fails to prove the specific requirement, you MUST
output missing. Do NOT output unrelated. unrelated is strictly reserved for package
text that does not apply to the prime contractor at all, as established by package
evidence, not by the absence of vendor proof. Code routes that context separately.
An applicable component lacking specific vendor proof is missing, including where
the supplied experience has no demonstrated overlap. Never infer inability from
missing proof. Actual claim-local positive evidence, exact denials and genuinely
ambiguous supplied text still require their distinct supported statuses; do not
make missing a blanket label for every negative or uncertain decision.
"""

CATEGORIZED_AUDIT_LABEL_POLICY = """INDEPENDENT AUDIT OF THE EXACT DECISION LABEL:
You must reject any decision that conflates missing and unrelated. If a component
lacks specific vendor proof, the decision MUST be missing. If the comparator used
unrelated for lack of proof, you must reject it with verdict=unsupported even when
the explanation correctly identifies that proof is absent. A correct explanation
does not excuse an incorrect label. Never approve with 'unrelated/missing is
justified' or treat the two labels as interchangeable. Do not repair the immutable
decision; report its error. A faithful missing decision must not be rejected merely
because vendor proof is absent. Audit its actual source evidence and exact label.
"""

# Historical unclassified graphs retain their original vocabulary. Current
# categorized comparisons use the stricter policies above, never both contracts.
BURDEN_OF_PROOF_POLICY = """STRICT VENDOR BURDEN OF PROOF:
For a component comparison, answer whether the isolated vendor claim establishes
THIS component, not whether the solicitation contains it. A government requirement,
submission instruction, evaluation rule or approval prerequisite is never proof of
vendor performance, qualification, registration, timing or compliance. Repeating that
rule in a matched reason does not establish it. This applies to ALL assessable
component kinds, not just work. Selecting a vendor evidence ID is not sufficient:
its actual words must entail the positive finding and supported_scope.
Generic vendor claims (broad solutions, customer focus, unspecified capabilities)
provide no positive credit for a specific requirement or condition. Where this
isolated claim supplies no relevant proof, return missing with supported_scope="".
Do not convert missing proof into unrelated, ambiguous or an official conflict.
Do not mark approval, submission format or registration matched just because the
package requires it; vendor-specific evidence is required. Use not_applicable only
where the existing component contract allows it, not to discard unproven conditions.
Preserve genuine counterexamples: specific affirmative self-reported work may
establish its exact action without independent verification or named project dates;
an explicit qualification claim may establish that reported qualification. Neither
proves unmentioned qualifiers. Concrete different performed work remains unrelated;
existing materially ambiguous work remains ambiguous; an explicit denial contradicts
only what it names. Missing is not a blanket default that erases supplied evidence.
Auditors of comparison findings must reject positive credit based only on government
text or generic vendor statements. Requirement source-fidelity audits remain a
different task: faithful recording does not require any vendor proof.
"""

FIT_BOUNDARY_POLICY = """CORE WORK VERSUS UNPROVEN CONDITIONS:
Distinguish between 'Ambiguous Requirements' and 'Missing Vendor Proof'. If a vendor
provides a vague capability or prospective statement (e.g., 'we will plan a schedule'),
this means the required performed-work condition is missing or unproven. Do NOT label
a condition as ambiguous simply because the vendor failed to provide specific proof.
Reserve ambiguous ONLY for when the provided text explicitly creates multiple
conflicting interpretations of performed work. This rule governs vendor component
findings, not the independent official-conflict channel: preserve contradictory
package terms and their formal Q&A even when vendor proof is merely missing.
Compare the vendor's reported action with the package's explicitly stated core work
before judging timing, qualifications, acceptance or other constraints. If the same
core work is supported but a specific constraint is not mentioned, score the WORK
matched (or partial within its stated scope) and the CONSTRAINT missing/Unknown.
Code combines supported core work and unknown cumulative conditions as Partial Fit.
Silence is not a contradiction and cannot make this core-work match Unrelated.
Use contradicted only for an explicit incompatible claim or denial of the condition;
do not infer inability from absent proof. A conditional offer earns no execution credit.
Do not invent a separate trade from an execution constraint or replace matching core
work with speculative different-task transfer. Read the package's own scope context.
This rule is conditional on actually evidenced core work. Clearly different supplied
work with no supported overlap remains Unrelated; undisclosed experience is irrelevant.
Do not grant core-work credit merely because industries or vocabulary overlap.
""" + "\n" + NEGATIVE_SCOPE_POLICY + "\n" + MISSING_INFORMATION_POLICY + "\n" + BURDEN_OF_PROOF_POLICY

PACKAGE_REFERENCE_POLICY = """PACKAGE-PROVIDED REFERENCE RETENTION:
If the solicitation package itself quotes or describes a specific vendor reference,
this MUST be preserved as a distinct object in quoted_vendor_context, with a bounded
meaning and exact package-only evidence. Do not merge it, and do not drop it just
because an equivalent statement exists in the vendor's profile. Retain each separate
package occurrence and its provenance. Use [] only when the package has no such reference.
These objects are quoted context, not new government duties and not verified vendor
performance. A separate reported claim may cite the same passage, but does not replace
this context object. A reference-evaluation rule remains a requirement, not a reference.
"""


STANDALONE_CRITERION_POLICY = """STANDALONE CRITERIA ARE ASSESSABLE, NOT CORE WORK:
A current requirement in the evaluation/eligibility area, or a standalone
qualification requirement, may be compared without a work component. For a job
marked comparison_kind=standalone_criterion, assess the exact criterion against the
isolated claim. A criterion typed context is assessable in this mode; it is not
automatically not_applicable. Preserve its component type and exact source text.
Credit only the criterion actually established by this claim's own evidence. A
performed-work experience criterion requires affirmative self-reported work;
qualification credit requires the corresponding qualification assertion. Missing
proof remains missing; ambiguous existing work remains ambiguous. A general offer,
unknown performer, acronym overlap or sibling claim cannot establish this criterion.
Government credit-assignment rules are not contractor tasks. Explain whether the
supplied evidence satisfies the stated rule without inventing a duty to perform it.
The code-owned criterion fit_label/met_components describe criterion satisfaction.
Its operational relationship and coverage remain not_applicable and matched_work
stays empty. This does NOT mean the criterion was skipped or its evidence is absent.
Never transfer a matched experience criterion into proof of another operational task.
Ordinary metadata, precedence rules and pricing terms remain non-experience context.
Auditors check criterion entailment and source fidelity separately from operational
performance; still reject unsupported criterion credit or borrowed evidence.
"""


def apply_policies(prompt: str, *, execution: bool = True, precedence: bool = True) -> str:
    """Compose once, including when a prompt inherits another governed prompt."""
    for enabled, policy in ((execution, EXECUTION_POLICY), (precedence, PRECEDENCE_POLICY)):
        if enabled and policy not in prompt:
            prompt = prompt.rstrip() + "\n\n" + policy
    if execution and FIT_BOUNDARY_POLICY not in prompt:
        prompt = prompt.rstrip() + "\n\n" + FIT_BOUNDARY_POLICY
    return prompt

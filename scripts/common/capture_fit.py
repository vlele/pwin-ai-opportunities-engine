"""Current-package/company evidence contracts; no customer-specific matching rules."""
from __future__ import annotations

from copy import deepcopy
from typing import Any


def _strings(value: Any) -> list[str]:
    return [str(v).strip() for v in value if isinstance(v, str) and v.strip()] if isinstance(value, list) else []


def _profile_fields(source, context):
    fields = {source.get("profile_field")} if source.get("kind") == "profile" else set()
    if source.get("kind") == "user_answer":
        for answer in context.get("answers", []):
            if answer.get("question_id") == source.get("question_id"):
                fields.update(context.get("sources", {}).get(c.get("source_id"), {}).get("profile_field")
                              for c in answer.get("citations", []))
    return fields - {None, ""}


def _component_credit(edge, requirement):
    """Ranking proxy, not a measured share of work or a win probability."""
    if edge["relationship"] not in {"same_task", "applicable_different_task"}:
        return 0.0
    if edge["coverage"] == "complete":
        return 1.0
    applicable = [f"K{i}" for i, part in enumerate(requirement["components"]) if part["kind"] not in {"context", "pricing"}]
    values = [{"matched": 1.0, "partial": .5, "transferable": .4}.get(edge["component_findings"][key]["status"], 0.0)
              for key in applicable]
    # Separate claims are not assumed to be the same engagement or combined into
    # full coverage. A partial claim cannot become complete through averaging.
    return min(.99, sum(values) / max(1, len(values)))


def _component_score(fraction):
    if fraction <= 0:
        return 0
    return 15 if fraction >= 1 else max(1, int(15 * fraction))


def _bind_checked_graph(catalog, context):
    from common.capture_understanding import build_spans
    from common.semantic_contract import aggregate_components, has_work, validate_components, validate_focus
    graph = context["checked_evidence_graph"]
    if context.get("understanding_audit", {}).get("claim_evidence", {}).get("passed") is not True:
        raise ValueError("A checked graph requires a passing assertion audit.")
    spans = build_spans({"sources": context["sources"]})
    requirements, rules = {}, []
    for i, record in enumerate(graph["requirements"]):
        validate_focus(record, spans)
        validate_components(record, spans)
        if record["status"] != "current":
            continue
        if record["record_kind"] == "precedence_rule":
            rules.append({"requirement_id": f"R{i}", **deepcopy(record)})
        elif record["record_kind"] == "requirement" and has_work(record):
            requirements[f"R{i}"] = {"text": " ".join(a["quote"] for a in record["focus"]),
                                      "anchors": [a["quote"] for a in record["focus"]],
                                      "components": deepcopy(record["components"]), "logic": record["logic"],
                                      "source_requirement_id": f"R{i}"}
    catalog.update(requirements=requirements, active_precedence_rules=rules, assessment_mode="checked_component_graph")
    fields = {}
    for index, claim in enumerate(graph["claims"]):
        for anchor in claim["evidence"]:
            for field in _profile_fields(spans[anchor["ref"]], context):
                fields.setdefault(field, set()).add(index)
    for entry in catalog["vendor_evidence"].values():
        claim_ids = fields.get(entry["profile_field"], set())
        bounds = {}
        for edge in graph["comparisons"]:
            rid = f"R{edge['requirement']}"
            if edge["claim"] not in claim_ids or rid not in requirements:
                continue
            requirement = graph["requirements"][edge["requirement"]]
            checked = aggregate_components(requirement, graph["claims"][edge["claim"]], edge["component_findings"], spans)
            bounds.setdefault(rid, []).append({"claim_id": f"C{edge['claim']}", **checked,
                                               "credit_fraction": _component_credit(checked, requirement)})
        entry["understanding_credit"] = {
            "allowed": any(e["credit_fraction"] > 0 for edges in bounds.values() for e in edges),
            "claim_ids": [f"C{i}" for i in sorted(claim_ids)], "by_requirement": bounds,
            "basis": "Immutable checked claim/component comparisons; never field-wide proof of a different task.",
        }


def _checked_projects(catalog):
    projects = []
    for pid, entry in catalog["vendor_evidence"].items():
        if entry["kind"] != "past_performance":
            continue
        by_requirement = entry["understanding_credit"]["by_requirement"]
        positive = {}
        for rid, edges in by_requirement.items():
            candidates = [e for e in edges if e["credit_fraction"] > 0]
            if candidates:
                positive[rid] = deepcopy(max(candidates, key=lambda e: (e["credit_fraction"], e["relationship"] == "same_task")))
        relations = {e["relationship"] for edges in by_requirement.values() for e in edges}
        relevance = ("direct" if any(e["relationship"] == "same_task" for e in positive.values()) else
                     "transferable" if positive else "unrelated" if relations == {"unrelated"} else "unknown")
        reason = " ".join(f"{rid}/{e['claim_id']}: {e['fit_label']}. {e['reason']}" for rid, e in positive.items())
        if not reason:
            reason = ("Supplied project text is unrelated to the current tasks." if relevance == "unrelated" else
                      "No positive performed-work match is established by the supplied project text.")
        projects.append({"project_id": pid, "relevance": relevance, "requirement_ids": list(positive),
                         "coverage_by_requirement": positive, "checked_component_assessments": deepcopy(by_requirement),
                         "reason": reason,
                         "classification_source": "checked_component_graph"})
    return projects


def _checked_requirement_assessments(catalog):
    rows = []
    for rid in catalog["requirements"]:
        all_edges, positives = [], []
        for eid, evidence in catalog["vendor_evidence"].items():
            edges = evidence["understanding_credit"]["by_requirement"].get(rid, [])
            all_edges.extend(edges)
            positives.extend((eid, e) for e in edges if e["credit_fraction"] > 0)
        relations = {e["relationship"] for e in all_edges}
        match = ("direct" if any(e["relationship"] == "same_task" for _, e in positives) else
                 "transferable" if positives else "none" if relations == {"unrelated"} else "unknown")
        row = {"requirement_id": rid, "match": match, "vendor_evidence_ids": list(dict.fromkeys(eid for eid, _ in positives)),
               "reason": " ".join(e["reason"] for e in all_edges) or "No checked project comparison is available.",
               "fit_label": "Partial Fit" if any(e["fit_label"] in {"Partial Fit", "Supported Fit"} for e in all_edges) else "Unrelated" if match == "none" else "Unknown",
               "component_assessments": deepcopy(all_edges),
               "classification_source": "checked_component_graph"}
        if positives:
            best = max((e for _, e in positives), key=lambda e: e["credit_fraction"])
            row.update(coverage=best["coverage"], credit_fraction=best["credit_fraction"],
                       fit_label=best["fit_label"])
        rows.append(row)
    return rows


def _record_overrides(proposed, checked, id_key, keys):
    originals = {}
    overrides = []
    if not isinstance(proposed, list):
        overrides.append({"field": id_key, "proposed": deepcopy(proposed), "reason": "Expected an array; checked decisions retained."})
        proposed = []
    for original in proposed:
        key = original.get(id_key) if isinstance(original, dict) else None
        if not isinstance(key, str) or key in originals:
            overrides.append({"field": id_key, "proposed": deepcopy(original), "reason": "Invalid or duplicate identity; checked decisions retained."})
            continue
        originals[key] = original
    for row in checked:
        original = originals.pop(row[id_key], {})
        if any(original.get(key) != row[key] for key in keys):
            overrides.append({id_key: row[id_key], "proposed": deepcopy(original),
                              "retained": {key: deepcopy(row[key]) for key in keys}})
    overrides.extend({id_key: key, "proposed": deepcopy(value), "retained": None} for key, value in originals.items())
    return overrides


def build_fit_catalog(profile: dict, workstreams: list[dict], *, clarification_context: dict | None = None) -> dict:
    requirements, evidence = {}, {}
    for row in workstreams[:8]:
        text = str(row.get("objective") or row.get("title") or "").strip()
        anchors = _strings(row.get("evidence_snippets"))
        if text and anchors:
            requirements[f"R{len(requirements) + 1}"] = {"text": text, "anchors": anchors[:3]}
    for field, prefix, kind in (("core_competencies", "C", "capability"), ("past_performance_highlights", "PP", "past_performance")):
        values = profile.get(field)
        for index, text in enumerate(values if isinstance(values, list) else []):
            if not isinstance(text, str) or not text.strip():
                continue
            # Source-field indexes must not shift when empty entries are skipped.
            evidence[f"{prefix}{index + 1}"] = {"kind": kind, "text": text.strip(), "profile_field": f"{field}[{index}]", "provenance": "user_supplied_not_independently_verified"}
    context = clarification_context or {}
    if context.get("understanding_audit", {}).get("claim_evidence", {}).get("passed") is True:
        checked_fields = {}
        for finding in context.get("open_gaps", []):
            if finding.get("record_type") == "question":
                continue
            for citation in finding.get("claim_citations", []):
                source = context.get("sources", {}).get(citation.get("source_id"), {})
                fields = {source.get("profile_field")} if source.get("kind") == "profile" else set()
                if source.get("kind") == "user_answer":
                    for answer in context.get("answers", []):
                        if answer.get("question_id") == source.get("question_id"):
                            fields.update(context.get("sources", {}).get(c.get("source_id"), {}).get("profile_field")
                                          for c in answer.get("citations", []))
                for field in fields - {None, ""}:
                    checked_fields.setdefault(field, []).append(finding)
        for row in evidence.values():
            findings = checked_fields.get(row["profile_field"], [])
            positives = [f for f in findings if f.get("claim", {}).get("subject") == "performed_work"
                         and f.get("relevance") in {"direct", "transferable"} and f.get("attribution", "self") == "self"]
            withheld = row["kind"] == "past_performance" and not positives
            if findings and all(f.get("relevance") == "unrelated" for f in findings):
                withheld = True
            row["understanding_credit"] = {"allowed": not withheld,
                                           "claim_ids": [f.get("claim_id") for f in findings if f.get("claim_id")],
                                           "basis": "Checked input claims bound later credit; no new performance evidence is created here."}
    for answer in context.get("answers", []):
        if answer.get("kind") not in {"vendor_experience", "vendor_role", "vendor_scale", "vendor_recency", "company_identity"}:
            continue
        fields = {context.get("sources", {}).get(c.get("source_id"), {}).get("profile_field") for c in answer.get("citations", [])}
        for row in evidence.values():
            if row["profile_field"] in fields:
                row.setdefault("clarifications", []).append(answer)
                row["text"] += f" [User-reported clarification {answer['question_id']}: {answer['answer']}]"
    catalog = {"requirements": requirements, "vendor_evidence": evidence}
    if "checked_evidence_graph" in context:
        try:
            _bind_checked_graph(catalog, context)
        except (ValueError, KeyError, TypeError, IndexError) as error:
            catalog["validation_issues"] = [f"Checked evidence graph invalid: {error}"]
            catalog["requirements"] = {}
    return catalog


def validate_fit_assessment(value: Any, catalog: dict) -> dict:
    value = value if isinstance(value, dict) else {}
    requirements = catalog.get("requirements", {})
    evidence = catalog.get("vendor_evidence", {})
    issues, matches, projects = list(catalog.get("validation_issues", [])), [], []
    component_mode = catalog.get("assessment_mode") == "checked_component_graph" and not issues
    checked_projects = _checked_projects(catalog) if component_mode else None
    overrides = []
    seen = set()
    proposed_requirements = value.get("requirement_assessments", []) or []
    if not component_mode and not isinstance(proposed_requirements, list):
        issues.append("Requirement assessments must be an array")
        proposed_requirements = []
    checked_requirements = _checked_requirement_assessments(catalog) if component_mode else proposed_requirements
    if component_mode:
        overrides.extend(_record_overrides(proposed_requirements, checked_requirements, "requirement_id", ("match", "vendor_evidence_ids")))
    for row in checked_requirements:
        if not isinstance(row, dict):
            issues.append("Invalid requirement assessment")
            continue
        rid = row.get("requirement_id")
        status = row.get("match")
        ids = _strings(row.get("vendor_evidence_ids"))
        if rid not in requirements or rid in seen or status not in {"direct", "transferable", "none", "unknown"} or not row.get("reason"):
            issues.append("Invalid or duplicate requirement reference/classification")
            continue
        seen.add(rid)
        if status in {"direct", "transferable"} and (not ids or any(eid not in evidence for eid in ids)):
            issues.append(f"Unsupported vendor references for {rid}")
            status, ids = "unknown", []
        if status in {"direct", "transferable"} and any(evidence[eid].get("understanding_credit", {}).get("allowed") is False for eid in ids):
            issues.append(f"{rid} contradicts the checked evidence credit boundary")
            status, ids = "unknown", []
        if component_mode and status in {"direct", "transferable"}:
            if any(not any(e["credit_fraction"] > 0 for e in evidence[eid]["understanding_credit"]["by_requirement"].get(rid, [])) for eid in ids):
                issues.append(f"{rid} borrows checked credit from another task")
                status, ids = "unknown", []
        if status in {"none", "unknown"}:
            ids = []
        match = {**row, "match": status, "vendor_evidence_ids": ids}
        if component_mode and ids:
            limits = [e for eid in ids for e in evidence[eid]["understanding_credit"]["by_requirement"].get(rid, []) if e["credit_fraction"] > 0]
            best = max(limits, key=lambda e: e["credit_fraction"])
            match.update(coverage=best["coverage"], credit_fraction=best["credit_fraction"], reason=best["reason"],
                         component_assessments=deepcopy(limits))
        matches.append(match)
    if seen != set(requirements):
        issues.append("Requirement assessment incomplete")
    seen_projects = set()
    proposed_projects = value.get("past_performance_assessments", []) or []
    if not component_mode and not isinstance(proposed_projects, list):
        issues.append("Past-performance assessments must be an array")
        proposed_projects = []
    if component_mode:
        overrides.extend(_record_overrides(proposed_projects, checked_projects, "project_id", ("relevance", "requirement_ids")))
    for row in checked_projects if component_mode else proposed_projects:
        if not isinstance(row, dict):
            issues.append("Invalid past-performance assessment")
            continue
        pid = row.get("project_id")
        relevance = row.get("relevance")
        rids = _strings(row.get("requirement_ids"))
        if pid not in evidence or evidence[pid]["kind"] != "past_performance" or pid in seen_projects:
            issues.append("Invalid or duplicate project reference")
            continue
        seen_projects.add(pid)
        if relevance not in {"direct", "transferable", "unrelated", "unknown"} or not row.get("reason"):
            issues.append(f"Invalid relevance for {pid}")
            relevance, rids = "unknown", []
        if relevance in {"direct", "transferable"} and (not rids or any(rid not in requirements for rid in rids)):
            issues.append(f"Unsupported requirement references for {pid}")
            relevance, rids = "unknown", []
        if relevance in {"direct", "transferable"} and evidence[pid].get("understanding_credit", {}).get("allowed") is False:
            issues.append(f"{pid} contradicts the checked evidence credit boundary")
            relevance, rids = "unknown", []
        if relevance in {"unrelated", "unknown"}:
            rids = []
        projects.append({**row, "relevance": relevance, "requirement_ids": rids})
    if seen_projects != {key for key, row in evidence.items() if row["kind"] == "past_performance"}:
        issues.append("Past-performance assessment incomplete")
    by_requirement = {row["requirement_id"]: row for row in matches}
    for project in projects:
        for rid in project["requirement_ids"]:
            if by_requirement.get(rid, {}).get("match") not in {"direct", "transferable"}:
                issues.append(f"{project['project_id']} positive work conflicts with the {rid} assessment")
    status = str(value.get("status") or "unknown")
    positive = [row for row in matches if row["match"] in {"direct", "transferable"}]
    if component_mode:
        status = ("fit" if matches and len(positive) == len(matches) and all(r.get("coverage") == "complete" for r in positive)
                  else "adjacent" if positive else "no_fit" if matches and all(r["match"] == "none" for r in matches) else "unknown")
        if status != value.get("status"):
            overrides.append({"field": "status", "proposed": value.get("status"), "retained": status})
    if status not in {"fit", "adjacent", "no_fit", "unknown"}:
        status = "unknown"
    if not evidence or not requirements or issues:
        status = "unknown"
    if status in {"fit", "adjacent"} and not positive:
        status = "unknown"
        issues.append("Positive verdict without supported workshare")
    if status == "no_fit" and (positive or any(row["match"] == "unknown" for row in matches)):
        status = "unknown"
        issues.append("No-fit verdict contradicted or incomplete")
    denominator = max(1, len(requirements))
    capability_fraction = sum(row.get("credit_fraction", 0) if component_mode else
                              {"direct": 1, "transferable": .5}.get(row["match"], 0) for row in matches) / denominator
    capability = _component_score(capability_fraction) if component_mode else round(15 * capability_fraction)
    coverage = {rid: 0.0 for rid in requirements}
    for row in projects:
        for rid in row["requirement_ids"]:
            credit = (row["coverage_by_requirement"][rid]["credit_fraction"] if component_mode else
                      {"direct": 1, "transferable": .4}.get(row["relevance"], 0))
            coverage[rid] = max(coverage[rid], credit)
    performance_fraction = sum(coverage.values()) / denominator
    performance = _component_score(performance_fraction) if component_mode else round(15 * performance_fraction)
    boundaries = []
    if component_mode:
        for eid, entry in evidence.items():
            for rid, edges in entry["understanding_credit"]["by_requirement"].items():
                components = requirements[rid]["components"]
                for edge in edges:
                    if edge["fit_label"] not in {"Partial Fit", "Supported Fit"}:
                        continue
                    supported = [f"{components[int(k[1:])]['text']} ({edge['component_findings'][k]['status']})"
                                 for k in edge["met_components"] + edge["partial_components"]]
                    missing = [components[int(k[1:])]["text"] for k in edge["missing_components"]]
                    boundaries.append(f"{eid} / {rid} / {edge['claim_id']}: {edge['fit_label']}. "
                                      + "Supported in this claim: " + "; ".join(supported) + ". "
                                      + ("Not established in this claim: " + "; ".join(missing) + "." if missing else ""))
    complete_count = sum(r.get("coverage") == "complete" for r in matches)
    partial_count = sum(r.get("fit_label") == "Partial Fit" for r in matches)
    summary = (f"Checked input evidence: {complete_count} requirement(s) fully covered, {partial_count} partially supported; "
               "remaining tasks are unrelated or unproven. Component details retain the limits; reported work is not independently verified."
               if component_mode else str(value.get("summary") or "Vendor fit is unverified; obtain profile evidence before recommending pursuit."))
    gaps = _strings(value.get("critical_gaps"))
    if component_mode:
        gaps = []
        for match in matches:
            rid = match["requirement_id"]
            if match.get("coverage") == "complete":
                continue
            if match["match"] == "none":
                gaps.append(f"{rid}: No supplied work matches this requirement: {requirements[rid]['text']}")
            elif match["match"] == "unknown":
                gaps.append(f"{rid}: Performed-work coverage is not established for: {requirements[rid]['text']}")
            else:
                best = max(match["component_assessments"], key=lambda e: e["credit_fraction"])
                incomplete = best["missing_components"] + best["partial_components"]
                labels = [requirements[rid]["components"][int(key[1:])]["text"] for key in incomplete]
                gaps.append(f"{rid} / {best['claim_id']}: Partial Fit. Unestablished or incomplete components in this claim: "
                            + "; ".join(labels) + ".")
    return {
        "status": status, "summary": ("Fit assessment failed evidence validation; no positive fit or past-performance credit is released."
                                       if issues else summary),
        "requirement_assessments": matches, "past_performance_assessments": projects,
        "critical_gaps": gaps, "validation_issues": issues,
        "capability_score": capability if status != "unknown" else 0,
        "past_performance_score": performance if status != "unknown" else 0,
        "supported_workshare": [row["requirement_id"] for row in positive] if status != "unknown" else [],
        "catalog": catalog, "score_basis": "Requirement coverage, not inventory count; unknown is provisional, not demonstrated inability.",
        "component_coverage_notes": boundaries, "checked_decision_overrides": overrides,
        "component_credit_policy": ("Equal-component ranking proxy: matched=1, partial=.5, transferable=.4, unproved=0; pricing/context excluded. Separate claims are not combined into full coverage. Nonzero partial totals stay between 1 and 14 of 15, never round to full credit."
                                    if component_mode else "Legacy coverage proxy; no model-supplied numeric weights are accepted."),
    }


def validate_company_strategy_rows(rows: Any, fit: dict, *, require_project: bool = False) -> list[dict]:
    if fit.get("status") not in {"fit", "adjacent"}:
        return []
    catalog = fit.get("catalog", {})
    requirements = catalog.get("requirements", {})
    evidence = catalog.get("vendor_evidence", {})
    positive = {row["requirement_id"]: set(row["vendor_evidence_ids"]) for row in fit.get("requirement_assessments", []) if row.get("match") in {"direct", "transferable"}}
    projects = {row["project_id"]: set(row["requirement_ids"]) for row in fit.get("past_performance_assessments", []) if row.get("relevance") in {"direct", "transferable"}}
    output, seen = [], set()
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        text = str(row.get("text") or "").strip()
        rids, eids = _strings(row.get("requirement_ids")), _strings(row.get("vendor_evidence_ids"))
        if not text or text.lower() in seen or not rids or not eids or any(r not in positive for r in rids) or any(e not in evidence for e in eids):
            continue
        if not all(any(e in positive[r] or r in projects.get(e, set()) for r in rids) for e in eids):
            continue
        if not all(any(e in positive[r] or r in projects.get(e, set()) for e in eids) for r in rids):
            continue
        if require_project and not any(set(rids) & projects.get(e, set()) for e in eids):
            continue
        seen.add(text.lower())
        anchors = [requirements[r]["anchors"][0] for r in rids]
        vendor_refs = [f"{eid}: {evidence[eid]['text']}" for eid in eids]
        output.append({**row, "text": text, "evidence_anchor": " | ".join(anchors) + " | Profile-reported proof: " + "; ".join(vendor_refs), "requirement_ids": rids, "vendor_evidence_ids": eids})
    return output[:3]


def apply_validated_fit(capability_fit: dict, fit: dict) -> dict:
    """Replace lexical claims, including prose, rather than only adjusting a score."""
    catalog = fit.get("catalog", {})
    evidence = catalog.get("vendor_evidence", {})
    positive = fit.get("requirement_assessments", []) if fit.get("status") in {"fit", "adjacent"} else []
    ids = list(dict.fromkeys(eid for row in positive if row.get("match") in {"direct", "transferable"} for eid in row.get("vendor_evidence_ids", [])))
    projects = [row for row in fit.get("past_performance_assessments", []) if row.get("relevance") in {"direct", "transferable"}] if positive else []
    proof = [f"{eid} (profile-reported): {evidence[eid]['text']}" for eid in ids if eid in evidence]
    past_performance_hits = [f"{row['project_id']}: {evidence[row['project_id']]['text']}" for row in projects]
    if catalog.get("assessment_mode") == "checked_component_graph":
        proof = list(dict.fromkeys(f"{eid} / {r['requirement_id']} / {edge['claim_id']} (reported): {edge['matched_work']}; coverage {edge['coverage']}."
                for r in positive for eid in r.get("vendor_evidence_ids", [])
                for edge in evidence[eid]["understanding_credit"]["by_requirement"].get(r["requirement_id"], []) if edge["credit_fraction"] > 0))
        past_performance_hits = [f"{row['project_id']}: {row['reason']}" for row in projects]
    gaps = [*capability_fit.get("eligibility_gaps", []), *fit.get("critical_gaps", []), *fit.get("validation_issues", [])]
    boundaries = fit.get("component_coverage_notes", [])
    gaps.extend(note for note in boundaries if "Not established in this claim:" in note)
    return {**capability_fit, "vendor_fit_assessment": fit,
            "capability_hits": proof, "past_performance_hits": past_performance_hits,
            "proof_points": proof, "fit_narrative_positive_hits": proof,
            "fit_weighting_signals": [fit["summary"]], "fit_weighting_cautions": gaps,
            "fit_weighting_summary": fit["summary"], "missing_proof": gaps,
            "credibility_requirements": gaps or ["Validate the profile-reported references before proposal use."],
            "component_coverage_notes": boundaries,
            "customer_alignment_adjustment": 0, "requirement_fit_adjustment": 0, "past_performance_adjustment": 0}

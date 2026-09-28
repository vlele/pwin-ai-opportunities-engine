"""Adapt saved semantic fixtures to the selection wire contract, never production.

Existing fixtures still describe exact evidence. This helper makes their stub
provider choose the smallest available evidence-line range and leaves every
semantic verdict and expected routing assertion unchanged.
"""
from copy import deepcopy
import re


def fixture_category(part):
    """Explicit defaults for old synthetic mechanics fixtures, NOT model grading."""
    return {"category": {"pricing": "contract_terms", "context": "contract_terms",
                         "qualification": "compliance_certification"}.get(part["kind"], "technical_capability"),
            "applicability": "not_prime_contractor" if part["kind"] == "context" else "prime_contractor",
            "routing_reason": "Synthetic fixture declares this component's category and actor."}


def selection_provider(provider):
    def wrapped(**kwargs):
        payload = kwargs["user_payload"]
        if payload.get("parent_scoped_decomposition"):
            view = deepcopy(payload)
            for row in view["requirements"].values():
                row["evidence"] = list(row["evidence_catalog"].values())
            result = provider(**{**kwargs, "user_payload": view})
            if result is None:
                return None
            result = deepcopy(result)
            for key, row in result["requirements"].items():
                row["status"] = "complete"
                catalog = payload["requirements"][key]["evidence_catalog"]
                for part in row["components"]:
                    for name, value in fixture_category(part).items():
                        part.setdefault(name, value)
                    ids = []
                    for anchor in part.pop("evidence"):
                        matches = [eid for eid, parent in catalog.items()
                                   if parent["ref"] == anchor["ref"] and anchor["quote"] in parent["quote"]]
                        if not matches:
                            raise AssertionError("Fixture component has no parent evidence; do not widen scope.")
                        ids.append(min(matches, key=lambda eid: len(catalog[eid]["quote"])))
                    part["evidence_ids"] = list(dict.fromkeys(ids))
            return result
        if "EVIDENCE TRANSPORT" not in kwargs["system_prompt"]:
            return provider(**kwargs)
        view, units = deepcopy(payload), {}
        for ref, span in view.get("spans", {}).items():
            parts = re.findall(r"^L\d+\| (.*)$", span["text"], re.M)
            units[ref] = parts
            span["text"] = "\n".join(parts)
        result = provider(**{**kwargs, "user_payload": view})
        if result is not None and payload.get("inventory_mode"):
            result = inventory_fragment(result, view)
        if result is not None and "source_coverage" in payload:
            requirement_schema = kwargs["response_schema"]["schema"]["properties"]["requirements"]["items"]
            if "components" not in requirement_schema["properties"]:
                result = deepcopy(result)
                for row in result.get("requirements", []):
                    row.pop("components", None)
                    row.pop("logic", None)
                    if "supporting_context" in requirement_schema["properties"]:
                        row["supporting_context"] = row.pop("evidence")

        def convert(value):
            if isinstance(value, list):
                return [convert(v) for v in value]
            if not isinstance(value, dict):
                return value
            if set(value) == {"ref", "quote"}:
                if "selectable_evidence" in payload:
                    choices = payload["selectable_evidence"]
                    key = next(k for k, a in choices.items() if a == value)
                    return {"evidence_id": key}
                ref, quote = value["ref"], value["quote"]
                text = "\n".join(units[ref])
                # Only test stubs use this conversion; runtime never searches or
                # normalizes a model-produced quotation.
                normalized, positions = "", []
                for match in re.finditer(r"\S+", text):
                    if normalized:
                        normalized += " "
                        positions.append(match.start())
                    normalized += match.group()
                    positions.extend(range(match.start(), match.end()))
                q = " ".join(quote.split())
                start = normalized.find(q)
                if start < 0:
                    raise AssertionError(f"Saved fixture quote not in source: {value}")
                lo, hi = positions[start], positions[start + len(q) - 1]
                return {"start": {"ref": ref, "line": text[:lo].count("\n") + 1},
                        "end": {"ref": ref, "line": text[:hi].count("\n") + 1}}
            return {k: convert(v) for k, v in value.items()}
        return convert(result)
    return wrapped


def inventory_fragment(result, payload):
    """Adapt explicit old fixture rows to new role-isolated batch ownership.

    This helper never supplies a semantic verdict. Dedicated handoff tests exercise
    omissions and bad links without this legacy fixture adapter.
    """
    result = deepcopy(result)
    package = payload["inventory_mode"] == "package"
    maps = {}
    for key in ("requirements", "claims", "quoted_vendor_context"):
        rows = result.get(key, [])
        keep = []
        mapping = {}
        for i, row in enumerate(rows):
            if (key == "claims") == package:
                continue
            if not {a["ref"] for a in row["evidence"]}.issubset(payload["spans"]):
                continue
            mapping[i] = len(keep)
            keep.append(row)
        maps[key] = mapping
        result[key] = keep
    questions = []
    for q in result["questions"]:
        if any(i not in maps[k] for k in ("requirements", "claims") for i in q[k]):
            continue
        questions.append({**q, **{k: [maps[k][i] for i in q[k]] for k in ("requirements", "claims")}})
    result["questions"] = questions
    for r in result["requirements"]:
        r["supersedes"] = [maps["requirements"][i] for i in r["supersedes"]]
    if package:
        for key in ("requirements", "quoted_vendor_context"):
            for row in result[key]:
                row["originating_fact_ids"] = []
        for fid, fact in payload["fact_ledger"].items():
            links = [{"array": key, "index": i} for key in ("requirements", "quoted_vendor_context")
                     for i, r in enumerate(result[key]) if {a["ref"] for a in r["evidence"]} & set(fact["refs"])]
            if not links:
                raise AssertionError("Legacy fixture lacks a record for the supplied ledger fact.")
            for link in links:
                result[link["array"]][link["index"]]["originating_fact_ids"].append(fid)
    else:
        result["vendor_coverage"] = {ref: {"claims": [i for i, c in enumerate(result["claims"])
            if ref in {a["ref"] for a in c["evidence"]}], "reason": "Explicit saved fixture assertion mapping."}
            for ref in payload["spans"]}
    return result

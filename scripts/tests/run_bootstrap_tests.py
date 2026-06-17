from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from bootstrap.bootstrap_workspace import seed_workspace, seed_workspace_from_govtribe  # type: ignore
from common.paths import load_json  # type: ignore


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


class FakeGovTribeBootstrapProvider:
    def __init__(
        self,
        *,
        status: str = "ok",
        status_by_lookup: dict[str, str] | None = None,
        vendor_record: dict | None = None,
        vendor_record_by_lookup: dict[str, dict] | None = None,
    ) -> None:
        self.status = status
        self.status_by_lookup = status_by_lookup or {}
        self.vendor_record = vendor_record or {}
        self.vendor_record_by_lookup = vendor_record_by_lookup or {}
        self.lookups: list[str] = []

    def resolve_vendor_profile(self, *, lookup: str, limit: int = 5) -> dict:
        self.lookups.append(lookup)
        status = self.status_by_lookup.get(lookup, self.status)
        if status != "ok":
            return {
                "status": status,
                "matched": False,
                "notes": [f"fake {status}"],
                "vendor_record": {},
            }
        vendor_record = {
            "source_id": "govtribe_mcp_commercial_intel",
            "source_name": "GovTribe MCP Commercial Intelligence",
            "external_record_id": "vendor-123",
            "source_url": "https://govtribe.com/vendors/demogov-services-demo1",
            "govtribe_id": "vendor-123",
            "govtribe_url": "https://govtribe.com/vendors/demogov-services-demo1",
            "name": "DemoGov Services, LLC",
            "dba": "",
            "division": "",
            "uei": "DEMOUEI12345",
            "parent_or_child": "Child",
            "parent_vendor": {
                "name": "DemoGov Holdings Inc.",
                "uei": "DEMOPARENT123",
                "govtribe_id": "parent-123",
                "govtribe_url": "https://govtribe.com/vendors/demogov-holdings",
            },
            "vendor_hierarchy": {
                "parent_or_child": "Child",
                "parent": {
                    "name": "DemoGov Holdings Inc.",
                    "uei": "DEMOPARENT123",
                    "govtribe_id": "parent-123",
                    "govtribe_url": "https://govtribe.com/vendors/demogov-holdings",
                },
            },
            "summary": (
                "DemoGov provides software engineering, cloud services, cybersecurity, data analytics, "
                "and program management support to federal agencies.\n"
                "DemoGov has secured positions on GSA MAS and the One Acquisition Solution for "
                "Integrated Services Small Business (OASIS SB) IDIQ."
            ),
            "location": "Vienna, VA, USA",
            "naics": ["Web Search Portals and All Other Information Services"],
            "certifications": [
                "Self Certified Small Disadvantaged Business",
                "For Profit Organization",
                "Business or Organization",
                "Limited Liability Company",
            ],
            "contract_vehicles": ["True", "GSA MAS"],
            "expired_contract_vehicles": ["One Acquisition Solution for Integrated Services - Small Business (OASIS SB)"],
            "buyers": ["Department of Veterans Affairs"],
            "places_of_performance": ["Vienna, VA 22182, USA", "Washington, DC 20001, USA"],
            "preferred_states": ["VA", "DC"],
            "set_asides": ["No Set-Aside Used", "Total Small Business", "Competitive 8(a)"],
            "contract_types": ["Delivery Order", "Definitive Contract"],
            "pricing_types": ["Firm Fixed Price", "Time and Materials"],
            "prime_or_sub": ["prime"],
            "psc_codes": ["D399"],
            "service_contract_roles": ["prime", "sub"],
            "contract_vehicle_subcategories": ["Multiple Award Schedule: 54151S"],
            "teaming_preferences": ["Historical sub-award prime: Large Prime Integrator"],
            "govtribe_award_profile": {
                "top_naics": [
                    {
                        "code": "541512",
                        "label": "Computer Systems Design Services",
                        "doc_count": 22,
                        "dollars_obligated": 25000000,
                    },
                    {
                        "code": "541519",
                        "label": "Other Computer Related Services",
                        "doc_count": 8,
                        "dollars_obligated": 5000000,
                    },
                ],
                "top_locations": [
                    {"name": "Vienna, VA 22182, USA", "state": "VA", "doc_count": 12, "dollars_obligated": 22000000},
                    {"name": "Washington, DC 20001, USA", "state": "DC", "doc_count": 3, "dollars_obligated": 3000000},
                ],
                "top_set_asides": [
                    {"name": "No Set-Aside Used", "doc_count": 15, "dollars_obligated": 20000000},
                    {"name": "Total Small Business", "doc_count": 4, "dollars_obligated": 4000000},
                ],
                "top_contract_types": [
                    {"name": "Delivery Order", "doc_count": 17, "dollars_obligated": 21000000},
                ],
                "top_pricing_types": [
                    {"name": "Firm Fixed Price", "doc_count": 14, "dollars_obligated": 18000000},
                ],
                "value_stats": {
                    "dollars_obligated": {"count": 24, "min": 1000, "max": 10000000, "avg": 1250000, "sum": 30000000},
                    "ceiling_value": {"count": 10, "min": 50000, "max": 50000000, "avg": 5000000, "sum": 50000000},
                    "base_and_exercised_options_value": {"count": 12, "min": 25000, "max": 12000000, "avg": 2000000, "sum": 24000000},
                },
            },
            "govtribe_service_contract_inventory_profile": {
                "value_stats": {
                    "derived_hourly_rate": {"count": 9, "min": 82.5, "max": 156.75, "avg": 118.4},
                    "total_dollar_amount_invoiced": {"count": 9, "sum": 2450000, "avg": 272222.22},
                    "hours_invoiced": {"count": 9, "sum": 20692, "avg": 2299.1},
                },
                "top_roles": [{"name": "prime", "doc_count": 7}, {"name": "sub", "doc_count": 2}],
                "top_naics": [{"code": "541513", "label": "Computer Facilities Management Services", "doc_count": 3}],
                "top_psc": [{"code": "D399", "label": "IT and Telecom Other IT and Telecommunications", "doc_count": 5}],
                "top_states": [{"name": "MD", "doc_count": 4}],
            },
            "govtribe_vehicle_subcategory_profile": {
                "subcategories": [
                    {
                        "name": "Information Technology Professional Services",
                        "short_name": "54151S",
                        "display_name": "Multiple Award Schedule: 54151S",
                        "vehicle": "Multiple Award Schedule",
                    }
                ]
            },
            "govtribe_sub_award_profile": {
                "top_prime_contractors": [{"name": "Large Prime Integrator"}],
                "sub_award_signals": [
                    "Cloud migration support subaward - Large Prime Integrator - DemoGov Services, LLC - 2024-02-01"
                ],
            },
            "award_signals": ["VA Modernization Support - VA-1 - Department of Veterans Affairs"],
            "keywords": [
                "True",
                "For Profit Organization",
                "Web Search Portals and All Other Information Services",
                "cybersecurity",
                "GSA MAS",
                "Department of Veterans Affairs",
            ],
            "raw_record": {},
        }
        vendor_record.update(self.vendor_record)
        vendor_record.update(self.vendor_record_by_lookup.get(lookup, {}))
        return {
            "status": "ok",
            "matched": True,
            "matched_by": "GovTribe vendor search",
            "external_record_id": vendor_record.get("external_record_id", ""),
            "source_url": vendor_record.get("source_url", ""),
            "vendor_record": vendor_record,
            "notes": ["GovTribe MCP tools used: Search_Vendors"],
            "tool_name": "Search_Vendors",
        }


def main() -> int:
    bundle_root = Path(__file__).resolve().parents[2]
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        site = root / "site"
        workspace = root / "workspace"

        write(
            site / "index.html",
            """
            <html>
              <head>
                <title>Acme Federal | Mission Data and Cloud Delivery</title>
                <meta name="description" content="Acme Federal delivers cloud modernization, data analytics, and program management support for federal health buyers." />
              </head>
              <body>
                <h1>Mission Data and Cloud Delivery</h1>
                <p>We help federal agencies modernize case management, analytics, and reporting workflows.</p>
                <a href="about.html">About</a>
                <a href="capabilities.html">Capabilities</a>
              </body>
            </html>
            """,
        )
        write(
            site / "about.html",
            """
            <html>
              <body>
                <h2>Public Health and Veteran Services</h2>
                <p>Our team supports public health, veterans benefits, and data-driven operations for civilian agencies.</p>
              </body>
            </html>
            """,
        )
        write(
            site / "capabilities.html",
            """
            <html>
              <body>
                <h2>Cloud Modernization</h2>
                <h2>Data Analytics</h2>
                <h2>Program Management</h2>
                <p>We deliver software development, integration, analytics, and modernization support.</p>
              </body>
            </html>
            """,
        )

        result = seed_workspace(
            bundle_root=bundle_root,
            workspace=workspace,
            company_url=(site / "index.html").resolve().as_uri(),
            user_naics=["541512"],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=FakeGovTribeBootstrapProvider(status="not_configured"),
        )

        vendor_profile = load_json(workspace / "procurement" / "vendor-profile.json", default={})
        preferences = load_json(workspace / "procurement" / "preferences.json", default={})
        starter_profile = (workspace / "procurement" / "STARTER_PROFILE.md").read_text(encoding="utf-8")
        memory = (workspace / "MEMORY.md").read_text(encoding="utf-8")

        assert result["status"] == "OK", result
        assert vendor_profile["company"]["name"] == "Acme Federal", vendor_profile["company"]
        assert "cloud modernization" in json.dumps(vendor_profile).lower(), vendor_profile
        assert "541512" in vendor_profile["naics"]["confirmed"], vendor_profile["naics"]
        assert "grants" in preferences["hard_filters"]["exclude_opportunity_classes"], preferences["hard_filters"]
        assert "Acme Federal" in starter_profile, starter_profile
        assert "Bootstrap snapshot" in memory, memory

        nav_site = root / "nav-site"
        nav_workspace = root / "nav-workspace"
        write(
            nav_site / "index.html",
            """
            <html>
              <head>
                <title>DemoGov Services, LLC | About Us</title>
              </head>
              <body>
                <h1>About Us</h1>
                <h2>Logistics</h2>
                <h2>Digital Services</h2>
                <h2>Cybersecurity</h2>
                <p>We help federal agencies protect mission systems and operate secure technology programs.</p>
              </body>
            </html>
            """,
        )

        nav_result = seed_workspace(
            bundle_root=bundle_root,
            workspace=nav_workspace,
            company_url=(nav_site / "index.html").resolve().as_uri(),
            user_naics=["519290"],
            naics_status="confirmed",
            explicit_name="DemoGov Services, LLC",
            explicit_summary="DemoGov supports federal cybersecurity programs.",
            provider=FakeGovTribeBootstrapProvider(status="not_configured"),
        )

        nav_vendor_profile = load_json(nav_workspace / "procurement" / "vendor-profile.json", default={})
        nav_preferences = load_json(nav_workspace / "procurement" / "preferences.json", default={})
        nav_starter_profile = (nav_workspace / "procurement" / "STARTER_PROFILE.md").read_text(encoding="utf-8")
        nav_memory = (nav_workspace / "MEMORY.md").read_text(encoding="utf-8")
        nav_payload = json.dumps(
            {
                "core_competencies": nav_vendor_profile.get("core_competencies", []),
                "keywords": nav_vendor_profile.get("other_taxonomy_tags", {}).get("keywords", []),
                "positive_keywords": nav_preferences.get("soft_preferences", {}).get("positive_keywords", []),
                "starter_profile": nav_starter_profile,
                "memory": nav_memory,
            }
        ).lower()

        assert nav_result["status"] == "OK", nav_result
        assert "cybersecurity" in nav_vendor_profile["core_competencies"], nav_vendor_profile
        assert "cybersecurity" in nav_preferences["soft_preferences"]["positive_keywords"], nav_preferences
        for low_signal_term in ("about us", "logistics", "digital services"):
            assert low_signal_term not in nav_payload, nav_payload

        unavailable_workspace = root / "website-govtribe-unavailable"
        unavailable_provider = FakeGovTribeBootstrapProvider(status="not_configured")
        unavailable_result = seed_workspace(
            bundle_root=bundle_root,
            workspace=unavailable_workspace,
            company_url=(site / "index.html").resolve().as_uri(),
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=unavailable_provider,
        )
        unavailable_vendor_profile = load_json(unavailable_workspace / "procurement" / "vendor-profile.json", default={})
        assert unavailable_result["status"] == "OK", unavailable_result
        assert unavailable_result["bootstrap_source"] == "website", unavailable_result
        assert unavailable_result["govtribe_status"] == "GOVTRIBE_NOT_CONFIGURED", unavailable_result
        assert unavailable_provider.lookups == ["Acme Federal"], unavailable_provider.lookups
        assert unavailable_vendor_profile["bootstrap"]["method"] == "company_url_bootstrap_script_v1", unavailable_vendor_profile

        hybrid_site = root / "hybrid-site"
        hybrid_workspace = root / "hybrid-workspace"
        write(
            hybrid_site / "index.html",
            """
            <html>
              <head>
                <title>DemoGov Services | Federal Technology Delivery</title>
                <meta name="description" content="DemoGov Services supports federal software engineering, cloud modernization, and cybersecurity programs." />
              </head>
              <body>
                <h1>Federal Technology Delivery</h1>
                <p>We help federal agencies modernize secure mission applications and data platforms.</p>
              </body>
            </html>
            """,
        )
        hybrid_provider = FakeGovTribeBootstrapProvider()
        hybrid_result = seed_workspace(
            bundle_root=bundle_root,
            workspace=hybrid_workspace,
            company_url=(hybrid_site / "index.html").resolve().as_uri(),
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=hybrid_provider,
        )
        hybrid_vendor_profile = load_json(hybrid_workspace / "procurement" / "vendor-profile.json", default={})
        hybrid_facts = hybrid_vendor_profile["provenance"]["facts"]
        hybrid_url = (hybrid_site / "index.html").resolve().as_uri()
        assert hybrid_result["status"] == "OK", hybrid_result
        assert hybrid_result["bootstrap_source"] == "govtribe", hybrid_result
        assert hybrid_result["govtribe_inferred_lookup"] == "DemoGov Services", hybrid_result
        assert hybrid_result["govtribe_match_confidence"] == "near_exact_name", hybrid_result
        assert hybrid_provider.lookups == ["DemoGov Services"], hybrid_provider.lookups
        assert hybrid_vendor_profile["bootstrap"]["method"] == "govtribe_vendor_bootstrap_script_v1", hybrid_vendor_profile
        assert hybrid_vendor_profile["bootstrap"]["inputs"]["plain_language_summary"] == "", hybrid_vendor_profile
        assert hybrid_vendor_profile["company"]["name"] == "DemoGov Services", hybrid_vendor_profile["company"]
        assert hybrid_vendor_profile["company"]["website"] == hybrid_url, hybrid_vendor_profile["company"]
        assert hybrid_vendor_profile["company"]["summary"].startswith("DemoGov Services supports federal software"), hybrid_vendor_profile["company"]
        assert hybrid_vendor_profile["company"]["uei"] == "DEMOUEI12345", hybrid_vendor_profile["company"]
        assert any(
            item.get("field") == "company.website"
            and item.get("source") == hybrid_url
            and item.get("provenance") == "user_confirmed"
            for item in hybrid_facts
        ), hybrid_facts
        assert any(
            item.get("field") == "company.name"
            and item.get("source") == hybrid_url
            and item.get("provenance") == "website_inferred"
            for item in hybrid_facts
        ), hybrid_facts
        assert any(
            item.get("field") == "company.summary"
            and item.get("source") == hybrid_url
            and item.get("provenance") == "website_inferred"
            for item in hybrid_facts
        ), hybrid_facts
        assert not any(
            item.get("field") in {"company.name", "company.summary"}
            and item.get("provenance") == "govtribe_subscription_derived"
            for item in hybrid_facts
        ), hybrid_facts
        assert any(
            item.get("field") == "company.uei" and item.get("provenance") == "govtribe_subscription_derived"
            for item in hybrid_facts
        ), hybrid_facts

        no_match_workspace = root / "website-govtribe-no-match"
        no_match_provider = FakeGovTribeBootstrapProvider(status="no_match")
        no_match_result = seed_workspace(
            bundle_root=bundle_root,
            workspace=no_match_workspace,
            company_url=(hybrid_site / "index.html").resolve().as_uri(),
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=no_match_provider,
        )
        no_match_vendor_profile = load_json(no_match_workspace / "procurement" / "vendor-profile.json", default={})
        assert no_match_result["status"] == "OK", no_match_result
        assert no_match_result["bootstrap_source"] == "website", no_match_result
        assert no_match_result["govtribe_status"] == "GOVTRIBE_NO_MATCH", no_match_result
        assert no_match_provider.lookups == ["DemoGov Services"], no_match_provider.lookups
        assert no_match_vendor_profile["bootstrap"]["method"] == "company_url_bootstrap_script_v1", no_match_vendor_profile

        ais_site = root / "ais-site"
        write(
            ais_site / "index.html",
            """
            <html>
              <head>
                <title>AFA | Digital Services</title>
                <meta name="description" content="AFA delivers secure digital services for public sector agencies." />
              </head>
              <body><h1>Digital Services</h1></body>
            </html>
            """,
        )
        ais_record = {
            "external_record_id": "vendor-ais",
            "source_url": "https://govtribe.com/vendors/acme-federal-analytics-demo1",
            "govtribe_id": "vendor-ais",
            "govtribe_url": "https://govtribe.com/vendors/acme-federal-analytics-demo1",
            "name": "Acme Federal Analytics",
            "uei": "ACMEUEI12345",
            "parent_vendor": {},
            "vendor_hierarchy": {},
        }
        ambiguous_workspace = root / "ambiguous-ais-workspace"
        ambiguous_provider = FakeGovTribeBootstrapProvider(vendor_record=ais_record)
        ambiguous_result = seed_workspace(
            bundle_root=bundle_root,
            workspace=ambiguous_workspace,
            company_url=(ais_site / "index.html").resolve().as_uri(),
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=ambiguous_provider,
        )
        ambiguous_vendor_profile = load_json(ambiguous_workspace / "procurement" / "vendor-profile.json", default={})
        assert ambiguous_result["status"] == "OK", ambiguous_result
        assert ambiguous_result["bootstrap_source"] == "website", ambiguous_result
        assert ambiguous_result["govtribe_status"] == "GOVTRIBE_AMBIGUOUS_MATCH", ambiguous_result
        assert ambiguous_result["govtribe_ambiguous_candidate"]["name"] == "Acme Federal Analytics", ambiguous_result
        assert ambiguous_provider.lookups == ["AFA"], ambiguous_provider.lookups
        assert ambiguous_vendor_profile["bootstrap"]["method"] == "company_url_bootstrap_script_v1", ambiguous_vendor_profile
        assert "uei" not in ambiguous_vendor_profile["company"], ambiguous_vendor_profile["company"]

        parenthetical_site = root / "parenthetical-site"
        parenthetical_workspace = root / "parenthetical-workspace"
        write(
            parenthetical_site / "index.html",
            """
            <html>
              <head>
                <title>AFA (Acme Federal Analytics) | Digital Services</title>
                <meta name="description" content="Acme Federal Analytics delivers secure application modernization for federal agencies." />
              </head>
              <body><h1>Digital Services</h1></body>
            </html>
            """,
        )
        parenthetical_provider = FakeGovTribeBootstrapProvider(vendor_record=ais_record)
        parenthetical_result = seed_workspace(
            bundle_root=bundle_root,
            workspace=parenthetical_workspace,
            company_url=(parenthetical_site / "index.html").resolve().as_uri(),
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=parenthetical_provider,
        )
        parenthetical_vendor_profile = load_json(parenthetical_workspace / "procurement" / "vendor-profile.json", default={})
        assert parenthetical_result["status"] == "OK", parenthetical_result
        assert parenthetical_result["bootstrap_source"] == "govtribe", parenthetical_result
        assert parenthetical_result["govtribe_inferred_lookup"] == "Acme Federal Analytics", parenthetical_result
        assert parenthetical_provider.lookups == [
            "AFA (Acme Federal Analytics)",
            "Acme Federal Analytics",
        ], parenthetical_provider.lookups
        assert parenthetical_vendor_profile["company"]["name"] == "AFA (Acme Federal Analytics)", parenthetical_vendor_profile["company"]
        assert parenthetical_vendor_profile["company"]["website"] == (parenthetical_site / "index.html").resolve().as_uri(), parenthetical_vendor_profile["company"]
        assert parenthetical_vendor_profile["company"]["uei"] == "ACMEUEI12345", parenthetical_vendor_profile["company"]

        govtribe_workspace = root / "govtribe-workspace"
        fake_provider = FakeGovTribeBootstrapProvider()
        govtribe_result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=govtribe_workspace,
            govtribe_lookup="https://govtribe.com/vendors/demogov-services-demo1",
            company_url="",
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=fake_provider,
        )
        govtribe_vendor_profile = load_json(govtribe_workspace / "procurement" / "vendor-profile.json", default={})
        govtribe_preferences = load_json(govtribe_workspace / "procurement" / "preferences.json", default={})
        govtribe_registry = load_json(govtribe_workspace / "procurement" / "source-registry.json", default={})
        govtribe_starter = (govtribe_workspace / "procurement" / "STARTER_PROFILE.md").read_text(encoding="utf-8")
        govtribe_memory = (govtribe_workspace / "MEMORY.md").read_text(encoding="utf-8")
        govtribe_payload = json.dumps(govtribe_vendor_profile)

        assert govtribe_result["status"] == "OK", govtribe_result
        assert govtribe_result["bootstrap_source"] == "govtribe", govtribe_result
        assert fake_provider.lookups == ["https://govtribe.com/vendors/demogov-services-demo1"], fake_provider.lookups
        assert govtribe_vendor_profile["bootstrap"]["method"] == "govtribe_vendor_bootstrap_script_v1", govtribe_vendor_profile
        assert govtribe_vendor_profile["company"]["name"] == "DemoGov Services, LLC", govtribe_vendor_profile["company"]
        assert govtribe_vendor_profile["company"]["uei"] == "DEMOUEI12345", govtribe_vendor_profile["company"]
        assert govtribe_vendor_profile["company"]["govtribe_url"] == "https://govtribe.com/vendors/demogov-services-demo1", govtribe_vendor_profile["company"]
        assert govtribe_vendor_profile["company"]["parent"]["name"] == "DemoGov Holdings Inc.", govtribe_vendor_profile["company"]
        assert govtribe_vendor_profile["govtribe_vendor_hierarchy"]["parent_or_child"] == "Child", govtribe_vendor_profile
        assert "OASIS SB" not in govtribe_vendor_profile["company"]["summary"], govtribe_vendor_profile["company"]
        assert "541512" in govtribe_vendor_profile["naics"]["candidates"], govtribe_vendor_profile["naics"]
        assert "541519" in govtribe_vendor_profile["naics"]["candidates"], govtribe_vendor_profile["naics"]
        assert "541513" in govtribe_vendor_profile["naics"]["candidates"], govtribe_vendor_profile["naics"]
        assert "cybersecurity" in govtribe_vendor_profile["core_competencies"], govtribe_vendor_profile
        assert "cloud modernization" in govtribe_vendor_profile["core_competencies"], govtribe_vendor_profile
        assert "Self Certified Small Disadvantaged Business" in govtribe_vendor_profile["commercial_constraints"]["certifications"], govtribe_vendor_profile
        for generic_certification in ("For Profit Organization", "Business or Organization", "Limited Liability Company"):
            assert generic_certification not in govtribe_vendor_profile["commercial_constraints"]["certifications"], govtribe_vendor_profile
        assert "Self Certified Small Disadvantaged Business" not in govtribe_vendor_profile["core_competencies"], govtribe_vendor_profile
        assert "GSA MAS" in govtribe_vendor_profile["contract_vehicles"], govtribe_vendor_profile
        assert "True" not in govtribe_vendor_profile["contract_vehicles"], govtribe_vendor_profile
        assert "Department of Veterans Affairs" in govtribe_vendor_profile["buyers"]["notes"], govtribe_vendor_profile
        assert "Vienna, VA 22182, USA" in govtribe_vendor_profile["geography"]["place_of_performance"], govtribe_vendor_profile
        assert "VA" in govtribe_vendor_profile["geography"]["preferred_states"], govtribe_vendor_profile
        assert "Total Small Business" in govtribe_vendor_profile["commercial_constraints"]["set_aside_programs"], govtribe_vendor_profile
        assert "No Set-Aside Used" not in govtribe_vendor_profile["commercial_constraints"]["set_aside_programs"], govtribe_vendor_profile
        assert "prime" in govtribe_vendor_profile["commercial_constraints"]["prime_or_sub"], govtribe_vendor_profile
        assert "Historical sub-award prime: Large Prime Integrator" in govtribe_vendor_profile["commercial_constraints"]["teaming_preferences"], govtribe_vendor_profile
        assert govtribe_vendor_profile["commercial_constraints"]["min_award_value"] is None, govtribe_vendor_profile
        assert govtribe_vendor_profile["commercial_constraints"]["max_award_value"] is None, govtribe_vendor_profile
        observed_award_value_range = govtribe_vendor_profile["commercial_constraints"]["observed_award_value_range"]
        assert observed_award_value_range["constraint_status"] == "observed_history_not_user_constraint", observed_award_value_range
        assert observed_award_value_range["source_field"] == "govtribe_award_profile.value_stats", observed_award_value_range
        assert observed_award_value_range["dollars_obligated"]["min"] == 1000, observed_award_value_range
        assert observed_award_value_range["dollars_obligated"]["max"] == 10000000, observed_award_value_range
        assert observed_award_value_range["ceiling_value"]["max"] == 50000000, observed_award_value_range
        assert observed_award_value_range["base_and_exercised_options_value"]["min"] == 25000, observed_award_value_range
        assert "govtribe_award_profile" in govtribe_vendor_profile, govtribe_vendor_profile
        assert "govtribe_service_contract_inventory_profile" in govtribe_vendor_profile, govtribe_vendor_profile
        assert govtribe_vendor_profile["govtribe_service_contract_inventory_profile"]["value_stats"]["derived_hourly_rate"]["avg"] == 118.4, govtribe_vendor_profile
        assert "govtribe_vehicle_subcategory_profile" in govtribe_vendor_profile, govtribe_vendor_profile
        assert "govtribe_sub_award_profile" in govtribe_vendor_profile, govtribe_vendor_profile
        assert "D399" in govtribe_vendor_profile["other_taxonomy_tags"]["psc"], govtribe_vendor_profile
        assert "Multiple Award Schedule: 54151S" in govtribe_vendor_profile["contract_vehicle_subcategories"], govtribe_vendor_profile
        assert "541512" in govtribe_preferences["soft_preferences"]["preferred_naics"], govtribe_preferences
        assert "541519" in govtribe_preferences["soft_preferences"]["preferred_naics"], govtribe_preferences
        assert "541513" in govtribe_preferences["soft_preferences"]["preferred_naics"], govtribe_preferences
        assert "VA" in govtribe_preferences["soft_preferences"]["preferred_states"], govtribe_preferences
        assert "Total Small Business" in govtribe_preferences["soft_preferences"]["preferred_set_asides"], govtribe_preferences
        assert "Delivery Order" in govtribe_preferences["soft_preferences"]["preferred_contract_types"], govtribe_preferences
        assert "Firm Fixed Price" in govtribe_preferences["soft_preferences"]["preferred_pricing_types"], govtribe_preferences
        assert "D399" in govtribe_preferences["soft_preferences"]["preferred_psc"], govtribe_preferences
        assert "Multiple Award Schedule: 54151S" in govtribe_preferences["soft_preferences"]["preferred_contract_vehicle_subcategories"], govtribe_preferences
        assert "Historical sub-award prime: Large Prime Integrator" in govtribe_preferences["soft_preferences"]["preferred_teaming_partners"], govtribe_preferences
        noisy_payload = json.dumps(
            {
                "keywords": govtribe_vendor_profile.get("other_taxonomy_tags", {}).get("keywords", []),
                "certifications": govtribe_vendor_profile.get("commercial_constraints", {}).get("certifications", []),
                "positive_keywords": govtribe_preferences.get("soft_preferences", {}).get("positive_keywords", []),
                "preferred_contract_vehicles": govtribe_preferences.get("soft_preferences", {}).get("preferred_contract_vehicles", []),
                "preferred_contract_vehicle_subcategories": govtribe_preferences.get("soft_preferences", {}).get("preferred_contract_vehicle_subcategories", []),
                "starter": govtribe_starter,
            }
        )
        for bad_value in ("True", "For Profit Organization", "Business or Organization", "Limited Liability Company"):
            assert bad_value not in noisy_payload, noisy_payload
        assert "OASIS SB" not in noisy_payload, noisy_payload
        assert "541512 - Computer Systems Design Services" in govtribe_starter, govtribe_starter
        assert "GovTribe vendor: https://govtribe.com/vendors/demogov-services-demo1" in govtribe_starter, govtribe_starter
        assert "GSA MAS" in govtribe_starter, govtribe_starter
        assert "Vienna, VA 22182, USA" in govtribe_starter, govtribe_starter
        assert "Total Small Business" in govtribe_starter, govtribe_starter
        assert "Delivery Order" in govtribe_starter, govtribe_starter
        assert "Firm Fixed Price" in govtribe_starter, govtribe_starter
        assert "Multiple Award Schedule: 54151S" in govtribe_starter, govtribe_starter
        assert "Historical sub-award prime: Large Prime Integrator" in govtribe_starter, govtribe_starter
        assert "GovTribe award-history signal" in govtribe_starter, govtribe_starter
        assert "min obligated $1.0K" in govtribe_starter, govtribe_starter
        assert "GovTribe Service Contract Inventory signal" in govtribe_starter, govtribe_starter
        assert "move up the vendor chain to DemoGov Holdings Inc." in govtribe_starter, govtribe_starter
        assert "Company URL: https://govtribe.com/vendors/demogov-services-demo1" not in govtribe_starter, govtribe_starter
        assert "User-supplied NAICS: None provided" in govtribe_starter, govtribe_starter
        assert "User-supplied NAICS: 519290" not in govtribe_starter, govtribe_starter
        assert "GovTribe-derived facts remain provisional until the user confirms them." in govtribe_starter, govtribe_starter
        assert "GovTribe subscription-derived facts" in govtribe_starter, govtribe_starter
        assert "GovTribe subscription-derived facts" in govtribe_memory, govtribe_memory
        assert "move up the vendor chain to DemoGov Holdings Inc." in govtribe_memory, govtribe_memory
        assert "Service contract pricing signal" in govtribe_memory, govtribe_memory
        assert "GOVTRIBE_MCP_API_KEY" not in govtribe_payload, govtribe_payload
        provenance = govtribe_vendor_profile["provenance"]["facts"]
        assert any(item.get("field") == "company.uei" for item in provenance), provenance
        assert any(item.get("field") == "company.parent" for item in provenance), provenance
        assert any(item.get("field") == "commercial_constraints.observed_award_value_range" for item in provenance), provenance
        assert all(item.get("source") == "govtribe_mcp_commercial_intel" for item in provenance if item.get("provenance") == "govtribe_subscription_derived"), provenance
        govtribe_source = next(item for item in govtribe_registry["sources"] if item.get("id") == "govtribe_mcp_commercial_intel")
        assert govtribe_source["enabled"] is True, govtribe_source
        assert govtribe_result["recommended_next_moves"][0].startswith("GovTribe resolved DemoGov Services, LLC as a child entity"), govtribe_result

        name_workspace = root / "govtribe-name-workspace"
        name_provider = FakeGovTribeBootstrapProvider()
        name_result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=name_workspace,
            govtribe_lookup="DemoGov Services, LLC",
            company_url="",
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=name_provider,
        )
        assert name_result["status"] == "OK", name_result
        assert name_provider.lookups == ["DemoGov Services, LLC"], name_provider.lookups
        name_vendor_profile = load_json(name_workspace / "procurement" / "vendor-profile.json", default={})
        assert name_vendor_profile["company"]["name"] == "DemoGov Services, LLC", name_vendor_profile

        fallback_workspace = root / "govtribe-fallback-workspace"
        fallback_result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=fallback_workspace,
            govtribe_lookup="DemoGov Services, LLC",
            company_url=(site / "index.html").resolve().as_uri(),
            user_naics=["541512"],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=FakeGovTribeBootstrapProvider(status="not_configured"),
        )
        fallback_vendor_profile = load_json(fallback_workspace / "procurement" / "vendor-profile.json", default={})
        assert fallback_result["status"] == "OK", fallback_result
        assert fallback_result["bootstrap_source"] == "website", fallback_result
        assert fallback_result["govtribe_status"] == "GOVTRIBE_NOT_CONFIGURED", fallback_result
        assert fallback_vendor_profile["bootstrap"]["method"] == "company_url_bootstrap_script_v1", fallback_vendor_profile

        no_match = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=root / "govtribe-no-match-workspace",
            govtribe_lookup="Missing Vendor",
            company_url="",
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=FakeGovTribeBootstrapProvider(status="no_match"),
        )
        assert no_match["status"] == "GOVTRIBE_NO_MATCH", no_match

    print("run_bootstrap_tests.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    def __init__(self, *, status: str = "ok") -> None:
        self.status = status
        self.lookups: list[str] = []

    def resolve_vendor_profile(self, *, lookup: str, limit: int = 5) -> dict:
        self.lookups.append(lookup)
        if self.status != "ok":
            return {
                "status": self.status,
                "matched": False,
                "notes": [f"fake {self.status}"],
                "vendor_record": {},
            }
        return {
            "status": "ok",
            "matched": True,
            "matched_by": "GovTribe vendor search",
            "external_record_id": "vendor-123",
            "source_url": "https://govtribe.com/vendors/halvik-corp-5grr4",
            "vendor_record": {
                "source_id": "govtribe_mcp_commercial_intel",
                "source_name": "GovTribe MCP Commercial Intelligence",
                "external_record_id": "vendor-123",
                "source_url": "https://govtribe.com/vendors/halvik-corp-5grr4",
                "govtribe_id": "vendor-123",
                "govtribe_url": "https://govtribe.com/vendors/halvik-corp-5grr4",
                "name": "Halvik, LLC",
                "uei": "ABC123DEF456",
                "summary": "Halvik provides federal IT modernization and cybersecurity services.",
                "location": "Vienna, VA, USA",
                "naics": ["541512", "Computer Systems Design Services"],
                "certifications": ["SBA Certified 8A Program Participant", "Service Disabled Veteran Owned Business"],
                "contract_vehicles": ["GSA MAS"],
                "buyers": ["Department of Veterans Affairs"],
                "award_signals": ["VA Modernization Support - VA-1 - Department of Veterans Affairs"],
                "keywords": ["541512", "cybersecurity", "GSA MAS", "Department of Veterans Affairs"],
                "raw_record": {},
            },
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
                <title>Halvik, LLC | About Us</title>
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
            explicit_name="Halvik, LLC",
            explicit_summary="Halvik supports federal cybersecurity programs.",
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

        govtribe_workspace = root / "govtribe-workspace"
        fake_provider = FakeGovTribeBootstrapProvider()
        govtribe_result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=govtribe_workspace,
            govtribe_lookup="https://govtribe.com/vendors/halvik-corp-5grr4",
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
        assert fake_provider.lookups == ["https://govtribe.com/vendors/halvik-corp-5grr4"], fake_provider.lookups
        assert govtribe_vendor_profile["bootstrap"]["method"] == "govtribe_vendor_bootstrap_script_v1", govtribe_vendor_profile
        assert govtribe_vendor_profile["company"]["name"] == "Halvik, LLC", govtribe_vendor_profile["company"]
        assert govtribe_vendor_profile["company"]["uei"] == "ABC123DEF456", govtribe_vendor_profile["company"]
        assert "541512" in govtribe_vendor_profile["naics"]["candidates"], govtribe_vendor_profile["naics"]
        assert "SBA Certified 8A Program Participant" in govtribe_vendor_profile["commercial_constraints"]["certifications"], govtribe_vendor_profile
        assert "GSA MAS" in govtribe_vendor_profile["contract_vehicles"], govtribe_vendor_profile
        assert "Department of Veterans Affairs" in govtribe_vendor_profile["buyers"]["notes"], govtribe_vendor_profile
        assert "541512" in govtribe_preferences["soft_preferences"]["preferred_naics"], govtribe_preferences
        assert "GovTribe subscription-derived facts" in govtribe_starter, govtribe_starter
        assert "GovTribe subscription-derived facts" in govtribe_memory, govtribe_memory
        assert "GOVTRIBE_MCP_API_KEY" not in govtribe_payload, govtribe_payload
        provenance = govtribe_vendor_profile["provenance"]["facts"]
        assert any(item.get("field") == "company.uei" for item in provenance), provenance
        assert all(item.get("source") == "govtribe_mcp_commercial_intel" for item in provenance if item.get("provenance") == "govtribe_subscription_derived"), provenance
        govtribe_source = next(item for item in govtribe_registry["sources"] if item.get("id") == "govtribe_mcp_commercial_intel")
        assert govtribe_source["enabled"] is True, govtribe_source

        name_workspace = root / "govtribe-name-workspace"
        name_provider = FakeGovTribeBootstrapProvider()
        name_result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=name_workspace,
            govtribe_lookup="Halvik, LLC",
            company_url="",
            user_naics=[],
            naics_status="confirmed",
            explicit_name="",
            explicit_summary="",
            provider=name_provider,
        )
        assert name_result["status"] == "OK", name_result
        assert name_provider.lookups == ["Halvik, LLC"], name_provider.lookups
        name_vendor_profile = load_json(name_workspace / "procurement" / "vendor-profile.json", default={})
        assert name_vendor_profile["company"]["name"] == "Halvik, LLC", name_vendor_profile

        fallback_workspace = root / "govtribe-fallback-workspace"
        fallback_result = seed_workspace_from_govtribe(
            bundle_root=bundle_root,
            workspace=fallback_workspace,
            govtribe_lookup="Halvik, LLC",
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

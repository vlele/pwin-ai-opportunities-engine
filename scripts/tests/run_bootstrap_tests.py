from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parents[1]
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from bootstrap.bootstrap_workspace import seed_workspace  # type: ignore
from common.paths import load_json  # type: ignore


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.strip() + "\n", encoding="utf-8")


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

    print("run_bootstrap_tests.py: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

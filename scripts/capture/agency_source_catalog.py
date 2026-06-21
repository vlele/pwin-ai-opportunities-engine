from __future__ import annotations

# Declarative agency/source heuristics live here so the main capture logic stays
# package-agnostic and reviewers can audit the specialization surface directly.

AGENCY_DOMAIN_HINTS = {
    "internal revenue service": ["irs.gov", "home.treasury.gov"],
    "treasury, department of the": ["home.treasury.gov"],
    "department of the treasury": ["home.treasury.gov"],
    "department of defense": ["defense.gov", "comptroller.defense.gov"],
    "dept of defense": ["defense.gov", "comptroller.defense.gov"],
    "department of the army": ["army.mil", "defense.gov", "comptroller.defense.gov"],
    "dept of the army": ["army.mil", "defense.gov", "comptroller.defense.gov"],
    "department of the air force": ["af.mil", "defense.gov", "comptroller.defense.gov"],
    "dept of the air force": ["af.mil", "defense.gov", "comptroller.defense.gov"],
    "department of the navy": ["navy.mil", "marines.mil", "defense.gov", "comptroller.defense.gov"],
    "us coast guard": ["uscg.mil", "dhs.gov"],
    "department of homeland security": ["dhs.gov"],
    "department of commerce": ["commerce.gov"],
    "national oceanic and atmospheric administration": ["noaa.gov", "commerce.gov"],
    "health and human services": ["hhs.gov"],
    "department of veterans affairs": ["va.gov"],
    "veterans affairs": ["va.gov"],
    "department of state": ["state.gov"],
    "bureau of international narcotics and law enforcement affairs": ["fam.state.gov", "state.gov"],
    "acquisitions - inl": ["fam.state.gov", "state.gov"],
    "department of energy": ["energy.gov"],
    "department of the interior": ["doi.gov"],
    "general services administration": ["gsa.gov"],
    "federal deposit insurance corporation": ["fdic.gov"],
    "house of representatives": ["house.gov"],
    "selective service system": ["sss.gov"],
    "small business administration": ["sba.gov"],
    "indian health service": ["ihs.gov"],
    "us army corps of engineers": ["erdc.usace.army.mil", "usace.army.mil"],
    "engineer research and development center": ["erdc.usace.army.mil", "usace.army.mil"],
}

AGENCY_OVERSIGHT_HINTS = {
    "internal revenue service": ["tigta.gov", "oversight.gov"],
    "treasury, department of the": ["tigta.gov", "oversight.gov"],
    "department of the treasury": ["tigta.gov", "oversight.gov"],
    "department of defense": ["dodig.mil", "oversight.gov"],
    "dept of defense": ["dodig.mil", "oversight.gov"],
    "department of the army": ["dodig.mil", "oversight.gov"],
    "us army corps of engineers": ["dodig.mil", "oversight.gov"],
    "engineer research and development center": ["dodig.mil", "oversight.gov"],
}

AGENCY_DIRECT_URLS = {
    "state.gov": {
        "mission_context": [
            "https://fam.state.gov/fam/01fam/01fam0530.html",
            "https://2017-2021.state.gov/bureaus-offices/under-secretary-for-civilian-security-democracy-and-human-rights/bureau-of-international-narcotics-and-law-enforcement-affairs",
            "https://2021-2025.state.gov/justice-programs-in-action/",
        ],
        "budget_funding": [
            "https://2017-2021.state.gov/plans-performance-budget",
        ],
    },
    "fam.state.gov": {
        "mission_context": [
            "https://fam.state.gov/fam/01fam/01fam0530.html",
        ],
        "budget_funding": [
            "https://2017-2021.state.gov/plans-performance-budget",
        ],
    },
    "erdc.usace.army.mil": {
        "mission_context": [
            "https://www.erdc.usace.army.mil/About/",
        ],
        "acquisition_forecast": [
            "https://www.erdc.usace.army.mil/Business-With-Us/Small-Business/",
            "https://www.erdc.usace.army.mil/Media/Images/igphoto/2003821542/",
        ],
    },
    "usace.army.mil": {
        "mission_context": [
            "https://www.erdc.usace.army.mil/About/",
        ],
        "acquisition_forecast": [
            "https://www.erdc.usace.army.mil/Business-With-Us/Small-Business/",
            "https://www.erdc.usace.army.mil/Media/Images/igphoto/2003821542/",
        ],
    },
    "af.mil": {
        "mission_context": [
            "https://www.afimsc.af.mil/About-Us/Strategic-Plan/",
            "https://www.afcec.af.mil/Home/Fact-Sheets/Display/Article/2571674/facility-engineering-directorate/",
        ],
        "budget_funding": [
            "https://comptroller.defense.gov/Budget-Materials/",
        ],
        "acquisition_forecast": [
            "https://www.airforcesmallbiz.af.mil/Small-Business/Business-Opportunities/",
            "https://www.airforcesmallbiz.af.mil/Resources/Expiring-Contracts/",
        ],
    },
    "comptroller.defense.gov": {
        "budget_funding": [
            "https://comptroller.defense.gov/Budget-Materials/",
        ],
    },
}

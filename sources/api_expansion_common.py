"""
JOBHUNTER - API EXPANSION COMMON V1

Two equal-priority tracks:
A) QC / pharma / laboratory
B) Junior Data Analyst / BI junior
Plus QC/Data hybrid roles.
"""

from __future__ import annotations

import re
import unicodedata

from database.models import JobOffer
from sources.belgium_locations import BELGIUM, classify_belgium_location

QC_SEARCH_TERMS = (
    "QC Analyst",
    "QC Technician",
    "Laborantin",
    "Technicien laboratoire",
    "Microbiology Analyst",
    "HPLC GMP",
    "LIMS Data Integrity",
)

DATA_SEARCH_TERMS = (
    "Junior Data Analyst",
    "Data Analyst Junior",
    "Junior BI Analyst",
    "Business Intelligence Analyst",
    "Power BI Analyst",
    "Data Quality Analyst",
    "Reporting Analyst",
)

HYBRID_SEARCH_TERMS = (
    "LIMS Analyst",
    "Quality Data Analyst",
    "Data Integrity Specialist",
    "Lab Systems Analyst",
)

ALL_SEARCH_TERMS = QC_SEARCH_TERMS + DATA_SEARCH_TERMS + HYBRID_SEARCH_TERMS

SENIOR_BLOCK = re.compile(
    r"\b(senior|sr\.?|lead|leader|manager|head|director|principal|staff|"
    r"responsable|team\s*lead|chef\s+de|supervisor)\b",
    re.I,
)

NON_TARGET_BLOCK = re.compile(
    r"\b(sales|commercial|account\s+manager|business\s+development|"
    r"marketing|recruiter|recruteur|hr\b|human\s+resources)\b",
    re.I,
)

QC_TITLE = re.compile(
    r"\b("
    r"qc\s+(analyst|technician|laborant|chemist)|"
    r"quality\s+control\s+(analyst|technician|chemist)|"
    r"laborantin|laborant\b|"
    r"technicien(?:ne)?\s+(?:de\s+)?laboratoire|"
    r"analyste\s+(?:de\s+)?laboratoire|"
    r"lab(?:oratory)?\s+(technician|analyst|assistant)|"
    r"microbiology\s+(analyst|technician)|"
    r"analytical\s+(technician|analyst|chemist)|"
    r"chemical\s+(technician|analyst)"
    r")\b",
    re.I,
)

DATA_TITLE = re.compile(
    r"\b("
    r"junior\s+data\s+analyst|"
    r"data\s+analyst\s+junior|"
    r"junior\s+(?:bi|business\s+intelligence)\s+analyst|"
    r"(?:bi|business\s+intelligence)\s+analyst|"
    r"power\s*bi\s+analyst|"
    r"reporting\s+analyst|"
    r"data\s+quality\s+analyst|"
    r"business\s+data\s+analyst"
    r")\b",
    re.I,
)

HYBRID_TITLE = re.compile(
    r"\b("
    r"lims\s+(administrator|admin|analyst|key\s+user)|"
    r"lab(?:oratory)?\s+systems?\s+analyst|"
    r"quality\s+data\s+analyst|"
    r"data\s+integrity\s+(specialist|analyst)|"
    r"csv\s+specialist|"
    r"computerized\s+systems?\s+validation"
    r")\b",
    re.I,
)


def clean(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize(value) -> str:
    text = unicodedata.normalize("NFKD", clean(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text.lower()


def classify_target_title(title: str) -> str | None:
    value = clean(title)
    if not value or SENIOR_BLOCK.search(value) or NON_TARGET_BLOCK.search(value):
        return None
    if HYBRID_TITLE.search(value):
        return "QC_DATA_HYBRID"
    if QC_TITLE.search(value):
        return "QC_PHARMA_LAB"
    if DATA_TITLE.search(value):
        return "DATA_JUNIOR_BI"
    return None


def is_target_title(title: str) -> bool:
    return classify_target_title(title) is not None


def belgium_location_ok(location: str, *, trusted=False) -> bool:
    decision = classify_belgium_location(
        clean(location),
        trusted_belgium_listing=bool(trusted),
    )
    return decision.status == BELGIUM


def make_job(
    *,
    source: str,
    external_id: str,
    title: str,
    company: str,
    location: str,
    description: str,
    url: str,
    date_published=None,
    contract_type=None,
):
    job = JobOffer(
        source=source,
        external_id=clean(external_id),
        title=clean(title),
        company=clean(company) or source.title(),
        location=clean(location),
        description=clean(description),
        url=clean(url),
        date_published=clean(date_published) or None,
        contract_type=clean(contract_type) or None,
        language=None,
    )
    setattr(job, "api_target_track", classify_target_title(title))
    return job

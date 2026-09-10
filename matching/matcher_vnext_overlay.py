"""
JOBHUNTER - CENTRAL MATCHER VNEXT 1.4 PRODUCTION OVERLAY

V5.1 remains the base scorer.

Compared with 1.1:
- explicit incompatibilities remain HARD BLOCKS;
- Dutch-language-only description without explicit Dutch requirement becomes
  LANGUAGE_VERIFY, not automatic rejection;
- exactly 4 years experience becomes EXPERIENCE_4_STRETCH, not rejection;
- 5+ years remains a hard block;
- validation/qualification still needs independent science evidence.

PRODUCTION OVERLAY. The frozen legacy scorer is matching.basic_matcher_v51.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from matching import basic_matcher_v51 as base_matcher

OVERLAY_VERSION = "1.5.1-production"

SENIORITY_BLOCK = re.compile(
    r"\b(?:senior|sr\.?|principal|staff|director|head|manager|"
    r"lead|leader|team\s*lead(?:er)?|teamleader|supervisor)\b",
    re.I,
)

INTERNSHIP_BLOCK = re.compile(
    r"\b(?:intern(?:ship)?|stage|stagiaire|trainee|apprentice|student|phd)\b",
    re.I,
)

COMMERCIAL_BLOCK = re.compile(
    r"\b(?:sales|account manager|business manager|commercial|"
    r"business development|customer success|recruiter|recruitment consultant)\b",
    re.I,
)

NON_TARGET_ANALYST_BLOCK = re.compile(
    r"\b(?:aml|kyc|credit|financial crime|fraud|investment|tax|treasury|"
    r"claims?|underwriting|procurement|supply chain)\s+analyst\b",
    re.I,
)

TECH_ENGINEERING_BLOCK = re.compile(
    r"\b(?:cloud|platform|devops|network|security|cyber|software|"
    r"machine learning|ml|ai)\b.*\bengineer\b",
    re.I,
)

DATA_ENGINEER_TITLE = re.compile(r"\bdata engineer\b", re.I)
DATA_SCIENTIST_TITLE = re.compile(r"\bdata scientist\b", re.I)

TITLE_DUTCH_BLOCK = re.compile(
    r"(?:"
    r"\bfr\s*/\s*nl(?:\s*/\s*en)?\b|"
    r"\bnl\s*/\s*fr(?:\s*/\s*en)?\b|"
    r"\bfr\s*-\s*nl(?:\s*-\s*en)?\b|"
    r"\bfrench\s*/\s*dutch(?:\s*/\s*english)?\b|"
    r"\bdutch\s*/\s*french(?:\s*/\s*english)?\b|"
    r"\btweetalig\b|"
    r"\bbilingual\s+(?:dutch|nl)\b"
    r")",
    re.I,
)

DUTCH_REQUIRED_PATTERNS = (
    r"\bgoede\s+kennis\s+(?:van\s+het\s+)?nederlands\b",
    r"\bnederlands\s+(?:is\s+)?vereist\b",
    r"\bcommunicatief\b[^.!?;]{0,120}\bnederlands\b",
    r"\bfluent\b[^.!?;]{0,120}\bdutch\b",
    r"\bprofessional\s+(?:level\s+)?dutch\b",
    r"\bdutch\s+(?:is\s+)?(?:required|mandatory)\b",
    r"\bgood\s+(?:knowledge|command)\s+of\s+dutch\b",
    r"\bworking\s+proficiency\s+in\s+dutch\b",
    r"\bn[eé]erlandais\s+(?:est\s+)?(?:exig[eé]|requis|obligatoire)\b",
    r"\b(?:vous\s+vous\s+exprimez|vous\s+exprimer|s['’]exprimer)"
    r"[^.!?;]{0,120}\bn[eé]erlandais\b",
    r"\b(?:fran[cç]ais|french)\b[^.!?;]{0,100}\b(?:n[eé]erlandais|dutch)\b"
    r"[^.!?;]{0,100}\b(?:anglais|english)\b",
)

OPTIONAL_LANGUAGE_WORDS = (
    "asset", "plus", "preferred", "nice to have", "atout", "pluspunt",
    "souhaité", "souhaite", "préféré", "preference",
)

NL_WORDS = (
    "voor onze", "wij zijn", "jouw", "je bent", "ervaring", "opleiding",
    "nederlands", "werkervaring", "functie", "verantwoordelijkheden",
    "vaardigheden", "wat zoeken we", "wat bieden we", "solliciteer",
    "minstens", "bij voorkeur", "kennis van",
)

SOURCE_INELIGIBLE = re.compile(
    r"\b(?:ineligible|ineligible_language|reject(?:ed)?|blocked|hard_reject)\b",
    re.I,
)

STRICT_MASTER_REQUIRED = re.compile(
    r"(?:"
    r"\bmaster(?:'s)?\s+degree\s+(?:is\s+)?required\b|"
    r"\brequired\s*[:\-]?\s*master(?:'s)?\b|"
    r"\bmust\s+have\s+(?:a\s+)?master(?:'s)?\b|"
    r"\bmaster\s+(?:obligatoire|exig[eé]|requis)\b|"
    r"\bdipl[oô]me\s+de\s+master\s+(?:obligatoire|exig[eé]|requis)\b"
    r")",
    re.I,
)

EQUIVALENT_EXPERIENCE = re.compile(
    r"\b(?:or|ou)\s+(?:equivalent|[eé]quivalent)\s+(?:by|par)\s+experience\b",
    re.I,
)

DATA_CONTEXT = re.compile(
    r"\b(?:sql|power\s*bi|tableau|qlik|reporting|dashboard|analytics|"
    r"data quality|data governance|data model|etl|ssis|database|"
    r"requirements?|process(?:es)?|functional analysis|business requirements?|"
    r"kpi|statistics?|python|excel)\b",
    re.I,
)

SCIENCE_EVIDENCE = re.compile(
    r"\b(?:pharma|pharmaceutical|biotech|life sciences?|laboratory|laboratoire|"
    r"chemistry|chimie|chemical|gmp|bpf|qc|quality control|microbiology|"
    r"analytical chemistry|hplc|uplc|lc-ms|gc-ms|lims|aseptic|aseptique|"
    r"clean ?room|salle blanche|chromatograph|endotoxin|bioburden|"
    r"cell culture|stability study|raw material testing)\b",
    re.I,
)


@dataclass(frozen=True)
class Rule:
    name: str
    track: str
    family: str
    floor: float
    pattern: re.Pattern
    context: str = "NONE"
    junior_only: bool = False


def _r(pattern: str) -> re.Pattern:
    return re.compile(pattern, re.I)


RULES = (
    # HYBRID
    Rule("lims_analyst", "HYBRID", "hybrid_data_pharma", 91, _r(r"\blims\s+(?:analyst|specialist|coordinator)\b")),
    Rule("laboratory_informatics", "HYBRID", "hybrid_data_pharma", 90, _r(r"\blaboratory informatics\b")),
    Rule("lab_systems_analyst", "HYBRID", "hybrid_data_pharma", 88, _r(r"\blab(?:oratory)? systems?\s+analyst\b")),
    Rule("qc_data_analyst", "HYBRID", "hybrid_data_pharma", 91, _r(r"\bqc\s+data\s+analyst\b")),
    Rule("lab_data_analyst", "HYBRID", "hybrid_data_pharma", 90, _r(r"\b(?:lab|laboratory)\s+data\s+analyst\b")),
    Rule("quality_data_analyst", "HYBRID", "hybrid_data_pharma", 88, _r(r"\bquality\s+data\s+analyst\b")),
    Rule("data_integrity_analyst", "HYBRID", "hybrid_data_pharma", 87, _r(r"\bdata integrity\s+(?:analyst|specialist|officer)\b"), "SCIENCE"),
    Rule("scientific_data", "HYBRID", "hybrid_data_pharma", 84, _r(r"\bscientific data\s+(?:analyst|coordinator|specialist)\b")),
    Rule("digital_qc", "HYBRID", "hybrid_data_pharma", 86, _r(r"\bdigital\s+qc\b")),
    Rule("life_sciences_data_steward", "HYBRID", "hybrid_data_pharma", 85, _r(r"\bdata steward\b"), "SCIENCE"),
    Rule("manufacturing_data_analyst", "HYBRID", "hybrid_data_pharma", 84, _r(r"\bmanufacturing data analyst\b"), "SCIENCE"),

    # DATA_BI
    Rule("junior_data_analyst", "DATA_BI", "data_analytics", 91, _r(r"\bjunior\s+data analyst\b")),
    Rule("business_data_analyst", "DATA_BI", "data_analytics", 87, _r(r"\bbusiness data analyst\b")),
    Rule("data_analyst", "DATA_BI", "data_analytics", 84, _r(r"\bdata analyst\b")),
    Rule("sql_analyst", "DATA_BI", "data_analytics", 84, _r(r"\bsql analyst\b"), "DATA"),
    Rule("analytics_analyst", "DATA_BI", "data_analytics", 82, _r(r"\banalytics analyst\b")),
    Rule("insights_analyst", "DATA_BI", "data_analytics", 78, _r(r"\binsights analyst\b"), "DATA"),
    Rule("bi_analyst", "DATA_BI", "business_intelligence", 84, _r(r"\bbi analyst\b")),
    Rule("business_intelligence_analyst", "DATA_BI", "business_intelligence", 86, _r(r"\bbusiness intelligence analyst\b")),
    Rule("reporting_analyst", "DATA_BI", "business_intelligence", 82, _r(r"\breporting analyst\b")),
    Rule("reporting_officer", "DATA_BI", "business_intelligence", 76, _r(r"\breporting officer\b"), "DATA"),
    Rule("power_bi_analyst", "DATA_BI", "business_intelligence", 86, _r(r"\bpower\s*bi analyst\b")),
    Rule("power_bi_developer", "DATA_BI", "business_intelligence", 80, _r(r"\bpower\s*bi developer\b"), "DATA"),
    Rule("bi_developer", "DATA_BI", "business_intelligence", 78, _r(r"\bbi developer\b"), "DATA"),
    Rule("data_quality_analyst", "DATA_BI", "data_analytics", 86, _r(r"\bdata quality\s+(?:analyst|specialist|officer)\b")),
    Rule("master_data_analyst", "DATA_BI", "data_analytics", 84, _r(r"\bmaster data\s+(?:analyst|specialist)\b")),
    Rule("master_data_coordinator", "DATA_BI", "data_analytics", 78, _r(r"\bmaster data coordinator\b")),
    Rule("data_steward", "DATA_BI", "data_analytics", 82, _r(r"\bdata steward\b"), "DATA"),
    Rule("data_governance", "DATA_BI", "data_analytics", 82, _r(r"\bdata governance\s+(?:analyst|consultant|specialist|officer)\b"), "DATA"),
    Rule("data_coordinator", "DATA_BI", "data_analytics", 77, _r(r"\bdata coordinator\b"), "DATA"),
    Rule("mis_analyst", "DATA_BI", "business_intelligence", 78, _r(r"\bmis analyst\b"), "DATA"),
    Rule("junior_business_analyst", "DATA_BI", "business_analysis", 82, _r(r"\bjunior\s+business analyst\b"), "DATA"),
    Rule("business_analyst", "DATA_BI", "business_analysis", 74, _r(r"\bbusiness analyst\b"), "DATA"),
    Rule("functional_analyst", "DATA_BI", "business_analysis", 73, _r(r"\bfunctional analyst\b"), "DATA"),
    Rule("process_analyst", "DATA_BI", "business_analysis", 72, _r(r"\bprocess analyst\b"), "DATA"),
    Rule("operations_analyst", "DATA_BI", "business_analysis", 69, _r(r"\boperations analyst\b"), "DATA"),
    Rule("junior_analytics_consultant", "DATA_BI", "data_analytics", 74, _r(r"\b(?:junior\s+)?analytics consultant\b"), "DATA", True),
    Rule("junior_data_engineer", "DATA_BI", "data_engineering", 66, _r(r"\bjunior(?:\s*-\s*medior)?\s+data engineer\b"), "DATA", True),
    Rule("junior_data_scientist", "DATA_BI", "data_analytics", 64, _r(r"\bjunior\s+data scientist\b"), "DATA", True),

    # CHEM_LAB
    Rule("laborantin", "CHEM_LAB", "chemistry_lab", 91, _r(r"\blaborantin\b")),
    Rule("lab_technician", "CHEM_LAB", "chemistry_lab", 89, _r(r"\b(?:lab|laboratory)\s+technician\b")),
    Rule("lab_analyst", "CHEM_LAB", "chemistry_lab", 88, _r(r"\b(?:lab|laboratory)\s+analyst\b")),
    Rule("technicien_laboratoire", "CHEM_LAB", "chemistry_lab", 89, _r(r"\btechnicien(?:ne)?\s+(?:de\s+)?laboratoire\b")),
    Rule("analyste_laboratoire", "CHEM_LAB", "chemistry_lab", 88, _r(r"\banalyste\s+(?:de\s+)?laboratoire\b")),
    Rule("technicien_chimiste", "CHEM_LAB", "chemistry_lab", 87, _r(r"\btechnicien(?:ne)?\s+chimiste\b")),
    Rule("chemical_technician", "CHEM_LAB", "chemistry_lab", 85, _r(r"\bchemical technician\b")),
    Rule("chemical_analyst", "CHEM_LAB", "chemistry_lab", 85, _r(r"\bchemical analyst\b")),
    Rule("analytical_technician", "CHEM_LAB", "chemistry_lab", 85, _r(r"\banalytical technician\b")),
    Rule("qc_analyst", "CHEM_LAB", "pharma_qc", 90, _r(r"\bqc\s+analyst\b")),
    Rule("qc_technician", "CHEM_LAB", "pharma_qc", 89, _r(r"\bqc\s+technician\b")),
    Rule("quality_control_analyst", "CHEM_LAB", "pharma_qc", 89, _r(r"\bquality control\s+(?:analyst|technician|specialist|officer)\b")),
    Rule("controle_qualite", "CHEM_LAB", "quality", 84, _r(r"\b(?:contr[oô]le qualit[eé]|laborantin contr[oô]le qualit[eé])\b")),
    Rule("microbiology_analyst", "CHEM_LAB", "chemistry_lab", 86, _r(r"\bmicrobiology\s+(?:analyst|technician|specialist)\b")),
    Rule("qa_associate", "CHEM_LAB", "quality", 82, _r(r"\bqa\s+(?:associate|officer|specialist|technician)\b"), "SCIENCE"),
    Rule("quality_assurance", "CHEM_LAB", "quality", 80, _r(r"\bquality assurance\s+(?:associate|officer|specialist|technician)\b"), "SCIENCE"),
    Rule("gmp_compliance", "CHEM_LAB", "quality", 78, _r(r"\bgmp compliance\s+(?:associate|officer|specialist|analyst)\b"), "SCIENCE"),
    Rule("sample_management", "CHEM_LAB", "pharma_qc", 78, _r(r"\bsample management\s+(?:associate|coordinator|technician|specialist)\b"), "SCIENCE"),
    Rule("stability", "CHEM_LAB", "pharma_qc", 78, _r(r"\bstability\s+(?:analyst|technician|specialist|coordinator)\b"), "SCIENCE"),
    Rule("environmental_monitoring", "CHEM_LAB", "pharma_qc", 78, _r(r"\benvironmental monitoring\s+(?:analyst|technician|specialist)\b"), "SCIENCE"),
    Rule("validation", "CHEM_LAB", "quality", 76, _r(r"\b(?:validation|qualification)\s+(?:engineer|specialist|associate|officer|coordinator)\b"), "SCIENCE"),
    Rule("csv_validation", "CHEM_LAB", "quality", 78, _r(r"\b(?:csv|computer(?:ized)? system validation)\b"), "SCIENCE"),
    Rule("rd_technician", "CHEM_LAB", "chemistry_lab", 78, _r(r"\br&?d\s+technician\b"), "SCIENCE"),
    Rule("production_science", "CHEM_LAB", "chemistry_lab", 70, _r(r"\b(?:production|manufacturing|bioprocess|process)\s+technician\b"), "SCIENCE"),
)


def normalize(value) -> str:
    text = str(value or "").lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+#./'& -]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _attr(job, name):
    return str(getattr(job, name, "") or "")


def title_text(job) -> str:
    return _attr(job, "title")


def job_text(job) -> str:
    return " ".join(
        _attr(job, name)
        for name in (
            "title",
            "detail_matching_text",
            "description",
            "company",
            "location",
            "contract_type",
            "language",
            "degree_requirement",
            "experience_requirement",
            "restriction_text",
            "source_eligibility_reason",
        )
    )


def _has_junior_signal(title: str, text: str) -> bool:
    blob = normalize(title + " " + text[:3000])
    return bool(re.search(
        r"\b(?:junior|entry[- ]level|graduate|young graduate|"
        r"0\s*[-–]\s*3 years?|0\s*[-–]\s*2 years?)\b",
        blob,
    ))


def _context_ok(rule: Rule, title: str, text: str) -> bool:
    blob = title + " " + text[:5000]
    if rule.context == "NONE":
        return True
    if rule.context == "DATA":
        return bool(DATA_CONTEXT.search(blob))
    if rule.context == "SCIENCE":
        return bool(SCIENCE_EVIDENCE.search(blob))
    return False


def _mandatory_dutch(text: str) -> bool:
    low = normalize(text)
    for pattern in DUTCH_REQUIRED_PATTERNS:
        m = re.search(pattern, low, re.I)
        if not m:
            continue
        chunk = low[max(0, m.start()-120):m.end()+120]
        if any(word in chunk for word in OPTIONAL_LANGUAGE_WORDS):
            continue
        return True
    return False


def _clearly_dutch_description(text: str) -> bool:
    low = normalize(text)
    return sum(low.count(x) for x in NL_WORDS) >= 6


def _years_required(job) -> int | None:
    """
    Return the minimum experience threshold actually required.

    Critical rule:
    - 0-5 years => 0, not 5
    - 3-5 years => 3
    - 4-6 years => 4 (stretch)
    - 5-7 years => 5 (hard block)

    Range spans are masked before exact-year patterns are applied so the
    upper bound of a range cannot be re-read as an independent requirement.
    """
    text = " ".join([
        _attr(job, "experience_requirement"),
        _attr(job, "restriction_text"),
        _attr(job, "description")[:5000],
        _attr(job, "detail_matching_text")[:5000],
    ])

    vals = []
    masked = list(text)

    range_patterns = (
        r"\b(\d+)\s*[-–]\s*(\d+)\s+(?:years?|jaar|ans?)\b",
        r"\bbetween\s+(\d+)\s+and\s+(\d+)\s+years?\b",
        r"\bentre\s+(\d+)\s+et\s+(\d+)\s+ans?\b",
        r"\bvan\s+(\d+)\s+tot\s+(\d+)\s+jaar\b",
        r"\b(\d+)\s+to\s+(\d+)\s+years?\b",
    )

    for pattern in range_patterns:
        for m in re.finditer(pattern, text, re.I):
            try:
                low = int(m.group(1))
                high = int(m.group(2))
            except Exception:
                continue
            if 0 <= low <= 15 and 0 <= high <= 15:
                vals.append(min(low, high))
                for i in range(m.start(), m.end()):
                    masked[i] = " "

    remaining = "".join(masked)

    exact_patterns = (
        r"\b(?:minimum|min\.?|at least|minstens|au moins)\s+(\d+)\+?\s+(?:years?|jaar|ans?)\b",
        r"\b(\d+)\+\s*(?:years?|jaar|ans?)\b",
        r"(?<![-–\d])\b(\d+)\s+years?\s+(?:of\s+)?experience\b",
        r"(?<![-–\d])\b(\d+)\s+ans?\s+d['’ ]exp[eé]rience\b",
        r"(?<![-–\d])\b(\d+)\s+jaar\s+ervaring\b",
    )

    for pattern in exact_patterns:
        for m in re.finditer(pattern, remaining, re.I):
            try:
                x = int(m.group(1))
            except Exception:
                continue
            if 0 <= x <= 15:
                vals.append(x)

    return max(vals) if vals else None


def _strict_master_required(job) -> bool:
    text = " ".join([
        _attr(job, "degree_requirement"),
        _attr(job, "restriction_text"),
        _attr(job, "description")[:3000],
    ])
    if not STRICT_MASTER_REQUIRED.search(text):
        return False
    return not bool(EQUIVALENT_EXPERIENCE.search(text))


STUDENT_CONTRACT_SIGNAL = re.compile(
    r"\b(student|étudiant|etudiant|jobstudent|studentenjob|werkstudent)\b",
    re.I,
)
STUDENT_TITLE_SIGNAL = re.compile(
    r"\b(job étudiant|job etudiant|student job|studentenjob|jobstudent|"
    r"student worker|student contract|sales associate\s*\(student\)|"
    r"retail assistant student|vendeur étudiant|vendeur etudiant|"
    r"étudiant vendeur|etudiant vendeur|werkstudent)\b",
    re.I,
)


def _is_student_any_source(job) -> bool:
    if (
        str(_attr(job, "api_target_track") or "").strip().upper() == "STUDENT_ANY"
        or str(_attr(job, "student_source") or "").strip().lower() in {"1","true","yes"}
    ):
        return True

    contract = str(_attr(job, "contract_type") or "")
    title = str(_attr(job, "title") or "")
    return bool(
        STUDENT_CONTRACT_SIGNAL.search(contract)
        or STUDENT_TITLE_SIGNAL.search(title)
    )


def hard_block_reason(job) -> str | None:
    title = normalize(title_text(job))
    text = job_text(job)
    eligibility_status = normalize(_attr(job, "source_eligibility_status"))

    if not title:
        return None

    student_any = _is_student_any_source(job)

    # Dedicated student-job sources are intentionally domain-agnostic.
    # Keep source/language safety below, but do not reject merely because
    # the title contains "student", sales, horeca, logistics, etc.
    if not student_any and SENIORITY_BLOCK.search(title):
        return "SENIORITY"
    if not student_any and INTERNSHIP_BLOCK.search(title):
        return "INTERNSHIP"
    if not student_any and COMMERCIAL_BLOCK.search(title):
        return "COMMERCIAL"
    if not student_any and NON_TARGET_ANALYST_BLOCK.search(title):
        return "NON_TARGET_ANALYST"
    if not student_any and TECH_ENGINEERING_BLOCK.search(title):
        return "TECH_ENGINEERING"

    if not student_any and DATA_ENGINEER_TITLE.search(title) and not _has_junior_signal(title, text):
        return "DATA_ENGINEER_NON_JUNIOR"
    if not student_any and DATA_SCIENTIST_TITLE.search(title) and not _has_junior_signal(title, text):
        return "DATA_SCIENTIST_NON_JUNIOR"

    if not student_any and TITLE_DUTCH_BLOCK.search(title):
        return "DUTCH_TITLE_REQUIRED"

    if eligibility_status and SOURCE_INELIGIBLE.search(eligibility_status):
        return "SOURCE_INELIGIBLE"

    language_blob = " ".join([
        _attr(job, "restriction_text"),
        _attr(job, "source_eligibility_reason"),
        _attr(job, "language"),
        _attr(job, "detail_matching_text")[:5000],
        _attr(job, "description")[:5000],
    ])
    if _mandatory_dutch(language_blob):
        return "DUTCH_REQUIRED"

    years = _years_required(job)
    if years is not None and years >= 5:
        return "EXPERIENCE_5_PLUS"

    if _strict_master_required(job):
        return "MASTER_REQUIRED"

    return None


def soft_warning_reason(job) -> str | None:
    language_blob = " ".join([
        _attr(job, "language"),
        _attr(job, "detail_matching_text")[:5000],
        _attr(job, "description")[:5000],
    ])
    if _clearly_dutch_description(language_blob):
        return "LANGUAGE_VERIFY_DUTCH_DESCRIPTION"

    years = _years_required(job)
    if years == 4:
        return "EXPERIENCE_4_STRETCH"

    return None


THIN_DESCRIPTION_MAX_CHARS = 300

# High-confidence title rules eligible for a conservative title-only rescue
# when the description is genuinely too thin to provide normal context.
THIN_TITLE_RESCUE_RULE_NAMES = {
    "lims_analyst",
    "laboratory_informatics",
    "lab_systems_analyst",
    "qc_data_analyst",
    "lab_data_analyst",
    "quality_data_analyst",
    "junior_data_analyst",
    "business_data_analyst",
    "data_analyst",
    "bi_analyst",
    "business_intelligence_analyst",
    "reporting_analyst",
    "power_bi_analyst",
    "data_quality_analyst",
    "laborantin",
    "lab_technician",
    "lab_analyst",
    "technicien_laboratoire",
    "analyste_laboratoire",
    "technicien_chimiste",
    "chemical_technician",
    "chemical_analyst",
    "analytical_technician",
    "qc_analyst",
    "qc_technician",
    "quality_control_analyst",
    "controle_qualite",
    "microbiology_analyst",
}


def _description_only(job) -> str:
    detail = _attr(job, "detail_matching_text")
    description = _attr(job, "description")
    # Prefer the richer field but do not contaminate thinness with title/company.
    return detail if len(detail.strip()) >= len(description.strip()) else description


def is_genuinely_thin_description(job) -> bool:
    text = re.sub(r"\s+", " ", _description_only(job)).strip()
    return len(text) < THIN_DESCRIPTION_MAX_CHARS


def detect_thin_title_rescue(job):
    if not is_genuinely_thin_description(job):
        return None

    title = title_text(job)
    ntitle = normalize(title)
    if not ntitle:
        return None

    for rule in RULES:
        if rule.name not in THIN_TITLE_RESCUE_RULE_NAMES:
            continue
        if not rule.pattern.search(ntitle):
            continue
        if rule.junior_only and not _has_junior_signal(title, _description_only(job)):
            continue
        return rule
    return None


def detect_rule(job):
    title = title_text(job)
    text = job_text(job)
    ntitle = normalize(title)
    if not ntitle:
        return None

    for rule in RULES:
        if not rule.pattern.search(ntitle):
            continue
        if rule.junior_only and not _has_junior_signal(title, text):
            continue
        if not _context_ok(rule, title, text):
            continue
        return rule
    return None


BLOCK_CAPS = {
    "SENIORITY": 25,
    "INTERNSHIP": 10,
    "COMMERCIAL": 15,
    "NON_TARGET_ANALYST": 15,
    "TECH_ENGINEERING": 20,
    "DATA_ENGINEER_NON_JUNIOR": 25,
    "DATA_SCIENTIST_NON_JUNIOR": 25,
    "DUTCH_TITLE_REQUIRED": 15,
    "DUTCH_REQUIRED": 15,
    "SOURCE_INELIGIBLE": 10,
    "EXPERIENCE_5_PLUS": 30,
    "MASTER_REQUIRED": 25,
}

SOFT_CAPS = {
    "LANGUAGE_VERIFY_DUTCH_DESCRIPTION": 58,
    "EXPERIENCE_4_STRETCH": 55,
}


def _recommendation(score: float, core: bool, provisional: bool, soft: str | None = None) -> str:
    if soft == "LANGUAGE_VERIFY_DUTCH_DESCRIPTION":
        return "🟠 À VÉRIFIER - LANGUE"
    if soft == "EXPERIENCE_4_STRETCH":
        return "🟠 STRETCH - 4 ANS"
    if provisional:
        return "⚠️ SCORE PROVISOIRE"
    if not core:
        return "🔴 HORS CIBLE"
    if score >= 90:
        return "🔥 EXCELLENT MATCH"
    if score >= 80:
        return "🟢 TRÈS PERTINENT"
    if score >= 65:
        return "🟢 PERTINENT"
    if score >= 50:
        return "🟡 À EXAMINER"
    if score >= 35:
        return "⚪ POTENTIEL"
    return "🔴 FAIBLE"


def _apply_block(result: dict, reason: str) -> dict:
    old_score = float(result.get("score") or 0.0)
    cap = float(BLOCK_CAPS.get(reason, 25))
    score = min(old_score, cap)

    result["score"] = round(score, 1)
    result["core_relevance"] = False
    result["recommendation"] = "🔴 HORS CIBLE"
    result["vnext_track"] = None
    result["vnext_rule"] = None
    result["vnext_promoted"] = False
    result["vnext_blocked"] = True
    result["vnext_block_reason"] = reason
    result["vnext_soft_warning"] = None
    result["vnext_score_floor"] = None

    reasons = list(result.get("reasons") or [])
    msg = f"VNext blocage accessibilité/bruit : {reason}"
    if msg not in reasons:
        reasons.append(msg)
    result["reasons"] = reasons

    details = dict(result.get("details") or {})
    details["score"] = round(score, 1)
    details["core_relevance"] = False
    details["reasons"] = list(reasons)
    result["details"] = details
    return result


def _apply_soft_warning(result: dict, warning: str) -> dict:
    old_score = float(result.get("score") or 0.0)
    cap = float(SOFT_CAPS[warning])
    score = min(old_score, cap)

    # Do not convert an already non-core irrelevant role into core merely
    # because it has a warning. The recall rule, if any, may do that later.
    result["score"] = round(score, 1)
    result["vnext_soft_warning"] = warning

    reasons = list(result.get("reasons") or [])
    msg = f"VNext vérification prudente : {warning}"
    if msg not in reasons:
        reasons.append(msg)
    result["reasons"] = reasons
    result["recommendation"] = _recommendation(
        score,
        bool(result.get("core_relevance")),
        bool(result.get("provisional", False)),
        warning,
    )

    details = dict(result.get("details") or {})
    details["score"] = round(score, 1)
    details["reasons"] = list(reasons)
    result["details"] = details
    return result


def apply_overlay(job, base_result: dict) -> dict:
    result = dict(base_result or {})
    result.setdefault("vnext_overlay_version", OVERLAY_VERSION)
    result.setdefault("vnext_track", None)
    result.setdefault("vnext_rule", None)
    result.setdefault("vnext_promoted", False)
    result.setdefault("vnext_blocked", False)
    result.setdefault("vnext_block_reason", None)
    result.setdefault("vnext_soft_warning", None)
    result.setdefault("vnext_score_floor", None)
    result.setdefault("vnext_thin_description_rescue", False)

    block = hard_block_reason(job)
    if block:
        return _apply_block(result, block)

    if _is_student_any_source(job):
        old_score = float(result.get("score") or 0.0)
        new_score = max(old_score, 70.0)
        result["score"] = round(new_score, 1)
        result["core_relevance"] = True
        result["best_family"] = "student_jobs"
        result["vnext_track"] = "STUDENT_ANY"
        result["vnext_rule"] = "student_any_source"
        result["vnext_promoted"] = True
        result["vnext_score_floor"] = 70.0
        result["provisional"] = False
        reasons = list(result.get("reasons") or [])
        msg = "VNext STUDENT_ANY: offre issue d'une source dédiée aux jobs étudiants"
        if msg not in reasons:
            reasons.append(msg)
        result["reasons"] = reasons
        all_scores = dict(result.get("all_family_scores") or {})
        all_scores["student_jobs"] = new_score
        result["all_family_scores"] = all_scores
        result["recommendation"] = "VERIFY"
        return result

    warning = soft_warning_reason(job)
    rule = detect_rule(job)
    thin_rule = detect_thin_title_rescue(job)
    thin_rescue = False

    # If the description is genuinely thin and a high-confidence title rule
    # matches the same normal rule (or no normal contextual rule exists),
    # explicitly treat it as a conservative title-only rescue.
    if thin_rule is not None and (rule is None or rule.name == thin_rule.name):
        rule = thin_rule
        thin_rescue = True

    if rule is not None:
        old_score = float(result.get("score") or 0.0)
        old_core = bool(result.get("core_relevance", False))
        floor = float(rule.floor)

        if thin_rescue:
            # Title-only rescue must never masquerade as a fully evidenced match.
            floor = min(floor, 68.0)
            result["provisional"] = True
            result["confidence_level"] = "LOW"
            result["vnext_thin_description_rescue"] = True

        years = _years_required(job)
        if years == 4:
            floor = min(floor, 55.0)
        elif years == 3:
            floor = min(floor, 68.0)
        elif years == 2:
            floor = min(floor, 74.0)

        if bool(result.get("provisional", False)):
            floor = min(floor, 68.0)
        elif str(result.get("confidence_level") or "").upper() == "LOW":
            floor = min(floor, 72.0)

        if thin_rescue:
            # Real ceiling: a title-only rescue can never keep an inherited
            # base score above 68.
            new_score = min(68.0, max(old_score, floor))
        else:
            new_score = max(old_score, floor)
        result["score"] = round(new_score, 1)
        result["core_relevance"] = True
        result["best_family"] = rule.family
        result["vnext_track"] = rule.track
        result["vnext_rule"] = rule.name
        result["vnext_promoted"] = (not old_core) or new_score > old_score
        result["vnext_score_floor"] = floor

        reasons = list(result.get("reasons") or [])
        if thin_rescue:
            msg = (
                f"VNext {rule.track}: rescue titre fiable sur description <{THIN_DESCRIPTION_MAX_CHARS} "
                f"caractères ({rule.name.replace('_', ' ')})"
            )
        else:
            msg = f"VNext {rule.track}: intitulé compatible ({rule.name.replace('_', ' ')})"
        if msg not in reasons:
            reasons.append(msg)
        result["reasons"] = reasons

        all_scores = dict(result.get("all_family_scores") or {})
        if thin_rescue:
            # Keep the family score consistent with the conservative rescue cap.
            all_scores[rule.family] = new_score
        else:
            all_scores[rule.family] = max(float(all_scores.get(rule.family) or 0.0), new_score)
        result["all_family_scores"] = all_scores

        details = dict(result.get("details") or {})
        details["family"] = rule.family
        details["score"] = round(new_score, 1)
        details["core_relevance"] = True
        details["reasons"] = list(reasons)
        result["details"] = details

    if warning:
        result = _apply_soft_warning(result, warning)
    else:
        result["recommendation"] = _recommendation(
            float(result.get("score") or 0),
            bool(result.get("core_relevance")),
            bool(result.get("provisional", False)),
        )

    return result


def score_job(job):
    return apply_overlay(job, base_matcher.score_job(job))


def print_job_match(job, result):
    return base_matcher.print_job_match(job, result)

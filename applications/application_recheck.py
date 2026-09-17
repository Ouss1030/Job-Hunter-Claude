"""
JOB HUNTER BELGIUM
APPLICATION POST-REFRESH RECHECK - VERSION 1.1

Pourquoi cette couche ?
=======================
Le Gate travaille avant le refresh live. Certaines conditions éliminatoires
peuvent n'apparaître que dans la description complète récupérée ensuite :
agrément médical, restriction d'âge, véritable job étudiant, Master obligatoire,
outil "must", exigence linguistique forte, etc.

Cette couche ne modifie PAS :
- Matcher
- Gate
- Queue
- Canonical
- RAW DB

Elle décide uniquement si une offre rafraîchie est réellement prête pour
générer des documents.

Statuts :
- READY_DOCUMENTS
- STRETCH_REVIEW
- VERIFY
- REJECT
- SOURCE_REVIEW
- CLOSED_OR_REMOVED
- HOLD_DUPLICATE

Usage :
    python -m applications.application_recheck
"""

from __future__ import annotations

import json
import re
import unicodedata
from collections import Counter
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from matching.application_gate_v13 import detect_structured_master_requirement
# 18/09/2026 : la meme detection que le gate branche (couche V1.3.3) — « master data » n'est pas un diplome.
from matching.application_gate_v133 import detect_mandatory_master_v133 as detect_mandatory_master_v131

from matching.dutch_language_guard import analyze_dutch_dominance

RECHECK_VERSION = "1.1"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# Profil connu et volontairement conservateur.
CANDIDATE = {
    "medical_lab_accreditation": False,
    "data_professional_years": 0.0,
    "chemistry_lab_professional_years": 3.0,
    "languages": {"fr": "C2", "en": "B1", "nl": "A2"},
    "known_skills": {
        "hplc", "uplc", "gc", "gmp", "bpf", "bpl", "lims", "sap",
        "trackwise", "python", "sql", "power bi", "excel", "endosafe",
        "microbiologie", "microbiology",
    },
}

DATA_FAMILIES = {
    "data_analytics", "business_intelligence", "business_analysis", "data_engineering"
}


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("’", "'").replace("`", "'")
    text = re.sub(r"[^a-z0-9+#./' -]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # Répare quelques coupures rencontrées dans les descriptions live.
    text = re.sub(r"\bm\s+aster\b", "master", text)
    text = re.sub(r"\bb\s+achelor\b", "bachelor", text)
    return text


def latest_file(directory, pattern):
    paths = list(Path(directory).glob(pattern))
    return max(paths, key=lambda p: p.stat().st_mtime) if paths else None


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def full_live_text(item):
    detail = item.get("live_detail") or {}
    structured = detail.get("structured") or {}
    parts = [
        detail.get("matching_text"),
        structured.get("job_description"),
        structured.get("profile"),
        structured.get("access_conditions"),
        structured.get("language_section"),
    ]
    return "\n".join(clean_text(p) for p in parts if clean_text(p))


def contains_any(text, phrases):
    n = normalize(text)
    return any(normalize(p) in n for p in phrases)


def medical_accreditation_block(text):
    n = normalize(text)
    if CANDIDATE["medical_lab_accreditation"]:
        return False

    medical_context = any(p in n for p in [
        "technologue de laboratoire",
        "laboratoire en analyses medicales",
        "laboratoire d'analyses medicales",
        "biologie clinique",
    ])
    credential = any(p in n for p in [
        "agrement", "visa", "erkenning", "reconnaissance professionnelle",
    ])
    hard = any(p in n for p in [
        "non negociable", "obligatoire", "requis", "requise",
        "required", "mandatory", "vereist", "verplicht",
    ])
    return medical_context and credential and hard


def youth_or_first_job_block(text):
    n = normalize(text)
    patterns = [
        r"\bminder dan 25 jaar\b",
        r"\bmoins de 25 ans\b",
        r"\bmoins de 26 ans\b",
        r"\bunder 26\b",
        r"\bminder dan 26 jaar\b",
        r"\bjonger dan 26 jaar\b",
        r"\bstartbaanovereenkomst\b",
        r"\bpremier emploi\b",
        r"\bfirst job agreement\b",
    ]
    return any(re.search(p, n) for p in patterns)


def _sentence_chunks_recheck(text):
    raw = str(text or "")
    chunks = re.split(r"(?<=[.!?;:])\s+|[\r\n•●▪◦]+", raw)
    return [
        clean_text(chunk)
        for chunk in chunks
        if clean_text(chunk)
    ]


def _bachelor_master_alternative_sentence(sentence):
    """
    Alternatives Bachelor/Master qui ne doivent JAMAIS devenir un hard reject.

    Inclut le néerlandais rencontré en live :
        "bachelor- of masterdiploma in IT..."
    """
    n = normalize(sentence)
    patterns = [
        r"\bbachelor(?:diploma)?\s*[-/]?\s*(?:of|or|ou)\s*master(?:diploma)?\b",
        r"\bbachelier\s*[-/]?\s*(?:of|or|ou)\s*master\b",
        r"\bmaster(?:diploma)?\s*[-/]?\s*(?:of|or|ou)\s*bachelor(?:diploma)?\b",
        r"\bmaster\s*[-/]?\s*(?:of|or|ou)\s*bachelier\b",
    ]
    return any(re.search(pattern, n) for pattern in patterns)


def mandatory_master_block(text):
    """
    V1.1 : aligne le Recheck sur les détecteurs Master du Gate V1.3.2.

    Le Recheck garde une protection supplémentaire pour les formulations
    Bachelor/Master néerlandaises avec tiret ("bachelor- of masterdiploma"),
    observées dans le refresh live.
    """
    for sentence in _sentence_chunks_recheck(text):
        if _bachelor_master_alternative_sentence(sentence):
            continue

        # Le normalize du Recheck répare notamment "m aster" -> "master".
        normalized_sentence = normalize(sentence)

        if detect_mandatory_master_v131(normalized_sentence):
            return True

        if detect_structured_master_requirement(normalized_sentence):
            return True

    return False

def explicit_student_role(text):
    """
    Détecte un VRAI poste étudiant, pas une simple mention d'une expérience
    acquise via un studentenjob.

    Faux positif corrigé :
        "Ervaring via een stage, studentenjob of eerdere functie ... is mooi meegenomen"
        -> ce n'est PAS une offre réservée aux étudiants.
    """
    n = normalize(text)

    strong_patterns = [
        r"\bop zoek naar (?:een )?student\b",
        r"\bwe zoeken (?:een )?student\b",
        r"\bwij zoeken (?:een )?student\b",
        r"\bstudent quality controller\b",
        r"\bstudent laborant(?:e)?\b",
        r"\bjobstudent gezocht\b",
        r"\bvacature (?:voor )?jobstudent\b",
        r"\bals jobstudent\b",
        r"\breserve aux etudiants\b",
        r"\bréservé aux étudiants\b",
        r"\bstatut etudiant (?:requis|obligatoire)\b",
        r"\bstatut étudiant (?:requis|obligatoire)\b",
        r"\bemploi etudiant\b",
        r"\bemploi étudiant\b",
        r"\bjob etudiant\b",
        r"\bjob étudiant\b",
    ]

    return any(re.search(pattern, n) for pattern in strong_patterns)

def mandatory_unknown_skill_block(text):
    n = normalize(text)

    # Règles explicites très fortes.
    hard_rules = [
        ("empower", ["empower is een must", "empower is required", "empower obligatoire"]),
    ]
    for skill, phrases in hard_rules:
        if any(normalize(p) in n for p in phrases) and skill not in CANDIDATE["known_skills"]:
            return skill
    return None


def obvious_live_domain_mismatch(item, text):
    n = normalize(text)
    title = normalize(item.get("title"))
    family = clean_text(item.get("best_family"))

    if family not in {"chemistry_lab", "pharma_qc", "quality", "hybrid_data_pharma"}:
        return None

    # Ex. "contrôle qualité microbiologique" dont les missions réelles sont
    # conduite de ligne + électromécanique + maintenance.
    if (
        "embouteillage" in title
        and any(p in n for p in ["electromecanique", "electromechanique"])
        and "ligne d'embouteillage" in n
        and any(p in n for p in ["reparation", "reparations", "maintenance"])
    ):
        return "Missions réelles principalement électromécaniques/production, hors cœur labo-QC"

    return None


def strong_language_gap(text):
    n = normalize(text)
    warnings = []

    dutch_strong = [
        "goede beheersing van het nederlands",
        "goede beheersing van nederlands",
        "goede kennis van het nederlands",
        "goede kennis van nederlands",
        "communiceert vlot in het nederlands",
        "communiceert vlot in nederlands",
        "vlot in het nederlands",
        "vlot in nederlands",
        "zeer vlot nederlands",
        "vlotte communicatievaardigheden in het nederlands",
        "vloeiend nederlands",
        "nederlands als moedertaal",
        "moedertaal nederlands",
        "neerlandais comme langue maternelle",
        "bonne connaissance professionnelle de l'autre langue",
        "fluent dutch",
        "native dutch",
    ]
    if (
        any(normalize(p) in n for p in dutch_strong)
        and CANDIDATE["languages"]["nl"] == "A2"
    ):
        warnings.append(
            "Néerlandais demandé à un niveau professionnel/aisé ; candidat A2"
        )

    english_strong = [
        "aisance professionnelle en anglais",
        "professional english",
        "good command of english",
        "good knowledge of english",
        "goede kennis van het engels",
        "goede beheersing van het engels",
        "vlotte communicatievaardigheden in het engels",
        "zeer vlot engels",
        "vloeiend engels",
        "fluent english",
    ]
    if (
        any(normalize(p) in n for p in english_strong)
        and CANDIDATE["languages"]["en"] == "B1"
    ):
        warnings.append(
            "Anglais professionnel/bon niveau demandé ; candidat B1"
        )

    return warnings

def _stack_term_is_mentioned(raw_text, normalized_text, term):
    """
    Tableau est un cas particulier :
    - "Tableau" = technologie potentielle
    - "tableaux de bord" = nom commun français

    On utilise donc la casse originale pour la marque Tableau.
    """
    if term == "tableau":
        return bool(re.search(r"\bTableau\b", str(raw_text or "")))

    pattern = r"(?<![a-z0-9])" + re.escape(normalize(term)) + r"(?![a-z0-9])"
    return bool(re.search(pattern, normalized_text))


def data_experience_or_degree_stretch(item, text):
    family = clean_text(item.get("best_family"))
    if family not in DATA_FAMILIES:
        return []

    n = normalize(text)
    warnings = []

    if CANDIDATE["data_professional_years"] <= 0:
        if any(p in n for p in [
            "experience averee",
            "premiere experience probante d'un an minimum",
            "1 an minimum",
            "minimum 1 an",
            "aantoonbare ervaring",
            "ervaring in",
        ]):
            warnings.append(
                "Expérience professionnelle Data/BI demandée ; "
                "candidat surtout académique/projet"
            )

    degree_patterns = [
        r"\bbachelor(?:diploma)?\s+in\s+informatica\b",
        r"\bbachelor(?:diploma)?\s+in\s+(?:it|ict)\b",
        r"\bbachelor.{0,45}(?:informatica|computer science|it|ict)\b",
        r"\bbachelor.{0,65}(?:logistiek|logistics|supply chain)\b",
        r"\bbachelor ou d'un master en informatique\b",
        r"\bbachelor ou master en informatique\b",
        r"\bmaster en informatique\b",
    ]
    if any(re.search(pattern, n) for pattern in degree_patterns):
        warnings.append(
            "Diplôme explicitement orienté IT/informatique/logistique/supply chain ; "
            "profil candidat adjacent via BDA/chimie"
        )

    stack_terms = {
        "talend",
        "apache hop",
        "tableau",
        "oracle",
        "pl/sql",
        "sap business object",
    }
    mentioned = sorted(
        skill
        for skill in stack_terms
        if _stack_term_is_mentioned(text, n, skill)
    )
    missing = [
        skill
        for skill in mentioned
        if skill not in CANDIDATE["known_skills"]
    ]

    if len(missing) >= 2:
        warnings.append(
            "Stack spécifique non démontrée : " + ", ".join(missing)
        )

    return warnings

def qa_experience_stretch(text):
    n = normalize(text)
    if any(p in n for p in [
        "ervaring in een kwaliteitsborgingsfunctie",
        "experience in a quality assurance role",
        "experience en assurance qualite",
    ]):
        return ["Expérience QA/GDP dédiée demandée ; expérience candidat principalement QC/laboratoire"]
    return []


def text_for_similarity(item):
    detail = item.get("live_detail") or {}
    # Pour les doublons cross-source, le matching_text complet est volontairement
    # utilisé : Forem et Actiris encapsulent parfois différemment le même contenu
    # dans les champs structurés, alors que le texte complet reste quasi identique.
    text = detail.get("matching_text") or ""
    return normalize(text)


def same_location_family(a, b):
    la = normalize(a.get("location"))
    lb = normalize(b.get("location"))

    # Même ville / même code postal / même ancre textuelle significative.
    common_places = [
        "spa", "bruxelles", "anderlecht", "saint gilles", "woluwe",
        "wavre", "louvain la neuve", "ardooie", "kortemberg", "kortenberg",
    ]
    for place in common_places:
        if place in la and place in lb:
            return True

    post_a = set(re.findall(r"\b\d{4}\b", la))
    post_b = set(re.findall(r"\b\d{4}\b", lb))
    return bool(post_a & post_b)


def find_live_duplicates(items):
    live = [
        x for x in items
        if x.get("job_live_status") == "LIVE_CONFIRMED"
        and text_for_similarity(x)
    ]
    duplicates = {}

    for i, a in enumerate(live):
        ta = text_for_similarity(a)
        for b in live[i + 1:]:
            if not same_location_family(a, b):
                continue
            tb = text_for_similarity(b)
            ratio = SequenceMatcher(None, ta, tb).ratio()
            if ratio >= 0.90:
                primary, secondary = sorted(
                    [a, b],
                    key=lambda x: (
                        int(x.get("queue_rank") or 999999),
                        -float(x.get("queue_score") or 0),
                    ),
                )
                duplicates[secondary.get("stable_item_key")] = {
                    "duplicate_of": primary.get("stable_item_key"),
                    "similarity": round(ratio, 3),
                }
    return duplicates


def evaluate_item(item, duplicate_map=None):
    duplicate_map = duplicate_map or {}
    result = {
        "recheck_version": RECHECK_VERSION,
        "stable_item_key": item.get("stable_item_key"),
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "url": item.get("url"),
        "queue_rank": item.get("queue_rank"),
        "queue_score": item.get("queue_score"),
        "match_score": item.get("match_score"),
        "cv_track": item.get("cv_track"),
        "reasons": [],
        "warnings": [],
        "duplicate_of": None,
        "duplicate_similarity": None,
    }

    live_status = clean_text(item.get("job_live_status"))
    reason = clean_text(item.get("reason"))

    if live_status != "LIVE_CONFIRMED":
        if "404" in reason:
            result["status"] = "CLOSED_OR_REMOVED"
            result["reasons"].append("La source live renvoie 404 : offre probablement retirée/fermée")
        else:
            result["status"] = "SOURCE_REVIEW"
            result["reasons"].append(reason or "Lecture live impossible")
        return result

    stable_key = item.get("stable_item_key")
    if stable_key in duplicate_map:
        d = duplicate_map[stable_key]
        result["status"] = "HOLD_DUPLICATE"
        result["duplicate_of"] = d["duplicate_of"]
        result["duplicate_similarity"] = d["similarity"]
        result["reasons"].append(
            f"Description live quasi identique à {d['duplicate_of']} "
            f"(similarité {d['similarity']:.3f})"
        )
        return result

    text = full_live_text(item)

    if medical_accreditation_block(text):
        result["status"] = "REJECT"
        result["reasons"].append(
            "Agrément de technologue de laboratoire médical explicitement requis/non négociable"
        )
        return result

    if youth_or_first_job_block(text):
        result["status"] = "REJECT"
        result["reasons"].append("Restriction d'âge / convention premier emploi incompatible")
        if mandatory_master_block(text):
            result["reasons"].append("Master également explicitement demandé")
        return result

    if mandatory_master_block(text):
        result["status"] = "REJECT"
        result["reasons"].append(
            "Master explicitement demandé sans alternative Bachelor clairement indiquée"
        )
        return result

    missing_must = mandatory_unknown_skill_block(text)
    if missing_must:
        result["status"] = "REJECT"
        result["reasons"].append(
            f"Compétence explicitement 'must' non démontrée dans le profil : {missing_must}"
        )
        return result

    dutch_guard = analyze_dutch_dominance(text)
    result["dutch_language_guard"] = dutch_guard
    if dutch_guard.get("predominantly_dutch"):
        result["warnings"].append(
            "Description live principalement redigee en neerlandais ; langue de page seule non eliminatoire. "
            "Verifier uniquement les exigences NL professionnelles explicites."
        )

    mismatch = obvious_live_domain_mismatch(item, text)
    if mismatch:
        result["status"] = "REJECT"
        result["reasons"].append(mismatch)
        return result

    if explicit_student_role(text):
        result["status"] = "VERIFY"
        result["reasons"].append(
            "Offre explicitement réservée/recherchant un étudiant : statut étudiant à confirmer"
        )
        return result

    warnings = list(result["warnings"])
    warnings.extend(strong_language_gap(text))
    warnings.extend(data_experience_or_degree_stretch(item, text))
    warnings.extend(qa_experience_stretch(text))

    # Cas analytique : "expérience limitée" ou 2 ans en labo avec profil QC 3 ans
    # ne génère pas de pénalité supplémentaire.
    if warnings:
        result["status"] = "STRETCH_REVIEW"
        result["warnings"] = list(dict.fromkeys(warnings))
        result["reasons"].append("Candidature possible mais revue humaine recommandée avant documents")
        return result

    result["status"] = "READY_DOCUMENTS"
    result["reasons"].append(
        "Description live relue : aucun blocage supplémentaire détecté"
    )
    return result


def recheck_batch(items):
    duplicate_map = find_live_duplicates(items)
    results = [evaluate_item(item, duplicate_map) for item in items]
    results.sort(key=lambda x: int(x.get("queue_rank") or 999999))
    return results


def summary(results):
    counts = Counter(x.get("status") for x in results)
    return {
        "total": len(results),
        **{status: counts.get(status, 0) for status in [
            "READY_DOCUMENTS",
            "STRETCH_REVIEW",
            "VERIFY",
            "REJECT",
            "SOURCE_REVIEW",
            "CLOSED_OR_REMOVED",
            "HOLD_DUPLICATE",
        ]}
    }


def export_results(results):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    json_path = LOG_DIR / f"application_recheck_v1_{stamp}.json"
    txt_path = LOG_DIR / f"application_recheck_v1_{stamp}.txt"

    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    s = summary(results)
    lines = [
        "APPLICATION POST-REFRESH RECHECK V1.1",
        "=" * 78,
        f"Total              : {s['total']}",
        f"READY_DOCUMENTS    : {s['READY_DOCUMENTS']}",
        f"STRETCH_REVIEW     : {s['STRETCH_REVIEW']}",
        f"VERIFY             : {s['VERIFY']}",
        f"REJECT             : {s['REJECT']}",
        f"SOURCE_REVIEW      : {s['SOURCE_REVIEW']}",
        f"CLOSED_OR_REMOVED  : {s['CLOSED_OR_REMOVED']}",
        f"HOLD_DUPLICATE     : {s['HOLD_DUPLICATE']}",
        "",
    ]

    for i, item in enumerate(results, 1):
        lines.extend([
            f"{i:2d}. {item['status']} | Q{float(item.get('queue_score') or 0):.1f} "
            f"| M{float(item.get('match_score') or 0):.1f}",
            f"    {item.get('title')}",
            f"    {item.get('company')} | {item.get('location')}",
        ])
        for r in item.get("reasons", []):
            lines.append(f"    ↳ {r}")
        for w in item.get("warnings", []):
            lines.append(f"    ⚠ {w}")
        lines.append(f"    {item.get('url')}")
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")
    return txt_path, json_path


def main():
    input_path = latest_file(LOG_DIR, "job_refresh_v1_*.json")
    if not input_path:
        raise SystemExit("Aucun job_refresh_v1_*.json trouvé dans exports/logs.")

    items = load_json(input_path)
    results = recheck_batch(items)
    txt_path, json_path = export_results(results)
    s = summary(results)

    print("\nAPPLICATION POST-REFRESH RECHECK V1.1")
    print("=" * 78)
    print(f"Source             : {input_path}")
    for key in [
        "READY_DOCUMENTS", "STRETCH_REVIEW", "VERIFY", "REJECT",
        "SOURCE_REVIEW", "CLOSED_OR_REMOVED", "HOLD_DUPLICATE"
    ]:
        print(f"{key:18s} : {s[key]}")
    print(f"TXT                : {txt_path}")
    print(f"JSON               : {json_path}")


if __name__ == "__main__":
    main()

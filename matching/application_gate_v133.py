"""
JOB HUNTER BELGIUM
APPLICATION GATE - VERSION 1.3.3

Couche au-dessus du Gate V1.3.2.

    application_gate.py       V1.2    inchangé
    application_gate_v13.py   V1.3.2  inchangé
    application_gate_v133.py  V1.3.3  cette couche

Rollback : réimporter apply_application_gate depuis application_gate_v13.

============================================================================
CONSTAT GÉNÉRAL
============================================================================
Le Gate V1.2 dispose déjà d'un utilitaire de correspondance à frontières
lexicales, phrase_regex() / contains_phrase(), dont le docstring dit :

    "fabric" ne doit PAS matcher "fabrication".

Le V1.2 l'utilise 9 fois. Les couches V1.3.1 et V1.3.2 ne l'utilisent
jamais : elles testent leurs marqueurs en sous-chaîne brute. C'est la
cause commune du bug V.I.E historique et des défauts corrigés ici.

La Queue V1.2 a résolu le même problème de son côté avec
_bounded_phrase_in_text() ("Evere" ne doit plus matcher "Beveren").

V1.3.3 applique cette technique à la couche Gate.

============================================================================
CORRECTIF 1 - MARQUEURS EN SOUS-CHAÎNE (deux sites)
============================================================================
Site A, diplôme :
    "Master's degree in Pharma plus GMP knowledge is required."
    -> "pharmA PLUS" déclenche le marqueur optionnel "a plus"
    -> un Master réellement exigé n'est pas bloqué.

Site B, expérience (plus coûteux) :
    "Minimum 5 ans d'expérience en pharma plus GMP requise."
    -> mandatory=None, optional=5
    -> une exigence de 5 ans devient optionnelle et ne bloque plus rien.

Aucun marqueur n'est retiré des listes : ils sont seulement testés avec
frontières lexicales.

============================================================================
CORRECTIF 2 - ANCIENNETÉ D'AGENCE NON COUVERTE
============================================================================
Le V1.3.2 traite "N ans d'expérience dans le recrutement" mais pas :

    "Après plus de 20 ans d'expérience et plus de 200 collaborateurs,
     nous avons pu devenir leader sur le marché du travail."

Le découpage en fragments coupe sur la virgule, ce qui sépare le nombre
du signal d'entreprise situé après. Restaient rejetées à tort 5 offres
kwaliteitscontrole du run du 18/08/2026, sans aucun autre blocage.

Deux formulations d'auto-présentation sont ajoutées :
  - la tournure "après/avec/fort de (plus de) N ans d'expérience",
    qui n'est jamais une exigence adressée au candidat ;
  - la taille d'entreprise ("N collaborateurs", "N agences").

============================================================================
CORRECTIF 3 - "MASTER DATA" DANS LA BRANCHE OBLIGATION
============================================================================
Le garde-fou existait dans detect_structured_master_requirement() mais pas
dans detect_mandatory_master_v131(), qui lisait donc

    "Master Data governance experience required."

comme un diplôme Master exigé. Impact nul sur le run actuel, bloquant dès
que la track DATA s'élargit (Data Steward, Data Governance).

============================================================================
CORRECTIF 4 - \\bVIE\\b MAJUSCULE
============================================================================
La règle "VIE en capitales dans le titre" rejette les titres français tout
en majuscules : "CONSEILLER ASSURANCE VIE", "SCIENCES DE LA VIE". Sur les
données réelles elle n'a produit aucune détection unique : les deux vraies
offres V.I.E du run portent la ponctuation dans le titre. Règle retirée ;
V.I.E, V-I-E, "VIE Programme" et les formulations officielles restent.

============================================================================
CORRECTIF 5 - MENTION V.I.E NON AUTO-RÉFÉRENTIELLE
============================================================================
    "review of internship agreements and V.I.E (Volontariat International
     en Entreprise) programme applications"

Poste RH qui administre des dossiers V.I.E, pas une offre V.I.E. La
formulation officielle n'est retenue que si la fenêtre porte aussi un
marqueur auto-référentiel (poste, contrat, mission, position...).
"""

from __future__ import annotations

import re
from contextlib import contextmanager

import matching.application_gate as base_gate
import matching.application_gate_v13 as gate_v132


GATE_VERSION = "1.3.5"


# ============================================================
# CORRESPONDANCE À FRONTIÈRES LEXICALES
# ============================================================

def _bounded_in(marker, normalized_text):
    """
    Même technique que base_gate.phrase_regex() et que
    application_queue_v12._bounded_phrase_in_text().

    La normalisation de la couche V1.3.x (_norm) est appliquée au marqueur
    pour rester cohérent avec le texte déjà normalisé qu'on reçoit.
    """
    nmarker = gate_v132._norm(marker)
    if not nmarker or not normalized_text:
        return False

    pieces = [re.escape(piece) for piece in nmarker.split()]
    body = r"\s+".join(pieces)
    pattern = rf"(?<![a-z0-9]){body}(?![a-z0-9])"
    return re.search(pattern, normalized_text) is not None


# ============================================================
# CORRECTIF 1 - SITE A : MARQUEURS DIPLÔME
# ============================================================

def _optional_master_sentence_v133(sentence):
    n = gate_v132._norm(sentence)

    if gate_v132._bachelor_alternative(sentence):
        return True

    return any(
        _bounded_in(marker, n)
        for marker in _OPTIONAL_MASTER_MARKERS
    )


_OPTIONAL_MASTER_MARKERS = [
    "is a plus",
    "est un plus",
    "serait un plus",
    "un plus",
    "a plus",
    "asset",
    "atout",
    "preferred",
    "preferable",
    "nice to have",
    "nice-to-have",
    "souhaite",
    "souhaitee",
    "pluspunt",
    "mooi meegenomen",
    "bij voorkeur",
    "voorkeur",
]


# ============================================================
# CORRECTIF 1 - SITE B : MARQUEURS EXPÉRIENCE
# ============================================================

def _experience_optional_v133(chunk):
    n = gate_v132._norm(chunk)
    return any(
        _bounded_in(marker, n)
        for marker in gate_v132._EXPERIENCE_OPTIONAL_MARKERS_V132
    )


# ============================================================
# CORRECTIF 2 - AUTO-PRÉSENTATION D'AGENCE
# ============================================================

_COMPANY_HISTORY_EXTRA_V133 = [
    # "Après plus de 20 ans d'expérience", "Fort de 30 ans d'expérience".
    # Jamais une exigence adressée au candidat.
    r"\b(?:apres|avec|fort de|forte de|riche de)\s+(?:plus de\s+)?"
    r"\d{1,3}\s*(?:ans|annees)\s+d[' ]?experience",
    # Taille de l'entreprise citée dans le même fragment.
    r"\b\d{1,3}\s*(?:collaborateurs?|medewerkers?|employees?)\b",
    r"\b\d{1,3}\s*(?:agences?|kantoren|vestigingen|filiales?)\b",
]


def _company_history_experience_v133(chunk):
    n = gate_v132._norm(chunk)

    if any(
        re.search(pattern, n)
        for pattern in gate_v132._COMPANY_HISTORY_PATTERNS_V132
    ):
        return True

    return any(
        re.search(pattern, n)
        for pattern in _COMPANY_HISTORY_EXTRA_V133
    )


# ============================================================
# CORRECTIF 3 - "MASTER DATA" EN BRANCHE OBLIGATION
# ============================================================

def _strip_master_data(normalized_sentence):
    return re.sub(r"(?<![a-z0-9])master\s+data(?![a-z0-9])", " ",
                  normalized_sentence)


def detect_mandatory_master_v133(text):
    for sentence in gate_v132._sentence_chunks(text):
        if not gate_v132._contains_master_term(sentence):
            continue

        # "Master Data" est un domaine métier, pas un diplôme.
        residu = _strip_master_data(gate_v132._norm(sentence))
        if not gate_v132._contains_master_term(residu):
            continue

        if _optional_master_sentence_v133(sentence):
            continue

        if gate_v132._explicit_master_requirement_sentence(sentence):
            return True

    return False


# ============================================================
# CORRECTIFS 4 ET 5 - V.I.E
# ============================================================

_VIE_SELF_REFERENTIAL = [
    "poste",
    "contrat",
    "mission",
    "position",
    "contract",
    "assignment",
    "cette offre",
    "deze functie",
    "opportunity",
    "opportunite",
]

_VIE_OFFICIAL_PHRASES = [
    "volontariat international en entreprise",
    "volunteer for international experience",
]


def _explicit_vie_offer_v133(title, text=""):
    raw_title = gate_v132._clean(title)
    norm_title = gate_v132._norm(title)
    norm_text = gate_v132._norm(text)

    if re.search(
        r"\bV\s*\.\s*I\s*\.\s*E\s*\.?(?=\s|$|\W)",
        raw_title,
        flags=re.IGNORECASE,
    ):
        return True

    if re.search(r"\bV\s*-\s*I\s*-\s*E\b", raw_title, flags=re.IGNORECASE):
        return True

    # V1.3.3 : la règle "\bVIE\b en capitales" est retirée (correctif 4).

    if re.search(r"\bvie\s+(?:programme|program)\b", norm_title):
        return True

    # V1.3.3 : formulation officielle auto-référentielle seulement (correctif 5).
    for phrase in _VIE_OFFICIAL_PHRASES:
        for m in re.finditer(re.escape(phrase), norm_text):
            window = norm_text[max(0, m.start() - 120): m.end() + 120]
            if any(_bounded_in(mk, window) for mk in _VIE_SELF_REFERENTIAL):
                return True

    return False


# ============================================================
# CORRECTIF 6 - EXIGENCE LINGUISTIQUE SANS NIVEAU CECR
# ============================================================
"""
detect_language_gaps() du V1.2 ne déduit un niveau requis que si le texte
contient un niveau CECR explicite (B2, C1...) ou un mot de fluidité
("courant", "fluent", "vloeiend"). Or les annonces belges expriment le plus
souvent l'exigence autrement :

    "Je hebt een goede kennis Nederlands"
    "maîtrise du néerlandais exigée"
    "tweetalig FR/NL"
    "Nederlands is een must"

Aucune de ces formulations ne produisait d'écart, donc aucun blocage.
Tant que le profil déclarait néerlandais B1 l'effet restait limité ; il
devient déterminant dès lors que le candidat ne parle pas néerlandais.

Cette couche complète le résultat du V1.2 au lieu de le remplacer : les
écarts déjà détectés sont conservés tels quels.
"""

# Formulations qui expriment une capacité de travail dans la langue, sans
# nommer de niveau. Rattachées à B2 : savoir travailler dans la langue.
_MAITRISE_MARQUEURS = (
    "goede kennis", "grondige kennis", "uitstekende kennis",
    "zeer goede kennis", "kennis van het",
    "bonne maitrise", "tres bonne maitrise", "excellente maitrise",
    "maitrise du", "maitrise de la", "bonne connaissance",
    "tres bonne connaissance", "excellente connaissance",
    "good knowledge", "very good knowledge", "excellent knowledge",
    "strong command", "good command",
    "tweetalig", "bilingue", "bilingual",
    "is een must", "est un must",
)

_NIVEAU_MAITRISE = "B2"

# Référence capturée à l'import, AVANT toute substitution. Sans cela,
# detect_language_gaps_v134 s'appellerait elle-même une fois le symbole
# remplacé dans base_gate : piège classique du monkeypatch.
_DETECT_LANGUAGE_GAPS_ORIGINAL = base_gate.detect_language_gaps
_DETECT_STUDENT_ROLE_ORIGINAL = base_gate.detect_student_role


# Formulations néerlandaises qui expriment une exigence, pas un souhait.
_OBLIGATION_MARQUEURS = (
    "vereist", "noodzakelijk", "verplicht", "must", "is een must",
    "je hebt", "je beheerst", "je spreekt", "u hebt",
    "exige", "exigee", "requis", "requise", "obligatoire", "indispensable",
    "required", "mandatory",
)

# En Belgique, "bilingue" / "tweetalig" signifie FR/NL : c'est une exigence
# de néerlandais même si le mot "néerlandais" n'apparaît pas.
_BILINGUE_MARQUEURS = ("tweetalig", "bilingue", "bilingual", "nl/fr", "fr/nl")


def _langue_exigee_sans_niveau(texte_normalise, code_langue):
    """
    Cherche une exigence de maîtrise pour une langue, dans une fenêtre
    autour de la mention de cette langue.

    La fenêtre évite d'attribuer à une langue un marqueur qui concerne la
    langue voisine — c'est le défaut que le V1.1 avait déjà corrigé pour
    les niveaux CECR, et qu'il faut respecter ici aussi.
    """
    for alias in base_gate.LANGUAGE_ALIASES.get(code_langue, ()):
        n_alias = base_gate.normalize(alias)
        if not n_alias:
            continue
        for m in base_gate.iter_phrase_matches(texte_normalise, n_alias):
            fenetre = texte_normalise[
                max(0, m.start() - 60): min(len(texte_normalise), m.end() + 60)
            ]
            if base_gate.is_optional_context(fenetre):
                continue
            if any(_bounded_in(marq, fenetre) for marq in _MAITRISE_MARQUEURS):
                return fenetre
    return None


def _exigence_bilingue(texte_normalise):
    """"Tweetalig", "bilingue" : exigence de néerlandais sans le nommer."""
    for marq in _BILINGUE_MARQUEURS:
        if not _bounded_in(marq, texte_normalise):
            continue
        idx = texte_normalise.find(base_gate.normalize(marq))
        fenetre = texte_normalise[max(0, idx - 60): idx + 90]
        if base_gate.is_optional_context(fenetre):
            continue
        return fenetre
    return None


def detect_language_gaps_v134(text):
    """
    Complète le résultat du V1.2 sans le remplacer.

    Restriction volontaire : cette inférence ne s'applique qu'aux langues où
    le candidat est en dessous de B1 (A1/A2). Pour une langue déjà à B1,
    "good knowledge required" ne dit pas grand-chose de plus que B1 et
    ferait basculer en STRETCH des offres parfaitement accessibles.
    """
    gaps = list(_DETECT_LANGUAGE_GAPS_ORIGINAL(text))
    deja = {g["language"] for g in gaps}
    norm = base_gate.normalize(text)

    for code in ("nl", "en", "fr"):
        if code in deja:
            continue

        niveau_candidat = base_gate.CANDIDATE["languages"][code]
        rang_candidat = base_gate.LEVEL_RANK[niveau_candidat]

        # Seulement pour une langue réellement non maîtrisée.
        if rang_candidat > base_gate.LEVEL_RANK["A2"]:
            continue

        rang_requis = base_gate.LEVEL_RANK[_NIVEAU_MAITRISE]
        if rang_requis <= rang_candidat:
            continue

        fenetre = _langue_exigee_sans_niveau(norm, code)
        if fenetre is None and code == "nl":
            fenetre = _exigence_bilingue(norm)
        if fenetre is None:
            continue

        obligatoire = (
            base_gate.is_mandatory_context(fenetre)
            or any(_bounded_in(m, fenetre) for m in _OBLIGATION_MARQUEURS)
            or any(_bounded_in(m, fenetre) for m in _BILINGUE_MARQUEURS)
        )
        ecart = rang_requis - rang_candidat

        gaps.append({
            "language": code,
            "candidate_level": niveau_candidat,
            "required_level": _NIVEAU_MAITRISE,
            "mandatory": obligatoire,
            "hard": bool(obligatoire and ecart >= 2),
        })

    return gaps


# ============================================================
# CORRECTIF 7 - STAGES ET ALTERNANCES
# ============================================================
"""
STUDENT_TITLE_MARKERS du V1.2 ne contient que des formulations comme
"student job". Les intitulés les plus fréquents passaient au travers :

    "Stage : Data Analyst - Optimisation des opérations"     -> APPLY
    "Internship: Global Supply Chain Planning"               -> APPLY
    "Stage en alternance : Business Analyst"                 -> APPLY

Le défaut était invisible tant que les sources ne remontaient que de
l'intérim. Les sites carrière des groupes pharma publient au contraire
beaucoup de stages, ce qui l'a rendu visible.

Le candidat a trois ans d'expérience professionnelle et des diplômes
achevés : un stage ou une alternance est réservé à un statut étudiant
qu'il n'a plus.
"""

# Marqueurs sans ambiguïté : leur seule présence suffit.
_STUDENT_MARQUEURS_V135 = (
    "stagiaire", "stagiair", "alternance", "internship", "internships",
    "intern", "trainee", "traineeship", "apprenti", "apprentice",
    "apprenticeship", "graduate program", "graduate programme",
    "summer job", "job etudiant", "studentenjob", "werkstudent",
    "student job",
)

# "stage" seul est ambigu : en génie chimique, un "stage pilote" ou une
# "analyse de stage de production" désigne une étape de procédé, pas un
# stage étudiant. On exige donc la forme réellement utilisée dans les
# intitulés d'offres : "Stage" en tête, ou suivi d'un séparateur.
_STAGE_MOTIFS = (
    r"^stages?\b",                    # "Stage : Data Analyst"
    r"^stages?\s*[:\-–]",             # "Stage - Laborantin"
    r"\bstages?\s+[:\-–]\s+\w",       # "Offre / Stage - ..." (espaces exigés)
    r"\bstages?\s+en\s+alternance\b",
)


def detect_student_role_v135(title):
    """
    Détection élargie, sur l'intitulé seulement.

    Le test porte sur le titre et non sur la description : une annonce de
    poste fixe peut mentionner un programme de stages sans en être un.
    """
    n = base_gate.normalize(title)
    if not n:
        return False

    if any(base_gate.contains_phrase(n, m) for m in _STUDENT_MARQUEURS_V135):
        return True

    if any(re.search(motif, n) for motif in _STAGE_MOTIFS):
        return True

    return _DETECT_STUDENT_ROLE_ORIGINAL(title)


# ============================================================
# APPLICATION DE LA COUCHE
# ============================================================

@contextmanager
def _v133_patches():
    originals = {
        "_optional_master_sentence": gate_v132._optional_master_sentence,
        "_experience_optional_v132": gate_v132._experience_optional_v132,
        "_company_history_experience_v132":
            gate_v132._company_history_experience_v132,
        "detect_mandatory_master_v131": gate_v132.detect_mandatory_master_v131,
        "_explicit_vie_offer": gate_v132._explicit_vie_offer,
    }
    originaux_base = {
        "detect_language_gaps": base_gate.detect_language_gaps,
        "detect_student_role": base_gate.detect_student_role,
    }

    gate_v132._optional_master_sentence = _optional_master_sentence_v133
    gate_v132._experience_optional_v132 = _experience_optional_v133
    gate_v132._company_history_experience_v132 = _company_history_experience_v133
    gate_v132.detect_mandatory_master_v131 = detect_mandatory_master_v133
    gate_v132._explicit_vie_offer = _explicit_vie_offer_v133
    base_gate.detect_language_gaps = detect_language_gaps_v134
    base_gate.detect_student_role = detect_student_role_v135

    try:
        yield
    finally:
        for name, value in originals.items():
            setattr(gate_v132, name, value)
        for name, value in originaux_base.items():
            setattr(base_gate, name, value)


def detect_required_experience_years_v133(text):
    with _v133_patches():
        return gate_v132.detect_required_experience_years_v132(text)


def evaluate_application_gate(job, match_result):
    with _v133_patches():
        gate = gate_v132.evaluate_application_gate(job, match_result)

    gate = dict(gate)
    gate["gate_version"] = GATE_VERSION
    return gate


def apply_application_gate(scored_jobs):
    gated = []

    for job, match_result in scored_jobs:
        gate = evaluate_application_gate(job, match_result)
        gated.append((job, match_result, gate))

    gated.sort(key=base_gate.gate_sort_key, reverse=True)
    return gated


partition_gate_results = base_gate.partition_gate_results
gate_summary = base_gate.gate_summary
export_application_gate = base_gate.export_application_gate
STATUS_LABELS = base_gate.STATUS_LABELS
STATUS_ORDER = base_gate.STATUS_ORDER
gate_sort_key = base_gate.gate_sort_key

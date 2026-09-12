"""
JOB HUNTER BELGIUM
CATEGORIES DE POSTES - VERSION 1.0

Trois grandes familles, trois sous-categories chacune. Le decoupage est
celui demande par le candidat — bachelier en chimie, specialisation Business
Data Analysis — et non une taxonomie generique du marche : il sert a lui
dire ce que demandent les postes qu'il peut viser, pas a classer tout
l'emploi belge.

    LAB      qc            controle qualite, analyses de routine
             rd            recherche, developpement analytique
             bio           microbiologie, biologie, culture cellulaire

    DATA     analyse       data / business analyst, BI, reporting
             ingenierie    data engineer, ETL, bases de donnees
             science       data science, statistiques, apprentissage

    PHARMA   qa            assurance qualite, conformite, validation
             production    fabrication, operateurs, process — en pharma
                           ou en chimie industrielle
             reglementaire affaires reglementaires, pharmacovigilance

Tout le reste est AUTRE : compte, jamais conseille.

Comment une offre est classee
-----------------------------
Le TITRE decide en premier : c'est la ou l'employeur nomme le poste. La
description ne sert qu'a departager — par exemple, un « Operateur de
production » n'est PHARMA que si l'annonce parle de pharma, de GMP ou de
sterile ; sinon c'est un operateur d'usine, et il va dans AUTRE.

Une offre n'a qu'une categorie. Quand plusieurs motifs correspondent, le
plus specifique l'emporte : « Data analyst laboratoire » est DATA/analyse,
pas LAB/qc, parce que le mot « data analyst » nomme le metier et
« laboratoire » nomme le contexte.

Frontieres de mots partout — le defaut recurrent du projet. « QA » ne doit
pas matcher « Qatar », « bio » ne doit pas matcher « biographie ».
"""

from __future__ import annotations

import re
import unicodedata


CATEGORIES_VERSION = "1.0"

FAMILLES = ("LAB", "DATA", "PHARMA")

LIBELLES = {
    "LAB": "Laboratoire",
    "DATA": "Données",
    "PHARMA": "Pharma, chimie & qualité",
    "AUTRE": "Hors cible",
    "LAB/qc": "Contrôle qualité",
    "LAB/rd": "R&D et développement analytique",
    "LAB/bio": "Microbiologie et biologie",
    "DATA/analyse": "Analyse et BI",
    "DATA/ingenierie": "Ingénierie data",
    "DATA/science": "Data science et statistiques",
    "PHARMA/qa": "Assurance qualité et validation",
    "PHARMA/production": "Production pharmaceutique",
    "PHARMA/reglementaire": "Affaires réglementaires",
}


def _plat(texte: str) -> str:
    """Minuscules, sans accents, espaces normalises."""
    t = unicodedata.normalize("NFKD", str(texte or "").lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", t).strip()


def _borne(motif: str) -> re.Pattern:
    return re.compile(r"(?<![a-z0-9])(?:" + motif + r")(?![a-z0-9])", re.I)


# ------------------------------------------------------------------
# Motifs sur le TITRE, du plus specifique au plus general
# ------------------------------------------------------------------
# L'ordre compte : la premiere correspondance gagne. DATA passe avant LAB
# parce qu'un « data analyst laboratoire » est un analyste data ; PHARMA/qa
# passe avant LAB/qc parce que « assurance qualite » est plus specifique
# que « qualite ».
_TITRE = (
    # DATA — le metier est nomme sans ambiguite
    ("DATA/science", _borne(
        r"data scientist|scientifique des donnees|machine learning|"
        r"deep learning|statisticien(?:ne)?|biostatisti\w*|"
        r"ai engineer|ml engineer|ingenieur ia")),
    ("DATA/ingenierie", _borne(
        r"data engineer|ingenieur data|data architect|etl developer|"
        r"database administrator|dba|sql developer|developpeur sql|"
        r"data platform|big data")),
    ("DATA/analyse", _borne(
        r"data analyst|analyste (?:de )?donnees|business analyst|"
        r"bi analyst|analyste bi|business intelligence|power bi|"
        r"reporting analyst|data steward|master data|data reviewer|"
        r"analytics|data officer|data quality|"
        # « business analyste », « data analist » : les annonces belges
        # ecrivent le metier en francais ou en neerlandais, pas seulement
        # en anglais. Mesure : 16 offres perdues sur ces deux formes.
        r"business analyste|analyste business|data analiste?|"
        r"data functional analyst|analyste data")),

    # PHARMA — reglementaire et QA avant tout ce qui contient « qualite »
    ("PHARMA/reglementaire", _borne(
        r"regulatory|reglementaire|pharmacovigilance|drug safety|"
        r"regulatory affairs|affaires reglementaires|dossier d'?enregistrement|"
        r"cmc|medical writer")),
    ("PHARMA/qa", _borne(
        r"assurance qualite|quality assurance|qa officer|qa specialist|"
        r"qa manager|qa engineer|qa associate|qa technician|"
        r"quality officer|quality specialist|quality engineer|"
        r"quality manager|quality compliance|compliance officer|"
        r"validation|qualification|csv|qualite fournisseur|"
        r"quality systems?|qms|gmp officer|responsable qualite|"
        r"quality coordinator|deviation|capa|batch release|"
        r"qualified person|personne qualifiee|qp|"
        # Mesure du 13 septembre 2026 : « assistant qualite » (13),
        # « quality assistant » (7), « quality analyst » (6), « technicien
        # qa » — des roles qualite que rien ne captait.
        r"assistante? qualite|quality assistant|quality analyst|"
        r"analyste qualite|ingenieur(?:e)? qualite|quality technician|"
        r"technicien(?:ne)? qa|qa")),

    # LAB — le laboratoire est nomme
    ("LAB/bio", _borne(
        r"microbiolog\w*|microbio|biolog\w*|cell culture|culture cellulaire|"
        r"bioanaly\w*|biotechnolog\w*|virolog\w*|immunolog\w*|"
        r"histolog\w*|technologue de laboratoire medical|"
        r"laboratoire medical|clinical lab|laboratorium technolo\w*")),
    ("LAB/rd", _borne(
        r"r&d|r & d|recherche et developpement|research and development|"
        r"research scientist|scientist|chercheur|chercheuse|"
        r"developpement analytique|analytical development|"
        r"formulation|method development|developpement de methodes")),
    ("LAB/qc", _borne(
        r"controle qualite|quality control|qc analyst|qc technician|"
        r"qc lab|qc specialist|analyste qc|technicien qc|"
        r"laborantin?e?s?|laborant\w*|technicien(?:ne)? de laboratoire|"
        r"lab technician|laboratory technician|technicien labo|"
        r"analyste (?:de )?laboratoire|lab analyst|laboratory analyst|"
        r"technicien chimiste|chimiste|chemist|analytical chemist|"
        r"technicien en chimie|technicien d'?analyse|"
        # « Controleur qualite » (60 offres), « inspecteur qualite » (9),
        # « quality controller » : ils controlent, ils vont en QC.
        r"controleu(?:r|se) qualite|inspecteur(?:\.trice|rice)? qualite|"
        r"quality controller|quality inspector|technicien(?:ne)? qualite|"
        r"technicien de laboratoire|laboratory|laboratoire|labo")),

    # PHARMA/production — seulement avec un contexte pharma (voir plus bas)
    ("PHARMA/production?", _borne(
        r"operateur|operatrice|operator|production|fabrication|"
        r"manufacturing|process|filling|conditionnement|packaging|"
        r"aseptique|sterile|remplissage|technicien de production|"
        r"process technician|manufacturing technician")),
)

# Contexte pharma OU chimie exige pour la production. Sans lui, un
# operateur de production est un operateur d'usine quelconque.
#
# La chimie industrielle en fait partie parce que c'est le diplome du
# candidat : un « operator chemie » ou un operateur de site petrochimique
# est dans sa cible, un operateur de scierie non.
_CONTEXTE_PHARMA = _borne(
    r"chimi\w*|chemi\w*|chemical|petrochim\w*|raffin\w*|"
    r"pharma\w*|farma\w*|gmp|bpf|sterile|aseptique|aseptic|biotech\w*|"
    r"vaccin\w*|medicament\w*|geneesmiddel\w*|api|clean ?room|salle blanche|"
    r"gsk|pfizer|ucb|takeda|jnj|janssen|novartis|sanofi|baxter|"
    r"catalent|thermo fisher|lonza|kaneka|eurogentec|univercells")


def categoriser(titre: str, description: str = "") -> str:
    """
    Categorie d'une offre : « FAMILLE/sous » ou « AUTRE ».

    Le titre decide. La description n'intervient que pour confirmer le
    contexte pharma d'un poste de production.
    """
    t = _plat(titre)
    if not t:
        return "AUTRE"

    for categorie, motif in _TITRE:
        if not motif.search(t):
            continue
        if categorie == "PHARMA/production?":
            contexte = _plat(description)[:3000]
            if _CONTEXTE_PHARMA.search(t) or _CONTEXTE_PHARMA.search(contexte):
                return "PHARMA/production"
            return "AUTRE"
        return categorie

    return "AUTRE"


def famille(categorie: str) -> str:
    return categorie.split("/", 1)[0] if "/" in categorie else categorie


def sous_categories(fam: str) -> list[str]:
    return [c for c, _ in _TITRE
            if c.startswith(fam + "/")
            ] if fam != "PHARMA" else [
        "PHARMA/reglementaire", "PHARMA/qa", "PHARMA/production"]

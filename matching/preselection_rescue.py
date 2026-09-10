"""
JOB HUNTER BELGIUM
SAUVETAGE DE PRÉ-SÉLECTION - VERSION 1.0

Le problème, mesuré le 22/08/2026
---------------------------------
    offres actives                        5 430
    description < 300 caractères          4 711   (86,8 %)
    enrichissement réussi                   591

Le pipeline n'enrichit que 11 % de ce qu'il collecte, et
`select_candidate_jobs()` décide qui sera enrichi à partir de
`core_relevance`, calculé sur ces descriptions maigres — souvent 160 à 280
caractères de métadonnées Actiris sans une ligne d'annonce.

D'où un cercle vicieux : une offre mal décrite n'obtient jamais sa
description, donc ne peut jamais être scorée correctement.

Mesure de l'impact
------------------
452 offres ont un intitulé métier et moins de 300 caractères. La
pré-sélection n'en retient que 4. Sur un échantillon de 12 enrichies à la
main, 6 sont passées de 0 à plus de 50 :

    0.0 -> 64.4   Technicien Qualité & Production Béton
    0.0 -> 61.8   Technicien(ne) de laboratoire
    0.0 -> 61.8   Assistant laboratoire en alimentaire
    0.0 -> 50.0   Support Laboratoire Polyvalent

Ce que fait ce module
---------------------
Il ajoute une seconde porte d'entrée vers l'enrichissement : un intitulé
qui contient un terme métier du profil suffit, même si le pré-score le
rejette. Le Matcher, le Gate et la Queue ne changent pas — une offre
sauvée est simplement enrichie, puis scorée normalement sur son vrai texte.

Le sauvetage est volontairement fondé sur l'INTITULÉ seul. Le titre est le
seul champ fiable quand la description manque, et il est court : le risque
de faux positif y est bien plus faible que dans un texte complet.

Coût
----
~448 enrichissements supplémentaires par run, soit environ 9 minutes à la
première collecte et 30 secondes ensuite, le cache étant réutilisé.
"""

from __future__ import annotations

import re

from config.profile import (
    CHEMISTRY_LAB_CORE_ANCHORS,
    CHEMISTRY_LAB_SEARCH_CONCEPTS,
    DATA_SEARCH_CONCEPTS,
)


RESCUE_VERSION = "1.0"

# Longueur en dessous de laquelle une description est considérée comme
# absente : ce ne sont que des métadonnées, pas une annonce.
THIN_DESCRIPTION_CHARS = 300


def _normalize(value: str) -> str:
    import unicodedata
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", text).strip()


def _bounded(terme: str, texte: str) -> bool:
    """
    Frontières lexicales, comme partout ailleurs dans le projet.

    Sans elles, "labo" matcherait "élaboration" et "qa" matcherait
    "qatar" : c'est la famille de défauts qui a produit le bug V.I.E.
    """
    n = _normalize(terme)
    if not n or not texte:
        return False
    corps = r"\s+".join(re.escape(p) for p in n.split())
    return re.search(rf"(?<![a-z0-9]){corps}(?![a-z0-9])", texte) is not None


def _construire_termes():
    """
    Vocabulaire de sauvetage, tiré de config/profile.py.

    On ne recopie pas de liste ici : les termes viennent des concepts et
    des ancres déjà validés par le Matcher, pour qu'un enrichissement du
    profil profite automatiquement au sauvetage.
    """
    termes = set()

    for ancre in CHEMISTRY_LAB_CORE_ANCHORS:
        n = _normalize(ancre)
        if len(n) >= 4:
            termes.add(n)

    for concepts in (CHEMISTRY_LAB_SEARCH_CONCEPTS, DATA_SEARCH_CONCEPTS):
        for definition in concepts.values():
            for langue in ("fr", "en", "nl"):
                for expression in definition.get(langue) or []:
                    n = _normalize(expression)
                    if len(n) >= 5:
                        termes.add(n)

    # Termes belges absents des concepts, constatés sur les données réelles.
    # "technieker" est la forme belge ; les Pays-Bas disent "technicus".
    termes.update({
        "technieker", "procestechnieker", "kwaliteitscontroleur",
        "kwaliteitsoperator", "kwaliteitsmedewerker", "onderzoeker",
        "staalnemer", "monsternemer", "laborante", "laborantin",
        "technicien qc", "technicien qa", "technicien qualite",
        "assistant laboratoire", "support laboratoire",
    })

    return tuple(sorted(termes, key=len, reverse=True))


CORE_TITLE_TERMS = _construire_termes()


def has_core_title(title) -> bool:
    """L'intitulé contient-il un terme métier du profil ?"""
    n = _normalize(title)
    if not n:
        return False
    return any(_bounded(terme, n) for terme in CORE_TITLE_TERMS)


def description_is_thin(job) -> bool:
    texte = (
        getattr(job, "detail_matching_text", None)
        or getattr(job, "description", None)
        or ""
    )
    return len(str(texte)) < THIN_DESCRIPTION_CHARS


def should_rescue(job, result) -> bool:
    """
    Faut-il enrichir cette offre alors que le pré-score la rejette ?

    Trois conditions, pour rester conservateur :
      - le pré-score ne l'a pas déjà retenue ;
      - sa description est trop maigre pour avoir été jugée équitablement ;
      - son intitulé porte un terme métier du profil.
    """
    if (result or {}).get("core_relevance"):
        return False
    if not description_is_thin(job):
        return False
    return has_core_title(getattr(job, "title", ""))


def partition_rescued(pre_scored_jobs):
    """
    Sépare les offres retenues par le pré-score de celles sauvées par
    l'intitulé. Le compte des secondes est journalisé par main.py.
    """
    retenues, sauvees = [], []
    for job, result in pre_scored_jobs:
        if (result or {}).get("core_relevance"):
            retenues.append((job, result))
        elif should_rescue(job, result):
            sauvees.append((job, result))
    return retenues, sauvees

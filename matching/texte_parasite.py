"""
JOB HUNTER BELGIUM
DETECTION DES TEXTES PARASITES - VERSION 1.0

Le probleme
-----------
Une page d'offre contient bien plus que l'offre. Elle contient aussi un fil
d'Ariane, un pied de page, et surtout un bloc « offres similaires » : une
liste d'AUTRES postes, avec leurs entreprises, leurs regions et leurs
avantages.

Quand l'extraction rate le bon bloc, c'est cette liste qui est enregistree
comme description. Le resultat est pire qu'une absence de texte : sur une
offre intitulee « HR Data Analyst », le texte stocke commencait par
« Senior Data analist Liantis Bruges » — un autre poste, une autre
entreprise, une autre ville. Le moteur de correspondance lisait alors des
dizaines de metiers sans rapport et notait l'offre sur eux.

Mesure du 9 septembre 2026 : 218 offres Jobat actives etaient dans ce cas,
avec une longueur mediane de 3 494 caracteres. Elles passaient donc tous les
controles de longueur, y compris le seuil du moteur de verdict.

Les signaux retenus
-------------------
Chacun a ete mesure sur les 5 428 textes enrichis de la base avant d'etre
retenu, et chacun separe parfaitement :

    « Depuis N jours » repete       218 Jobat  |  0 ailleurs
    « Interim option contrat fixe » 132 Jobat  |  0 ailleurs
    fil d'Ariane « : N jobs »         7 Jobat  |  0 ailleurs

Un signal a ete ECARTE malgre son apparente evidence : « Duree indeterminee »
repete, qui frappait 28 offres d'autres sources ou l'expression est
legitimement citee plusieurs fois. Un detecteur qui se trompe efface du vrai
texte ; mieux vaut en laisser passer que d'en detruire.

Ce que le module ne fait pas
----------------------------
Il ne repare pas le texte. Un bloc de liste ne contient pas l'offre : il n'y
a rien a sauver dedans. Le module dit seulement « ceci n'est pas une
description », et laisse l'appelant decider.
"""

from __future__ import annotations

import re


TEXTE_PARASITE_VERSION = "1.0"

# Nombre d'occurrences a partir duquel un marqueur cesse d'etre une mention
# et devient une enumeration. Une annonce peut dire une fois « depuis 3
# jours » ; elle ne le dit pas trois fois.
_SEUIL_REPETITION = 3

# « Depuis 5 jours », « Sinds 3 dagen » : l'anciennete de publication, une
# ligne par offre listee.
_ANCIENNETE_REPETEE = re.compile(
    r"(?:depuis|sinds)\s+\d+\s+(?:jours?|dag(?:en)?|mois|maand(?:en)?)", re.I)

# Etiquette de contrat propre aux listes de resultats.
_ETIQUETTE_CONTRAT = re.compile(
    r"int[eé]rim\s+option\s+contrat\s+fixe|"
    r"interim\s+optie\s+vast\s+contract", re.I)

# Fil d'Ariane complet : « Offres d'emploi X > Y > Z : 28 jobs ».
_FIL_D_ARIANE = re.compile(
    r"^\s*(?:offres?\s+d'emploi|jobs?\s+in|vacatures)\b[^\n]{0,300}?"
    r":\s*\d+\s*(?:jobs?|vacatures)\s*$", re.I)


def raison_parasite(texte: str) -> str:
    """
    Dit pourquoi un texte n'est pas une description, ou renvoie une chaine
    vide s'il en est une.

    La raison est rendue lisible telle quelle : elle est destinee a etre
    stockee dans detail_enrichment_error, ou elle explique a la relecture
    pourquoi l'offre n'a pas de texte.
    """
    texte = str(texte or "")
    if not texte.strip():
        return ""

    if _FIL_D_ARIANE.match(texte.strip()):
        return "BLOC_NAVIGATION : fil d'Ariane, pas une description"

    repetitions = len(_ANCIENNETE_REPETEE.findall(texte))
    if repetitions >= _SEUIL_REPETITION:
        return (f"BLOC_OFFRES_SIMILAIRES : {repetitions} mentions "
                f"d'anciennete de publication")

    etiquettes = len(_ETIQUETTE_CONTRAT.findall(texte))
    if etiquettes >= _SEUIL_REPETITION:
        return (f"BLOC_OFFRES_SIMILAIRES : {etiquettes} etiquettes de "
                f"contrat de liste")

    return ""


def est_texte_parasite(texte: str) -> bool:
    """Vrai si le texte est un bloc de navigation ou une liste d'offres."""
    return bool(raison_parasite(texte))

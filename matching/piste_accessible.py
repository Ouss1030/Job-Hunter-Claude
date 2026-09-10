"""
JOB HUNTER BELGIUM
PISTES DE CANDIDATURE - VERSION 1.0

Pourquoi separer les pistes
---------------------------
Le candidat est qualifie pour bien plus que sa specialite : un bachelier en
chimie industrielle avec trois ans de QC peut occuper la plupart des postes
qui n'exigent pas un diplome superieur.

Mais tout melanger serait contre-productif. Si un poste d'operateur de
production apparait a cote d'un poste de QC en pharma avec le meme rang, la
liste devient illisible et les vraies cibles se noient.

D'ou trois pistes distinctes, consultees separement :

    SPECIALITE            QC, laboratoire, chimie, data — le coeur de cible
    ACCESSIBLE_INDUSTRIE  production, conditionnement, procedes : pas la
                          specialite, mais le bagage industriel sert
    ACCESSIBLE_LARGE      aucune barriere de diplome, de langue ni
                          d'experience, mais le metier est etranger au profil

La quatrieme valeur, HORS_PORTEE, correspond a un verdict FERMEE.

Ce que ce module ne fait pas
-----------------------------
Il ne note pas. Le rang a l'interieur d'une piste reste le travail du
scoring ; ce module dit seulement DANS QUELLE LISTE une offre doit figurer.

Separer les deux evite le defaut classique : gonfler un score pour faire
remonter une offre, et ne plus rien comprendre au classement ensuite.
"""

from __future__ import annotations

import re

from matching.basic_matcher_v51 import TARGET_JOB_FAMILIES, find_matches
from matching.verdict import ACCESSIBLE, A_VERIFIER, FERMEE, INCONNU, evaluer


PISTES_VERSION = "1.0"

SPECIALITE = "SPECIALITE"
ACCESSIBLE_INDUSTRIE = "ACCESSIBLE_INDUSTRIE"
ACCESSIBLE_LARGE = "ACCESSIBLE_LARGE"
HORS_PORTEE = "HORS_PORTEE"
INDETERMINE = "INDETERMINE"


# ------------------------------------------------------------------
# Metiers industriels accessibles
# ------------------------------------------------------------------
# Expressions composees uniquement. Les mots isoles produisent du bruit :
# « preparateur » seul remonte « Coach Sportif / Preparateur Physique » et
# « Preparateur de Projets / Bureau d'Etudes », releves tous deux dans la
# base. C'est le meme piege que « technicien » qui remonterait
# « Technicien de surface ».
_INDUSTRIE = re.compile(
    r"(?<![a-z])("
    r"op[ée]rateur\s+(?:de\s+)?production|"
    r"op[ée]rateur\s+(?:de\s+)?(?:machine|ligne|conditionnement|fabrication)|"
    r"op[ée]rateur\s+(?:chimique|polyvalent)|"
    r"operator\s+productie|productiemedewerker|productieoperator|"
    r"procesoperator|chemisch\s+operator|machineoperator|"
    r"ouvrier\s+(?:de\s+)?production|agent\s+de\s+production|"
    r"technicien\s+(?:de\s+)?production|production\s+technician|"
    r"technicien\s+proc[ée]d[ée]s?|process\s+(?:technician|operator)|"
    r"pr[ée]parateur\s+de\s+commandes|orderpicker|"
    r"agent\s+de\s+conditionnement|conditionnement\s+pharmaceutique|"
    r"magasinier\s+industriel|"
    r"technicien\s+de\s+fabrication"
    r")(?![a-z])",
    re.I,
)

# Metiers ou le bagage chimie ne sert a rien et ou la penibilite ou la
# specialisation rendent la candidature peu credible. Ils restent
# ACCESSIBLE_LARGE, jamais ACCESSIBLE_INDUSTRIE.
_HORS_INDUSTRIE = re.compile(
    r"(?<![a-z])("
    r"pr[ée]parateur\s+physique|coach\s+sportif|"
    r"technicien\s+de\s+surface|nettoyage|"
    r"couturier|coiffeur|boulanger|boucher|cuisinier|serveur|"
    r"chauffeur|livreur|d[ée]m[ée]nageur"
    r")(?![a-z])",
    re.I,
)


# Marqueurs de specialite : leur seule presence dans le titre suffit a
# garder l'offre dans la piste principale, meme si aucune expression complete
# n'est reconnue.
#
# Sans cela, « Technicien DE PRODUCTION QC » basculait dans la piste
# industrielle : les mots intercales cassent l'expression « technicien qc »,
# donc aucune famille ne matche, et « technicien de production » l'emporte.
# Enumerer toutes les variantes possibles serait sans fin ; un marqueur
# suffit.
_MARQUEURS_SPECIALITE = re.compile(
    r"(?<![a-z])("
    r"qc|qa|quality|qualit[ée]|kwaliteit|"
    r"laborant|laboratoire|laboratorium|laboratory|"
    r"chimi|chemi|scheikund|"
    r"gmp|bpf|analytique|analytisch"
    r")(?![a-z])",
    re.I,
)


def famille_specialite(titre: str) -> str:
    """Nom de la famille metier reconnue dans le titre, sinon chaine vide."""
    for nom, termes in TARGET_JOB_FAMILIES.items():
        if find_matches(titre or "", termes):
            return nom
    return ""


def est_industrie_accessible(titre: str) -> bool:
    titre = titre or ""
    if _HORS_INDUSTRIE.search(titre):
        return False
    return bool(_INDUSTRIE.search(titre))


def piste(titre: str, texte: str) -> tuple[str, str]:
    """
    Piste de l'offre, et la raison en clair.

    L'ordre compte : la specialite l'emporte toujours, meme si le titre
    contient aussi un terme industriel. Un « Technicien de production QC »
    reste un poste QC.
    """
    v = evaluer(texte)

    famille = famille_specialite(titre)
    if famille and v.verdict != FERMEE:
        return SPECIALITE, f"famille {famille}"

    if v.verdict == FERMEE:
        motif = v.barrieres[0].message if v.barrieres else "barrière"
        return HORS_PORTEE, motif

    if v.verdict == INCONNU:
        return INDETERMINE, "texte insuffisant pour se prononcer"

    if est_industrie_accessible(titre):
        # Un marqueur de spécialité dans le titre l'emporte sur le terme
        # industriel : « Technicien de production QC » est un poste QC.
        marqueur = _MARQUEURS_SPECIALITE.search(titre or "")
        if marqueur:
            return SPECIALITE, f"marqueur « {marqueur.group(1).lower()} »"
        return ACCESSIBLE_INDUSTRIE, "métier industriel sans barrière"

    if famille:
        # Famille reconnue mais verdict INCONNU traite plus haut : ici le
        # titre matche et rien ne bloque.
        return SPECIALITE, f"famille {famille}"

    return ACCESSIBLE_LARGE, "aucune barrière, métier hors profil"


def classer(offres) -> dict[str, list]:
    """
    Range une liste de (titre, texte) par piste.

    Renvoie un dictionnaire piste -> liste de (titre, raison), dans l'ordre
    de lecture recommande : la specialite d'abord.
    """
    resultat: dict[str, list] = {
        SPECIALITE: [], ACCESSIBLE_INDUSTRIE: [],
        ACCESSIBLE_LARGE: [], HORS_PORTEE: [], INDETERMINE: [],
    }
    for titre, texte in offres:
        nom, raison = piste(titre, texte)
        resultat[nom].append((titre, raison))
    return resultat


ORDRE_LECTURE = (SPECIALITE, ACCESSIBLE_INDUSTRIE, ACCESSIBLE_LARGE,
                 INDETERMINE, HORS_PORTEE)

LIBELLES = {
    SPECIALITE: "Votre spécialité — QC, laboratoire, chimie, data",
    ACCESSIBLE_INDUSTRIE: "Accessible — production et procédés industriels",
    ACCESSIBLE_LARGE: "Accessible — aucun obstacle, mais hors de votre domaine",
    INDETERMINE: "À enrichir — pas assez de texte pour juger",
    HORS_PORTEE: "Hors de portée — barrière identifiée",
}

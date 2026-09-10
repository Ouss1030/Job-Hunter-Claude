"""
JOB HUNTER BELGIUM
STATISTIQUES DE MARCHE - VERSION 1.0

Que disent les offres collectees du marche belge pour ce profil ?

Le projet accumule plusieurs milliers d'offres actives et n'en exploite
qu'une centaine. Le reste n'est pas du dechet : c'est un echantillon du
marche accessible, et il repond a des questions qu'aucun autre module ne
pose — quelle competence ouvrirait le plus de portes, laquelle sert deja le
plus souvent, qui recrute, ou, dans quelle langue.

Le perimetre : les offres OUVERTES
----------------------------------
Toutes les mesures portent sur les offres qu'aucune barriere prouvee ne
ferme (verdict ACCESSIBLE ou A_VERIFIER). Compter sur l'ensemble melangerait
un marche atteignable et un marche qui ne l'est pas, et la moyenne des deux
ne decrit ni l'un ni l'autre.

Ce que ces chiffres sont, et ne sont pas
---------------------------------------
Ils comptent des MENTIONS dans le texte des annonces, pas des exigences
formelles. Une offre qui cite HACCP au detour d'une phrase compte autant
qu'une offre qui l'exige. C'est une limite assumee : extraire une exigence
formelle demanderait une analyse par annonce que rien ne garantit plus juste.

Le classement reste utile parce qu'il est relatif : si HACCP est mentionne
six fois plus souvent qu'Empower, l'ordre de priorite tient, meme si les
valeurs absolues surestiment.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from pathlib import Path

from matching.verdict import evaluer


MARCHE_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"

# En dessous, un comptage n'est plus qu'un accident statistique.
_SEUIL_SIGNIFICATIF = 3


def _ouvrir(chemin: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro", uri=True)


def _part(nombre: int, total: int) -> float:
    return round(100.0 * nombre / total, 1) if total else 0.0


def analyser_marche(chemin_base: Path | None = None,
                    limite: int | None = None) -> dict:
    """
    Portrait du marche accessible, calcule a partir des offres actives.

    `limite` sert aux tests et aux apercus : le calcul complet evalue
    plusieurs milliers d'annonces et prend une trentaine de secondes.
    """
    chemin = chemin_base or DB_PATH
    if not chemin.exists():
        return {"erreur": f"base introuvable : {chemin}"}

    connexion = _ouvrir(chemin)
    try:
        requete = (
            "SELECT title, company, location, source, contract_type, "
            "       COALESCE(detail_matching_text, description, '') "
            "FROM raw_jobs WHERE is_active = 1"
        )
        if limite:
            requete += f" LIMIT {int(limite)}"
        lignes = connexion.execute(requete).fetchall()
    finally:
        connexion.close()

    manques = Counter()
    atouts = Counter()
    employeurs = Counter()
    lieux = Counter()
    sources = Counter()
    contrats = Counter()
    verdicts = Counter()
    ouvertes = 0

    for titre, societe, lieu, source, contrat, texte in lignes:
        resultat = evaluer(f"{titre or ''}\n{texte}")
        verdicts[resultat.verdict] += 1
        if resultat.verdict not in ("ACCESSIBLE", "A_VERIFIER"):
            continue

        ouvertes += 1
        for terme in resultat.manques:
            manques[str(terme)] += 1
        for competence in resultat.atouts:
            atouts[str(competence)] += 1
        if societe:
            employeurs[str(societe).strip()] += 1
        if lieu:
            lieux[_ville(lieu)] += 1
        if source:
            sources[str(source)] += 1
        if contrat:
            contrats[str(contrat).strip()] += 1

    return {
        "version": MARCHE_VERSION,
        "offres_actives": len(lignes),
        "offres_ouvertes": ouvertes,
        "verdicts": dict(verdicts),
        "a_acquerir": _classer(manques, ouvertes),
        "a_valoriser": _classer(atouts, ouvertes),
        "employeurs": _classer(employeurs, ouvertes, seuil=2),
        "lieux": _classer(lieux, ouvertes, seuil=2),
        "sources": _classer(sources, ouvertes, seuil=1),
        "contrats": _classer(contrats, ouvertes, seuil=2),
    }


def _ville(localisation: str) -> str:
    """
    Ville seule, sans le code postal ni l'adresse.

    Les sources ecrivent « Avenue Jules Bordet 168 1140 Bruxelles Telework
    No telework ». Compter ces chaines entieres donnerait une liste ou
    chaque offre est unique, donc sans aucune information.
    """
    brut = str(localisation or "").strip()
    for separateur in (",", "|", " - "):
        if separateur in brut:
            brut = brut.split(separateur)[0]
    mots = [m for m in brut.split() if not m.isdigit() and len(m) > 2]
    return " ".join(mots[-2:]) if mots else "inconnu"


def _classer(compteur: Counter, total: int, seuil: int = _SEUIL_SIGNIFICATIF,
             limite: int = 15) -> list[dict]:
    return [
        {"nom": nom, "offres": nombre, "part": _part(nombre, total)}
        for nom, nombre in compteur.most_common(limite)
        if nombre >= seuil
    ]

"""
JOB HUNTER BELGIUM
STATISTIQUES DE CANDIDATURE - VERSION 1.0

Que deviennent les candidatures une fois envoyees ?

Au 10 septembre 2026, la reponse est : rien, aucune n'a ete envoyee. Ce
module existe quand meme, et c'est deliberе : une statistique de delai ou de
taux de reponse ne vaut que si elle commence a compter au premier envoi. La
construire apres coup obligerait a reconstituer des dates perdues.

Il rend donc aujourd'hui un etat vide EXPLICITE — « aucune candidature
envoyee » — et non des zeros qui se liraient comme un echec.

Ce qu'il mesurera
-----------------
    envoyees            nombre, par filiere de CV et par source
    taux de reponse     part des candidatures ayant recu un retour
    delai de reponse    jours entre l'envoi et le premier retour
    entonnoir           envoyee -> reponse -> entretien -> offre

Ce qu'il ne fera jamais
-----------------------
Marquer une candidature comme envoyee. Seul l'utilisateur le fait, et la
politique du projet est explicite la-dessus : APPLIED n'est jamais pose par
la machine. Ce module lit, il ne conclut pas a votre place.
"""

from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


CANDIDATURES_STATS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"

# Evenements qui marquent un envoi reel, par opposition a la simple
# preparation d'un dossier.
_ENVOI = ("APPLIED", "SENT", "SUBMITTED")

# Evenements qui marquent un retour de l'employeur.
_RETOUR = ("REPLIED", "RESPONSE", "INTERVIEW", "REJECTED", "OFFER",
           "PHONE_SCREEN")


def _ouvrir(chemin: Path) -> sqlite3.Connection:
    connexion = sqlite3.connect(f"{chemin.resolve().as_uri()}?mode=ro",
                                uri=True)
    connexion.row_factory = sqlite3.Row
    return connexion


def _date(valeur) -> datetime | None:
    brut = str(valeur or "")[:19]
    for forme in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(brut[:len(datetime.now().strftime(forme))],
                                     forme)
        except ValueError:
            continue
    return None


def analyser_candidatures(chemin_base: Path | None = None) -> dict:
    chemin = chemin_base or DB_PATH
    if not chemin.exists():
        return {"erreur": f"base introuvable : {chemin}"}

    connexion = _ouvrir(chemin)
    try:
        evenements = connexion.execute(
            "SELECT entity_id, event_type, status, event_at, source "
            "FROM application_events ORDER BY event_at"
        ).fetchall()
        entites = connexion.execute(
            "SELECT id, title, company, track FROM application_entities"
        ).fetchall()
    finally:
        connexion.close()

    types = Counter(str(e["event_type"]) for e in evenements)

    # Premier envoi et premier retour, par candidature.
    envois, retours = {}, {}
    for e in evenements:
        marqueur = f"{e['event_type']} {e['status']}".upper()
        cle = e["entity_id"]
        if any(x in marqueur for x in _ENVOI) and cle not in envois:
            envois[cle] = _date(e["event_at"])
        elif any(x in marqueur for x in _RETOUR) and cle not in retours:
            retours[cle] = _date(e["event_at"])

    if not envois:
        return {
            "version": CANDIDATURES_STATS_VERSION,
            "etat": "AUCUNE_CANDIDATURE_ENVOYEE",
            "message": ("Aucun envoi enregistre. Les compteurs de delai et de "
                        "taux de reponse commenceront au premier envoi."),
            "dossiers_suivis": len(entites),
            "evenements": dict(types),
            "envoyees": 0,
        }

    delais = [
        (retours[cle] - envois[cle]).days
        for cle in envois
        if cle in retours and envois[cle] and retours[cle]
    ]
    par_filiere = Counter(
        str(e["track"] or "?") for e in entites if e["id"] in envois)

    return {
        "version": CANDIDATURES_STATS_VERSION,
        "etat": "ACTIF",
        "dossiers_suivis": len(entites),
        "evenements": dict(types),
        "envoyees": len(envois),
        "avec_retour": len(delais),
        "taux_de_reponse": round(100.0 * len(delais) / len(envois), 1),
        "delai_median_jours": sorted(delais)[len(delais) // 2] if delais else None,
        "par_filiere": dict(par_filiere),
    }

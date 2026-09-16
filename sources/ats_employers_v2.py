"""
JOB HUNTER BELGIUM
REGISTRE DES EMPLOYEURS DECOUVERTS - VERSION 1.0

Un seul fichier, config/ats_employers_v2.json, tient tous les employeurs
trouves par le moteur de decouverte, quel que soit leur ATS :

    {"ats": "LEVER", "identifier": "deliverect", "label": "Deliverect",
     "enabled": true, "verified_at": "...", "jobs_total": 35, "jobs_be": 3,
     "discovered_by": "seed:tech", "career_url": "https://..."}

Les connecteurs de premiere generation (Greenhouse, Recruitee,
SmartRecruiters, Workday, SuccessFactors, Phenom) gardent leurs listes en
config/*_sources.py ; leur fonction enabled_companies() fusionne simplement
les entrees de ce fichier via fusionner(). Les connecteurs de seconde
generation (Lever, Ashby, Workable, Personio, JSONLD_SITES) lisent ce
fichier directement.

Regles
------
- Une entree n'est ecrite qu'apres validation (l'endpoint a repondu).
- jobs_be = 0 n'est pas une raison de desactiver : l'employeur peut
  publier demain. Seule une erreur repetee desactive (health).
- Une entree presente dans les deux listes (Python et JSON) : la liste
  Python gagne, le JSON n'ajoute que ce qui manque.
"""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path


ATS_EMPLOYERS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REGISTRY_PATH = PROJECT_ROOT / "config" / "ats_employers_v2.json"
_VERROU = threading.Lock()

# Comment chaque connecteur nomme son identifiant.
_CLE_IDENTIFIANT = {
    "WORKDAY_ATS": "tenant",
    "ORACLE_CLOUD": "host",
    "SUCCESSFACTORS_ATS": "host",
    "PHENOM_ATS": "host",
}


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def charger() -> dict:
    if not REGISTRY_PATH.exists():
        return {"schema_version": ATS_EMPLOYERS_VERSION, "updated_at": None, "employers": []}
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        data.setdefault("employers", [])
        return data
    except Exception:
        return {"schema_version": ATS_EMPLOYERS_VERSION, "updated_at": None, "employers": []}


def sauver(data: dict) -> Path:
    data["schema_version"] = ATS_EMPLOYERS_VERSION
    data["updated_at"] = _now()
    data["employers"] = sorted(data["employers"], key=lambda e: (e.get("ats", ""), str(e.get("label", "")).lower()))
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    return REGISTRY_PATH


def _cle(entree: dict) -> tuple:
    ident = entree.get("identifier")
    if isinstance(ident, dict):
        ident = json.dumps(ident, sort_keys=True)
    return (str(entree.get("ats", "")).upper(), str(ident).lower())


def employeurs(connecteur: str, actifs_seulement: bool = True) -> list[dict]:
    """
    Les entrees du registre pour un connecteur, dans la forme qu'il attend.
    """
    connecteur = str(connecteur).upper()
    sortie = []
    for e in charger()["employers"]:
        if str(e.get("connector") or e.get("ats") or "").upper() != connecteur:
            continue
        if actifs_seulement and not e.get("enabled", True):
            continue
        ident = e.get("identifier")
        ligne = {"label": e.get("label") or str(ident), "enabled": e.get("enabled", True),
                 "tracks": list(e.get("tracks") or []), "notes": e.get("notes", ""),
                 "_registre_v2": True}
        # Reglages par employeur que les connecteurs savent lire.
        for cle in ("max_jobs", "include_unknown", "lien_regex", "selecteur_contenu"):
            if e.get(cle) is not None:
                ligne[cle] = e[cle]
        if connecteur == "WORKDAY_ATS" and isinstance(ident, dict):
            ligne.update(tenant=ident.get("tenant"), wd=ident.get("wd"), site=ident.get("site"))
        elif connecteur == "ORACLE_CLOUD" and isinstance(ident, dict):
            ligne.update(host=ident.get("host"), site=ident.get("site"), lang=ident.get("lang") or "en")
        else:
            ligne[_CLE_IDENTIFIANT.get(connecteur, "identifier")] = ident
            if _CLE_IDENTIFIANT.get(connecteur):
                ligne["identifier"] = ident
        sortie.append(ligne)
    return sortie


def fusionner(connecteur: str, configures: list[dict]) -> list[dict]:
    """A appeler depuis enabled_companies() : ajoute ce que le registre connait en plus."""
    cle = _CLE_IDENTIFIANT.get(str(connecteur).upper(), "identifier")
    deja = set()
    for c in configures:
        v = c.get(cle) if cle != "tenant" else (c.get("tenant"), c.get("site"))
        deja.add(str(v).lower())
    ajouts = []
    for e in employeurs(connecteur):
        v = e.get(cle) if cle != "tenant" else (e.get("tenant"), e.get("site"))
        if str(v).lower() in deja:
            continue
        deja.add(str(v).lower())
        ajouts.append(e)
    return list(configures) + ajouts


def enregistrer(ats: str, connecteur: str | None, identifier, label: str, *,
                jobs_total: int | None, jobs_be: int | None, discovered_by: str,
                career_url: str | None = None, enabled: bool = True, notes: str = "") -> dict:
    """Ajoute ou met a jour une entree. Rend l'entree ecrite."""
    with _VERROU:
        return _enregistrer_sans_verrou(ats, connecteur, identifier, label, jobs_total=jobs_total,
                                        jobs_be=jobs_be, discovered_by=discovered_by,
                                        career_url=career_url, enabled=enabled, notes=notes)


def _enregistrer_sans_verrou(ats, connecteur, identifier, label, *, jobs_total, jobs_be,
                             discovered_by, career_url=None, enabled=True, notes="") -> dict:
    data = charger()
    entree = {
        "ats": str(ats).upper(), "connector": connecteur, "identifier": identifier,
        "label": label or str(identifier), "enabled": bool(enabled),
        "verified_at": _now(), "jobs_total": jobs_total, "jobs_be": jobs_be,
        "discovered_by": discovered_by, "career_url": career_url, "notes": notes,
    }
    cle = _cle(entree)
    for i, e in enumerate(data["employers"]):
        if _cle(e) == cle:
            e.update({k: v for k, v in entree.items() if k != "enabled" and not (k == "notes" and not v)})
            e["first_seen"] = e.get("first_seen") or entree["verified_at"]
            data["employers"][i] = e
            sauver(data)
            return e
    entree["first_seen"] = entree["verified_at"]
    data["employers"].append(entree)
    sauver(data)
    return entree


def resume() -> dict:
    from collections import Counter
    emp = charger()["employers"]
    return {
        "total": len(emp),
        "actifs": sum(1 for e in emp if e.get("enabled", True)),
        "par_ats": dict(Counter(e.get("ats") for e in emp)),
        "offres_be": sum(int(e.get("jobs_be") or 0) for e in emp),
    }

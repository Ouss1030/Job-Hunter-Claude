"""
JOB HUNTER BELGIUM
FEDERGON - GRAINES DE DECOUVERTE - VERSION 1.0

    python -m sources.federgon_seeds_v1            # ecrit config/discovery_seeds_federgon.json
    python -m sources.federgon_seeds_v1 --decouvrir  # puis passe les graines au moteur

Federgon est la federation des prestataires RH : interim, recrutement,
project sourcing, outplacement, formation. Sa page "Les membres" liste ses
membres avec leur site web — 465 domaines le 16 septembre 2026, dont les
petites agences regionales que personne ne recense ailleurs.

Ce module ne collecte aucune offre : il transforme l'annuaire en graines
pour sources/source_discovery_v1.py, qui trouve pour chaque domaine la page
carriere, l'ATS et la voie publique. Le cahier des charges :

    Federgon -> entreprise membre -> domaine -> page jobs -> ATSDetector -> collecte

Filtrage : les domaines d'outils et de reseaux (linkedin, facebook, google,
youtube...) et les domaines deja connus du registre sont ecartes.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

import requests


FEDERGON_SEEDS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SORTIE = PROJECT_ROOT / "config" / "discovery_seeds_federgon.json"
PAGE_MEMBRES = "https://federgon.be/fr/les-membres/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) JobHunter/federgon-seeds",
    "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8",
}

_RE_DOMAINE = re.compile(r"https?://(?:www\.)?([a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:be|com|eu|net|org|io|jobs|lu|fr|nl))/?", re.I)
_EXCLUS = {
    "federgon.be", "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "google.com", "googleapis.com", "gstatic.com", "w3.org", "schema.org", "cloudflare.com", "jquery.com",
    "vimeo.com", "hotjar.com", "cookiebot.com", "gravatar.com", "wp.com", "wordpress.org", "fonts.googleapis.com",
    "fonts.gstatic.com", "microsoft.com", "apple.com", "adobe.com", "typekit.net", "jsdelivr.net", "unpkg.com",
    "typo3.org", "drupal.org", "sitemanager.be", "webflow.com", "hubspot.com", "mailchimp.com", "vimeo.com",
}
_EXCLUS_SUFFIXES = (".gov", "europa.eu")


def extraire_domaines(html: str) -> list[str]:
    vus = []
    for d in _RE_DOMAINE.findall(html or ""):
        d = d.lower()
        if d in _EXCLUS or d in vus or any(d.endswith(s) for s in _EXCLUS_SUFFIXES):
            continue
        if d.count(".") > 2:
            continue
        vus.append(d)
    return vus


def graines(session=None) -> list[dict]:
    session = session or requests.Session()
    r = session.get(PAGE_MEMBRES, headers=HEADERS, timeout=30)
    r.raise_for_status()
    domaines = extraire_domaines(r.text)
    try:
        from sources.ats_employers_v2 import charger
        connus = set()
        for e in charger()["employers"]:
            for v in (e.get("career_url"), str(e.get("identifier"))):
                m = _RE_DOMAINE.search(str(v or ""))
                if m:
                    connus.add(m.group(1).lower())
    except Exception:
        connus = set()
    return [{"domaine": d, "label": d.split(".")[0].replace("-", " ").title(), "discovered_by": "federgon"}
            for d in domaines if d not in connus]


def ecrire(candidats: list[dict]) -> Path:
    SORTIE.write_text(json.dumps({
        "schema_version": FEDERGON_SEEDS_VERSION, "source": PAGE_MEMBRES,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "Membres Federgon (prestataires RH) a passer au moteur de decouverte.",
        "groups": {"federgon": [{"domaine": c["domaine"], "label": c["label"]} for c in candidats]},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return SORTIE


def main() -> int:
    import sys
    candidats = graines()
    chemin = ecrire(candidats)
    print(f"Federgon : {len(candidats)} domaines membres -> {chemin}")
    if "--decouvrir" in sys.argv:
        from sources.source_discovery_v1 import decouvrir
        decouvrir(candidats, dossier=PROJECT_ROOT / "exports" / "logs" /
                  f"discovery_federgon_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

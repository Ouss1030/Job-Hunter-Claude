"""
JOB HUNTER BELGIUM
DÉCOUVERTE D'ATS - OUTIL V1.0

Teste une liste d'entreprises contre les API publiques des ATS supportés,
et dit lesquelles sont joignables et avec combien d'offres belges.

    python -m diagnostics.ats_discovery
    python -m diagnostics.ats_discovery --secteur pharma
    python -m diagnostics.ats_discovery --entreprise ucb --entreprise solvay

⚠️ Appelle le réseau. Classé en catégorie RÉSEAU dans run_all.py.

Pourquoi cet outil
------------------
Greenhouse, Recruitee et SmartRecruiters sont des ATS : on interroge un
employeur, jamais « la Belgique ». Il n'existe aucun annuaire des
entreprises belges présentes sur chaque plateforme. La seule méthode fiable
est donc de tester un identifiant candidat contre chaque API.

Cet outil automatise ce test. Il ne devine pas les entreprises : la liste
CANDIDATS est écrite à la main, secteur par secteur, et se complète au fil
du temps. C'est un travail de recherche, pas de code.

Aucune écriture en base. Aucune modification de configuration : le résultat
est un rapport, à reporter manuellement dans config/*_sources.py après
vérification.
"""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import datetime
from pathlib import Path

import requests


LOG_DIR = Path(__file__).resolve().parent.parent / "exports" / "logs"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "application/json",
})

TIMEOUT = 8
DELAI = 0.15


# ============================================================
# CANDIDATS PAR SECTEUR
# ============================================================
# Entreprises belges, ou avec un site belge significatif, correspondant au
# profil : pharma / laboratoires / chimie / agroalimentaire d'un côté,
# data et BI de l'autre.

CANDIDATS = {
    "pharma": [
        "ucb", "gsk", "janssen", "takeda", "baxter", "pfizer", "sanofi",
        "msd", "novartis", "astrazeneca", "amgen", "catalent", "terumo",
        "galapagos", "argenx", "biocartis", "mithra", "celyad", "univercells",
        "bonetherapeutics", "iteos", "nyxoah", "onwardmedical", "imcyse",
        "precirix", "ziphius", "ncardia", "aseptic-technologies",
        "kaneka-eurogentec", "eurogentec", "prothya", "curia", "cordenpharma",
        "ecuphar", "animalcare", "thermofisher", "fujifilm",
    ],
    "laboratoires": [
        "eurofins", "sgs", "bureauveritas", "normec", "qualityassistance",
        "quality-assistance", "certech", "sciensano", "vito", "sirris",
        "materianova", "celabor", "cergroupe", "servaco", "alsglobal",
        "intertek", "carah",
    ],
    "chimie": [
        "solvay", "syensqo", "umicore", "tessenderlo", "prayon", "yara",
        "indaver", "aquafin", "recticel", "lhoist", "carmeuse", "vynova",
        "proviron", "oleon", "ecolab", "ineos", "chemours", "nyrstar",
        "totalenergies", "borealis", "basf", "evonik",
    ],
    "agroalimentaire": [
        "puratos", "lotusbakeries", "vandemoortele", "alpro", "danone",
        "milcobel", "terbeke", "spadel", "cocacola", "abinbev", "cargill",
        "barrycallebaut", "dosschemills", "delacre", "vionfood", "greenyard",
        "agristo", "clarebout", "ardo", "pinguinlutosa",
    ],
    "data": [
        "collibra", "smals", "soprasteria", "cegeka", "delaware", "acagroup",
        "ordina", "nrb", "tobania", "dataroots", "agilytic", "keyrus",
        "micropole", "isabelgroup", "odoo", "euroclear", "swift",
        "proximus", "telenet", "bpost", "colruytgroup", "statbel",
        "showpad", "teamleader", "silverfin", "deliverect", "materialise",
        # Ajouts du 20/08/2026 : ESN, cabinets data et éditeurs belges.
        "inetum", "devoteam", "capgemini", "accenture", "deloitte", "kpmg",
        "pwc", "ey", "arhs", "trasys", "gfi", "realdolmen", "inetumrealdolmen",
        "axians", "econocom", "spikes", "aca-it", "xplore-group", "craftworkz",
        "faktion", "ml6", "radix", "in-the-pocket", "showpad", "raito",
        "timeseries", "eura-nova", "euranova", "b12-consulting", "sopra",
        "cronos", "thefactory", "positive-thinking", "unifiedpost",
        "smartbit", "datacamp", "sentiance", "keyware", "bearingpoint",
        "sirris-data", "agifly", "nautadutilh", "digazu", "opinum",
    ],
}


# ============================================================
# SONDES PAR ATS
# ============================================================

def _variantes(nom: str):
    """Identifiants plausibles à partir d'un nom : le slug varie d'un ATS à l'autre."""
    base = re.sub(r"[^a-z0-9-]", "", nom.lower())
    vues, sortie = set(), []
    for v in (base, base.replace("-", ""), base.replace("-", "_")):
        if v and v not in vues:
            vues.add(v)
            sortie.append(v)
    return sortie


def sonde_recruitee(identifiant):
    url = f"https://{identifiant}.recruitee.com/api/offers/"
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        offres = (r.json() or {}).get("offers")
    except Exception:
        return None
    if offres is None:
        return None
    belges = [o for o in offres
              if str(o.get("country_code") or "").upper() == "BE"]
    return {"ats": "RECRUITEE", "identifiant": identifiant,
            "offres": len(offres), "belges": len(belges), "url": url}


def sonde_greenhouse(identifiant):
    url = f"https://boards-api.greenhouse.io/v1/boards/{identifiant}/jobs"
    try:
        r = SESSION.get(url, timeout=TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        offres = (r.json() or {}).get("jobs")
    except Exception:
        return None
    if offres is None:
        return None
    belges = [
        o for o in offres
        if "belg" in str((o.get("location") or {}).get("name", "")).lower()
    ]
    return {"ats": "GREENHOUSE", "identifiant": identifiant,
            "offres": len(offres), "belges": len(belges), "url": url}


def sonde_smartrecruiters(identifiant):
    """
    Limite connue de cette API : un identifiant inexistant renvoie
    HTTP 200 avec totalFound=0, exactement comme un employeur réel qui
    n'a aucune offre belge. Impossible de distinguer les deux.

    On ne signale donc un employeur que s'il a au moins une offre belge.
    Un employeur présent sur SmartRecruiters mais sans offre belge du jour
    passera inaperçu — c'est le compromis assumé, car l'inverse produirait
    un faux positif sur chaque nom testé.
    """
    url = f"https://api.smartrecruiters.com/v1/companies/{identifiant}/postings"
    try:
        r = SESSION.get(url, params={"country": "be", "limit": 100}, timeout=TIMEOUT)
    except Exception:
        return None
    if r.status_code != 200:
        return None
    try:
        payload = r.json() or {}
    except Exception:
        return None

    total = int(payload.get("totalFound") or 0)
    if total <= 0:
        return None

    return {"ats": "SMARTRECRUITERS", "identifiant": identifiant,
            "offres": total,
            "belges": total, "url": url}


SONDES = (sonde_recruitee, sonde_greenhouse, sonde_smartrecruiters)


# ============================================================
# DÉCOUVERTE
# ============================================================

def decouvrir(noms, verbose=True):
    trouves, testes = [], 0

    for nom in noms:
        deja_trouve = False
        for identifiant in _variantes(nom):
            if deja_trouve:
                break
            for sonde in SONDES:
                testes += 1
                resultat = sonde(identifiant)
                time.sleep(DELAI)
                if resultat is None:
                    continue
                resultat["nom"] = nom
                trouves.append(resultat)
                deja_trouve = True
                if verbose:
                    print(f"  {nom:<22} {resultat['ats']:<16} "
                          f"{resultat['offres']:>4} offres  "
                          f"BE={resultat['belges']}")
                break

    return trouves, testes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secteur", action="append",
                        choices=sorted(CANDIDATS),
                        help="limiter à un ou plusieurs secteurs")
    parser.add_argument("--entreprise", action="append",
                        help="tester un nom précis, hors liste")
    args = parser.parse_args()

    if args.entreprise:
        noms = args.entreprise
        titre = "noms fournis"
    else:
        secteurs = args.secteur or sorted(CANDIDATS)
        noms = [n for s in secteurs for n in CANDIDATS[s]]
        titre = ", ".join(secteurs)

    print("=" * 84)
    print("DÉCOUVERTE D'ATS")
    print("=" * 84)
    print(f"Secteurs   : {titre}")
    print(f"Entreprises: {len(noms)}")
    print()

    trouves, testes = decouvrir(noms)

    print()
    print("=" * 84)
    print(f"{len(trouves)} employeur(s) joignable(s) sur {len(noms)} testé(s) "
          f"({testes} requêtes)")
    print("=" * 84)

    avec_offres = [t for t in trouves if t["belges"] > 0]
    if avec_offres:
        print()
        print("AVEC DES OFFRES BELGES — à ajouter en priorité :")
        for t in sorted(avec_offres, key=lambda x: -x["belges"]):
            print(f"  {t['nom']:<22} {t['ats']:<16} BE={t['belges']:<4} "
                  f"identifiant={t['identifiant']}")

    sans = [t for t in trouves if t["belges"] == 0]
    if sans:
        print()
        print("JOIGNABLES MAIS SANS OFFRE BELGE AUJOURD'HUI :")
        for t in sans:
            print(f"  {t['nom']:<22} {t['ats']:<16} "
                  f"total={t['offres']:<4} identifiant={t['identifiant']}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = LOG_DIR / f"ats_discovery_{stamp}.json"
    chemin.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "companies_tested": len(noms),
        "requests": testes,
        "found": trouves,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("Rapport :", chemin)
    print()
    print("Vérifie chaque identifiant avant de l'ajouter à config/*_sources.py :")
    print("un board joignable ne garantit pas que les offres correspondent au profil.")


if __name__ == "__main__":
    main()

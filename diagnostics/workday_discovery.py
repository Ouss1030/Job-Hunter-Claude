"""
JOB HUNTER BELGIUM
DÉCOUVERTE DE TENANTS WORKDAY - OUTIL V1.0

    python -m diagnostics.workday_discovery
    python -m diagnostics.workday_discovery --tenant janssen --tenant ucb
    python -m diagnostics.workday_discovery --secteur pharma

⚠️ Appelle le réseau. Classé en catégorie RÉSEAU dans run_all.py.

Le problème
-----------
Une URL de site carrière Workday combine trois inconnues :

    https://<tenant>.wd<N>.myworkdayjobs.com/<site>

Tester toutes les combinaisons coûte cher : une vingtaine de numéros wd
multipliés par autant de noms de site plausibles, pour chaque entreprise.

La méthode
----------
Les codes de réponse permettent de séparer les deux inconnues, ce qui
ramène une recherche multiplicative à une recherche additive :

    HTTP 422  le couple tenant + wd n'existe pas
    HTTP 404  le couple tenant + wd EXISTE, seul le nom de site est faux
    HTTP 200  les trois éléments sont corrects

Phase 1 : on interroge chaque tenant avec un nom de site volontairement
          absurde. Un 404 identifie le bon numéro wd.
Phase 2 : on n'énumère les noms de site que pour les couples confirmés.

Vérifié le 20/08/2026 : gsk/wd5/GSKCareers -> 200,
gsk/wd5/MauvaisSite -> 404, gsk/wd3/GSKCareers -> 422.

Aucune écriture de configuration : le résultat est un rapport, à reporter
dans config/workday_sources.py après vérification.
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests


LOG_DIR = Path(__file__).resolve().parent.parent / "exports" / "logs"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "JobHunterBelgium/1.0 (recherche d'emploi personnelle)",
    "Accept": "application/json",
    "Content-Type": "application/json",
})

TIMEOUT = 7
DELAI = 0.12

SITE_SONDE = "ZzProbeSiteInexistant"

WD_NUMEROS = ("wd1", "wd2", "wd3", "wd5", "wd10", "wd12",
              "wd101", "wd103", "wd105")

CORPS = {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}


TENANTS = {
    "pharma": [
        "janssen", "jnj", "johnsoncontrols", "takeda", "ucb", "msd", "merck",
        "novartis", "astrazeneca", "amgen", "catalent", "terumo", "lonza",
        "bayer", "viatris", "organon", "teva", "fresenius", "roche",
        "boehringer", "abbvie", "abbott", "bd", "becton", "stryker",
        "medtronic", "zoetis", "elanco", "galapagosnv", "argenx",
        "thermofisher", "danaher", "sartorius", "eurofinsgroup",
    ],
    "chimie": [
        "solvay", "syensqo", "umicore", "basf", "evonik", "covestro",
        "arkema", "clariant", "lanxess", "dsm", "dsmfirmenich", "yara",
        "airliquide", "linde", "ineos", "borealis", "sabic", "lyondellbasell",
        "tessenderlo", "recticel", "aperam", "arcelormittal",
    ],
    "agro_conso": [
        "abinbev", "anheuserbuschinbev", "danone", "nestle", "unilever",
        "cargill", "mondelez", "pepsico", "cocacola", "kraftheinz",
        "barrycallebaut", "puratos", "lotusbakeries", "colruyt",
    ],
    "data": [
        "proximus", "telenet", "bpost", "euroclear", "swift", "kbc", "bnpparibas",
        "ing", "belfius", "deloitte", "pwc", "ey", "kpmg", "accenture",
        "capgemini", "atos", "sopra", "ibm", "sap", "oracle",
    ],
}


def _sonder(tenant: str, wd: str, site: str):
    url = f"https://{tenant}.{wd}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"
    try:
        r = SESSION.post(url, json=CORPS, timeout=TIMEOUT)
    except Exception:
        return None, None
    total = None
    if r.status_code == 200:
        try:
            total = (r.json() or {}).get("total")
        except Exception:
            total = None
    return r.status_code, total


def trouver_wd(tenant: str):
    """Phase 1 : un 404 signale que le couple tenant + wd existe."""
    for wd in WD_NUMEROS:
        code, _ = _sonder(tenant, wd, SITE_SONDE)
        time.sleep(DELAI)
        if code == 404:
            return wd
        if code == 200:          # site sonde valide, très improbable
            return wd
    return None


def noms_de_site(tenant: str):
    c = tenant.capitalize()
    return [
        "External", f"{c}Careers", f"{c}_Careers", tenant, f"{tenant}careers",
        "Careers", f"{c}External", f"{c}_External_Career_Site",
        "External_Career_Site", f"{c}Jobs", f"{tenant}jobs", "Global",
        f"{c}GlobalCareers", "careers", f"{c}_Careers_Site", "CareerSite",
    ]


def trouver_site(tenant: str, wd: str):
    """Phase 2 : n'énumère les sites que pour un couple déjà confirmé."""
    for site in noms_de_site(tenant):
        code, total = _sonder(tenant, wd, site)
        time.sleep(DELAI)
        if code == 200:
            return site, total
    return None, None


def decouvrir(tenants, verbose=True):
    trouves, partiels, requetes = [], [], 0

    for tenant in tenants:
        wd = trouver_wd(tenant)
        requetes += len(WD_NUMEROS)

        if wd is None:
            continue

        site, total = trouver_site(tenant, wd)
        requetes += len(noms_de_site(tenant))

        if site:
            trouves.append({"tenant": tenant, "wd": wd, "site": site,
                            "total": total})
            if verbose:
                print(f"  ✅ {tenant:<20} {wd:<6} {site:<26} {total} offres")
        else:
            partiels.append({"tenant": tenant, "wd": wd})
            if verbose:
                print(f"  ~  {tenant:<20} {wd:<6} tenant valide, site à trouver")

    return trouves, partiels, requetes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secteur", action="append", choices=sorted(TENANTS))
    parser.add_argument("--tenant", action="append")
    args = parser.parse_args()

    if args.tenant:
        cibles, titre = args.tenant, "tenants fournis"
    else:
        secteurs = args.secteur or sorted(TENANTS)
        cibles = [t for s in secteurs for t in TENANTS[s]]
        titre = ", ".join(secteurs)

    print("=" * 84)
    print("DÉCOUVERTE DE TENANTS WORKDAY")
    print("=" * 84)
    print(f"Secteurs : {titre}")
    print(f"Tenants  : {len(cibles)}")
    print()

    trouves, partiels, requetes = decouvrir(cibles)

    print()
    print("=" * 84)
    print(f"{len(trouves)} tenant(s) complet(s), {len(partiels)} partiel(s), "
          f"{requetes} requêtes")
    print("=" * 84)

    if trouves:
        print()
        print("À REPORTER DANS config/workday_sources.py :")
        for t in trouves:
            print(f'    {{"tenant": "{t["tenant"]}", "wd": "{t["wd"]}", '
                  f'"site": "{t["site"]}"}},   # {t["total"]} offres')

    if partiels:
        print()
        print("TENANTS VALIDES DONT LE NOM DE SITE RESTE À TROUVER :")
        for t in partiels:
            print(f"  {t['tenant']:<20} {t['wd']}")
        print()
        print("  Ouvrir la page carrière de l'entreprise : le nom de site est")
        print("  le segment qui suit myworkdayjobs.com dans l'URL.")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = LOG_DIR / f"workday_discovery_{stamp}.json"
    chemin.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tenants_tested": len(cibles),
        "requests": requetes,
        "found": trouves,
        "partial": partiels,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("Rapport :", chemin)


if __name__ == "__main__":
    main()

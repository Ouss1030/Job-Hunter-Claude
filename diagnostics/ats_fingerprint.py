"""
JOB HUNTER BELGIUM
EMPREINTE ATS - OUTIL V1.0

Identifie quel ATS héberge la page carrière d'une entreprise.

    python -m diagnostics.ats_fingerprint
    python -m diagnostics.ats_fingerprint --entreprise ucb.com --entreprise solvay.com
    python -m diagnostics.ats_fingerprint --secteur pharma

⚠️ Appelle le réseau (pages publiques). Classé en RÉSEAU dans run_all.py.

Pourquoi cet outil
------------------
Sonder les API à l'aveugle ne marche que si l'entreprise est sur un ATS
qu'on supporte déjà. Pour UCB, Solvay, Janssen ou P&G, les sondes
Recruitee / Greenhouse / SmartRecruiters / Workday sont toutes revenues
bredouilles — sans dire pour autant où ces entreprises publient.

Cet outil répond à la question dans l'autre sens : il ouvre la page
carrière publique, suit les redirections, et cherche la signature de l'ATS
dans l'URL finale et le HTML. On sait alors s'il faut écrire un connecteur,
et lequel.

Il ne collecte aucune offre. Il lit une page publique, comme un navigateur.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path

import requests


LOG_DIR = Path(__file__).resolve().parent.parent / "exports" / "logs"

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/151.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
})

TIMEOUT = 12


# Signatures ordonnées : la première rencontrée l'emporte.
SIGNATURES = (
    ("WORKDAY",         r"myworkdayjobs\.com|myworkdaysite\.com|/wday/"),
    ("GREENHOUSE",      r"(?:boards|job-boards)\.greenhouse\.io|greenhouse\.io/embed"),
    ("SMARTRECRUITERS", r"smartrecruiters\.com|careers\.smartrecruiters"),
    ("RECRUITEE",       r"\.recruitee\.com"),
    ("LEVER",           r"jobs\.lever\.co|api\.lever\.co"),
    ("SUCCESSFACTORS",  r"successfactors\.(?:com|eu)|career\d*\.successfactors|/sfcareer/"),
    ("TALEO",           r"taleo\.net|tbe\.taleo|/careersection/"),
    ("ICIMS",           r"icims\.com"),
    ("AVATURE",         r"avature\.net"),
    ("PHENOM",          r"phenompeople\.com|phenom\.com"),
    ("EIGHTFOLD",       r"eightfold\.ai"),
    ("WORKABLE",        r"apply\.workable\.com|workable\.com/j/"),
    ("TEAMTAILOR",      r"teamtailor\.com"),
    ("PERSONIO",        r"personio\.(?:de|com)/job"),
    ("ORACLE_CLOUD",    r"oraclecloud\.com/hcmUI|/hcmUI/CandidateExperience"),
    ("BRASSRING",       r"brassring\.com|krb-sjobs"),
    ("JOBVITE",         r"jobvite\.com"),
    ("ASHBY",           r"jobs\.ashbyhq\.com"),
)

# ATS pour lesquels un connecteur existe déjà dans le projet.
SUPPORTES = {"WORKDAY", "GREENHOUSE", "SMARTRECRUITERS", "RECRUITEE"}

CHEMINS = (
    "/careers", "/en/careers", "/fr/carrieres", "/carrieres", "/jobs",
    "/en/jobs", "/career", "/about/careers", "/company/careers",
    "/nl/jobs", "/vacatures", "/emplois", "",
)

PREFIXES = ("https://careers.", "https://jobs.", "https://www.", "https://")


ENTREPRISES = {
    "pharma": [
        "ucb.com", "jnj.com", "janssen.com", "takeda.com", "msd.com",
        "roche.com", "organon.com", "elanco.com", "bayer.com", "teva.com",
        "boehringer-ingelheim.com", "abbvie.com", "fresenius.com",
        "galapagos.com", "argenx.com", "biocartis.com", "mithra.com",
        "univercells.com", "aseptic-technologies.com", "eurogentec.com",
        "quality-assistance.com", "certech.be", "sciensano.be",
    ],
    "chimie": [
        "solvay.com", "syensqo.com", "umicore.com", "prayon.com",
        "tessenderlo.com", "yara.com", "indaver.com", "aquafin.be",
        "recticel.com", "lhoist.com", "carmeuse.com", "oleon.com",
        "proviron.com", "vynova-group.com", "basf.com", "ineos.com",
    ],
    "conso_agro": [
        "pg.com", "unilever.com", "danone.com", "nestle.com", "abinbev.com",
        "puratos.com", "lotusbakeries.com", "vandemoortele.com",
        "barry-callebaut.com", "spadel.com", "cargill.com", "milcobel.com",
    ],
    "data": [
        "smals.be", "cegeka.com", "delaware.pro", "nrb.be", "tobania.be",
        "inetum.com", "atos.net", "capgemini.com", "accenture.com",
        "proximus.com", "telenet.be", "euroclear.com", "swift.com",
        "kbc.com", "belfius.be", "ing.com", "bpost.be",
    ],
}


def _essayer(url: str):
    try:
        r = SESSION.get(url, timeout=TIMEOUT, allow_redirects=True)
    except Exception:
        return None
    if r.status_code >= 400:
        return None
    return r


# Extraction des identifiants exploitables, pour éviter de les deviner.
# C'est ainsi qu'a été trouvé le tenant de J&J : "jj" et non "jnj", que
# la sonde par devinette n'aurait jamais atteint.
_EXTRACTEURS = {
    "WORKDAY": re.compile(
        r"([a-z0-9_-]+)\.(wd\d+)\.myworkdayjobs\.com/(?:wday/cxs/[^/]+/)?"
        r"([A-Za-z0-9_-]+)", re.I),
    "GREENHOUSE": re.compile(
        r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?"
        r"([a-z0-9_-]+)", re.I),
    "RECRUITEE": re.compile(r"([a-z0-9-]+)\.recruitee\.com", re.I),
    "SMARTRECRUITERS": re.compile(
        r"careers\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I),
    "LEVER": re.compile(r"jobs\.lever\.co/([a-z0-9-]+)", re.I),
}

# Segments qui ne sont pas de vrais noms de site Workday.
_SITES_A_IGNORER = {"en-us", "fr-fr", "nl-nl", "en", "fr", "nl", "wday", "cxs"}


def extraire_identifiant(ats: str, texte: str):
    """Renvoie l'identifiant exploitable pour la config, si repérable."""
    motif = _EXTRACTEURS.get(ats)
    if not motif:
        return None

    replis = []
    for m in motif.finditer(texte or ""):
        groupes = [g for g in m.groups() if g]
        if ats == "WORKDAY":
            if len(groupes) < 3:
                continue
            tenant, wd, site = groupes[0], groupes[1], groupes[2]
            candidat = {"tenant": tenant, "wd": wd, "site": site}
            # Un segment de langue est rarement le nom de site... mais chez
            # argenx c'en est un. On le garde en repli plutôt que de le jeter.
            if site.lower() in _SITES_A_IGNORER:
                replis.append(candidat)
                continue
            return candidat
        return {"identifiant": groupes[0]}
    return replis[0] if replis else None


def identifier(reponse) -> tuple[str | None, str]:
    """Cherche une signature dans l'URL finale, la chaîne de redirection, puis le HTML."""
    zones = [reponse.url] + [h.headers.get("Location", "") for h in reponse.history]
    for nom, motif in SIGNATURES:
        for zone in zones:
            if re.search(motif, zone or "", re.I):
                return nom, "URL"

    corps = reponse.text[:400_000]
    for nom, motif in SIGNATURES:
        if re.search(motif, corps, re.I):
            return nom, "HTML"
    return None, ""


def sonder_entreprise(domaine: str, verbose=True):
    for prefixe in PREFIXES:
        for chemin in CHEMINS:
            url = f"{prefixe}{domaine}{chemin}"
            reponse = _essayer(url)
            if reponse is None:
                continue
            ats, ou = identifier(reponse)
            if ats:
                identifiant = extraire_identifiant(
                    ats, reponse.url + " " + reponse.text[:400_000])
                return {"domaine": domaine, "ats": ats, "detecte_dans": ou,
                        "url_testee": url, "url_finale": reponse.url,
                        "identifiant": identifiant,
                        "supporte": ats in SUPPORTES}
            # page atteinte mais aucune signature : on garde la trace
            if chemin and reponse.url != url:
                dernier = {"domaine": domaine, "ats": None, "detecte_dans": "",
                           "url_testee": url, "url_finale": reponse.url,
                           "supporte": False}
                return dernier
    return {"domaine": domaine, "ats": None, "detecte_dans": "",
            "url_testee": None, "url_finale": None, "supporte": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--secteur", action="append", choices=sorted(ENTREPRISES))
    parser.add_argument("--entreprise", action="append")
    args = parser.parse_args()

    if args.entreprise:
        cibles, titre = args.entreprise, "domaines fournis"
    else:
        secteurs = args.secteur or sorted(ENTREPRISES)
        cibles = [d for s in secteurs for d in ENTREPRISES[s]]
        titre = ", ".join(secteurs)

    print("=" * 88)
    print("EMPREINTE ATS")
    print("=" * 88)
    print(f"Secteurs   : {titre}")
    print(f"Entreprises: {len(cibles)}")
    print()

    resultats = []
    for domaine in cibles:
        r = sonder_entreprise(domaine)
        resultats.append(r)
        if r["ats"]:
            marque = "✅" if r["supporte"] else "🔧"
            print(f"  {marque} {domaine:<28} {r['ats']:<16} ({r['detecte_dans']})")
        else:
            print(f"  ?  {domaine:<28} non identifié")

    print()
    print("=" * 88)

    deja = [r for r in resultats if r["supporte"]]
    a_ecrire = [r for r in resultats if r["ats"] and not r["supporte"]]
    inconnus = [r for r in resultats if not r["ats"]]

    if deja:
        print()
        print("ATS DÉJÀ SUPPORTÉ — il suffit d'ajouter l'employeur à sa config :")
        for r in deja:
            print(f"  {r['domaine']:<28} {r['ats']}")
            ident = r.get("identifiant")
            if ident:
                print(f"      identifiant : {ident}")
            else:
                print(f"      identifiant non extrait — lire l'URL de "
                      f"{r['url_finale'][:60]}")

    if a_ecrire:
        compte = {}
        for r in a_ecrire:
            compte[r["ats"]] = compte.get(r["ats"], 0) + 1
        print()
        print("ATS NON SUPPORTÉ — un connecteur reste à écrire :")
        for ats, n in sorted(compte.items(), key=lambda x: -x[1]):
            noms = [r["domaine"] for r in a_ecrire if r["ats"] == ats]
            print(f"  {ats:<18} {n:>2} entreprise(s) : {', '.join(noms[:6])}")

    if inconnus:
        print()
        print(f"NON IDENTIFIÉS : {len(inconnus)}")
        print("  " + ", ".join(r["domaine"] for r in inconnus[:14]))

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = LOG_DIR / f"ats_fingerprint_{stamp}.json"
    chemin.write_text(json.dumps({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tested": len(cibles),
        "results": resultats,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    print("Rapport :", chemin)


if __name__ == "__main__":
    main()

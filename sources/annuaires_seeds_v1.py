"""
JOB HUNTER BELGIUM
ANNUAIRES SECTORIELS -> GRAINES DE DECOUVERTE - VERSION 1.0

    python -m sources.annuaires_seeds_v1                 # ecrit config/discovery_seeds_annuaires.json
    python -m sources.annuaires_seeds_v1 --decouvrir     # puis passe les graines au moteur
    python -m sources.annuaires_seeds_v1 --annuaire pharma_be,biowin

Meme idee que Federgon (sources/federgon_seeds_v1.py), appliquee aux
federations des secteurs vises par le candidat :

    pharma_be   pharma.be, « Nos membres » (6 pages) : le site de chaque membre
                est un lien -> domaines directs (76 le 17/09/2026)
    biowin      biowin.org, annuaire des membres du pole sante wallon : noms
                seulement (162), pas de lien -> le domaine est devine

essenscia (chimie/pharma), Agoria, Fevia : listes de logos sans lien ou
rendues en JavaScript, hors de portee le 17/09/2026.

deviner_domaine(nom) est partage avec l'etape « employeurs du Forem et
d'Actiris » : www.<nom>.be, .com, .eu, accepte seulement si la page
repond 200 et que son titre ou son texte reprend un mot significatif du
nom — « Analis » -> analis.be, « Aquilon Pharmaceuticals » -> aquilon.be.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from sources.federgon_seeds_v1 import extraire_domaines, HEADERS


ANNUAIRES_SEEDS_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SORTIE = PROJECT_ROOT / "config" / "discovery_seeds_annuaires.json"
TIMEOUT = 10
_FORMES = {"sa", "nv", "sprl", "bvba", "srl", "bv", "scrl", "cvba", "asbl", "vzw", "sc", "se", "scs", "snc", "group",
           "groupe", "belgium", "belgique", "belgie", "benelux", "europe", "international", "the", "de", "la", "le", "les",
           "et", "and", "en", "van", "der", "des", "du", "ltd", "inc", "gmbh", "ag", "bvba/sprl", "sa/nv", "nv/sa"}
_MOTS_VIDES = _FORMES | {"pharma", "pharmaceuticals", "pharmaceutical", "bio", "biotech", "medical", "clinical", "solutions",
                         "services", "consulting", "technologies", "technology", "systems", "lab", "labs", "laboratoire"}
_RE_BELGE = re.compile(r"(?<![a-z])(?:belgi(?:que|e|um|en)|bruxelles|brussels?|wallonie|vlaanderen|antwerpen|anvers|gent|liege|charleroi|namur|leuven|louvain|mons|hasselt)(?![a-z])")
_EXCLUS_DOMAINES = ("googletagmanager.com", "google.com", "linkedin.com", "facebook.com", "youtube.com", "twitter.com",
                    "x.com", "instagram.com", "yoast.com", "addtoany.com", "elementor.com", "typekit.net", "tiktok.com")


def _normaliser(nom: str) -> str:
    n = unicodedata.normalize("NFKD", str(nom or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9 ]+", " ", n).strip()


def _mots(nom: str) -> list[str]:
    return [m for m in _normaliser(nom).split() if m not in _MOTS_VIDES and len(m) >= 3]


def candidats_domaines(nom: str) -> list[str]:
    """Les hotes a essayer pour un nom d'entreprise, les plus probables d'abord."""
    n = _normaliser(nom)
    mots = [m for m in n.split() if m not in _FORMES]
    if not mots:
        return []
    colle = "".join(mots)
    tiret = "-".join(mots)
    significatifs = _mots(nom) or mots
    bases = []
    for b in (colle, tiret, significatifs[0] if significatifs else "", "".join(significatifs[:2])):
        if b and 3 <= len(b) <= 40 and b not in bases:
            bases.append(b)
    hotes = []
    for b in bases:
        for tld in (".be", ".com", ".eu"):
            hotes.append(f"{b}{tld}")
    return hotes[:9]


def deviner_domaine(nom: str, session=None) -> str | None:
    """www.<nom>.be / .com / .eu ; accepte si la page repond 200 et reprend un mot significatif du nom."""
    session = session or requests.Session()
    mots = _mots(nom) or _normaliser(nom).split()
    for hote in candidats_domaines(nom):
        try:
            r = session.get(f"https://www.{hote}", headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        except Exception:
            try:
                r = session.get(f"https://{hote}", headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
            except Exception:
                continue
        if r.status_code != 200 or len(r.text) < 500:
            continue
        soupe = BeautifulSoup(r.text[:200000], "html.parser")
        titre = _normaliser(soupe.title.get_text() if soupe.title else "")
        texte = _normaliser(soupe.get_text(" ")[:8000])
        # Un mot de 3 lettres (« hoc », « iba ») ne prouve rien ; le nom doit se lire dans le titre
        # ou le texte, et hors .be la page doit parler de Belgique.
        forts = [m for m in mots if len(m) >= 4]
        if not forts:
            # « Ad Hoc Clinical », « IBA » : sans mot fort, seul le nom colle (adhocclinical, iba) fait foi
            tous = [m for m in _normaliser(nom).split() if m not in _FORMES]
            if hote.split(".")[0] not in ("".join(tous), "-".join(tous)):
                continue
            forts = mots
        dans_titre = any(m in titre for m in forts)
        if not (dans_titre or any(f" {m} " in f" {texte} " for m in forts)):
            continue
        final = re.sub(r"^https?://", "", r.url).split("/")[0].lower().removeprefix("www.")
        if any(final.endswith(x) for x in _EXCLUS_DOMAINES):
            continue
        # Nom seulement dans le texte et hote hors .be : il faut en plus que la page parle de Belgique.
        if not final.endswith(".be") and not dans_titre and not _RE_BELGE.search(texte):
            continue
        return final
    return None


# ------------------------------------------------------------------
# Annuaires
# ------------------------------------------------------------------

def pharma_be(session) -> list[dict]:
    domaines = []
    for page in range(0, 12):
        r = session.get(f"https://pharma.be/fr/membres?page={page}", headers=HEADERS, timeout=25)
        if r.status_code != 200:
            break
        nouveaux = [d for d in extraire_domaines(r.text)
                    if not d.endswith("pharma.be") and not any(d.endswith(x) for x in _EXCLUS_DOMAINES) and d not in domaines]
        if not nouveaux:
            break
        domaines += nouveaux
    return [{"domaine": d, "label": d.split(".")[0].replace("-", " ").title(), "discovered_by": "annuaire:pharma.be"} for d in domaines]


def biowin(session, verbose: bool = True) -> list[dict]:
    noms = []
    for lettre in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        r = session.get(f"https://www.biowin.org/members/?filters[starts_with]={lettre}", headers=HEADERS, timeout=25)
        if r.status_code != 200:
            continue
        for h in BeautifulSoup(r.text, "html.parser").select("h3"):
            t = h.get_text(" ", strip=True)
            if t and len(t) < 60 and t not in noms and t not in ("Filters", "Click on the letter of the member", "Appear in that directory"):
                noms.append(t)
    sortie = []
    for i, nom in enumerate(noms, 1):
        d = deviner_domaine(nom, session)
        if verbose:
            print(f"  [{i:>3}/{len(noms)}] {nom[:40]:<40} -> {d or '-'}")
        if d:
            sortie.append({"domaine": d, "label": nom, "discovered_by": "annuaire:biowin"})
    return sortie


ANNUAIRES = {"pharma_be": pharma_be, "biowin": biowin}


def graines(noms_annuaires: list[str], verbose: bool = True) -> list[dict]:
    session = requests.Session()
    try:
        from sources.ats_employers_v2 import charger
        connus = set()
        for e in charger()["employers"]:
            for v in (e.get("career_url"), str(e.get("identifier"))):
                m = re.search(r"([a-z0-9-]+\.[a-z]{2,})(?:/|$)", str(v or "").lower().replace("www.", ""))
                if m:
                    connus.add(m.group(1))
    except Exception:
        connus = set()
    sortie, vus = [], set()
    for nom in noms_annuaires:
        fn = ANNUAIRES[nom]
        if verbose:
            print(f"\n{nom}")
        for c in (fn(session, verbose) if nom == "biowin" else fn(session)):
            d = c["domaine"]
            if d in vus or any(d.endswith(k) for k in connus):
                continue
            vus.add(d)
            sortie.append(c)
        if verbose:
            print(f"  -> {sum(1 for c in sortie if c['discovered_by'].endswith(nom.replace('_', '.')))} graines nouvelles")
    return sortie


def ecrire(candidats: list[dict]) -> Path:
    groupes: dict[str, list] = {}
    for c in candidats:
        groupes.setdefault(c["discovered_by"].split(":")[-1], []).append({"domaine": c["domaine"], "label": c["label"]})
    SORTIE.write_text(json.dumps({
        "schema_version": ANNUAIRES_SEEDS_VERSION, "generated_at": datetime.now().isoformat(timespec="seconds"),
        "purpose": "Membres des federations sectorielles (pharma.be, BioWin) a passer au moteur de decouverte.",
        "groups": groupes,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    return SORTIE


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--annuaire", default=",".join(ANNUAIRES), help="pharma_be,biowin")
    p.add_argument("--decouvrir", action="store_true")
    args = p.parse_args()
    candidats = graines([a.strip() for a in args.annuaire.split(",") if a.strip()])
    chemin = ecrire(candidats)
    print(f"\n{len(candidats)} graines -> {chemin}")
    if args.decouvrir and candidats:
        from sources.source_discovery_v1 import decouvrir
        decouvrir(candidats, dossier=PROJECT_ROOT / "exports" / "logs" /
                  f"discovery_annuaires_{datetime.now().strftime('%Y%m%d_%H%M%S')}", deviner=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
JOB HUNTER BELGIUM
DETECTEUR D'ATS - VERSION 1.0

Recoit une URL, un domaine ou une page HTML et dit quel systeme de
recrutement se cache derriere — puis vers quel connecteur existant router.

    >>> detecter_url("https://jobs.lever.co/deliverect/1234")
    {'ats': 'LEVER', 'identifiant': 'deliverect', 'connecteur': 'LEVER', ...}

    >>> detecter_site("ucb.com")          # une ou quelques requetes HTTP
    {'ats': 'PHENOM', 'identifiant': 'careers.ucb.com', ...}

Il ne collecte aucune offre. Il ouvre une page publique comme un navigateur,
suit les redirections, et cherche les signatures declarees dans
config/ats_signatures.json : URL finale, chaine de redirections, liens et
scripts du HTML. Ajouter un ATS = ajouter une entree dans ce fichier.

Ce qui est repris de diagnostics/ats_fingerprint.py (20 aout 2026) : la
methode — chemins carriere usuels, prefixes d'hote, signatures URL puis
HTML. Ce qui change : les signatures vivent en JSON, chaque ATS connait son
connecteur, et l'identifiant est extrait pour tous les ATS, pas cinq.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import urlsplit

import requests


ATS_DETECTOR_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SIGNATURES_PATH = PROJECT_ROOT / "config" / "ats_signatures.json"

TIMEOUT = 8
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/151.0 Safari/537.36 JobHunter/ats-detector"),
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
}

# Chemins carriere usuels, du plus specifique au plus general.
CHEMINS_CARRIERE = (
    "/careers", "/en/careers", "/jobs", "/en/jobs", "/career", "/vacatures",
    "/nl/vacatures", "/nl/jobs", "/fr/carrieres", "/carrieres", "/fr/emplois",
    "/emplois", "/fr/jobs", "/about/careers", "/company/careers", "/join-us",
    "/werken-bij", "/jobs-carrieres", "",
)
PREFIXES_HOTE = ("https://careers.", "https://jobs.", "https://www.", "https://")

# Un lien vers un hote ATS dans le HTML vaut preuve ; ces motifs disent
# lesquels chercher avant de scanner tout le HTML.
_RE_LIENS = re.compile(r"""(?:href|src|action|content)\s*=\s*["']([^"']{8,400})["']""", re.I)

_cache_signatures: dict | None = None


def charger_signatures(force: bool = False) -> dict:
    global _cache_signatures
    if _cache_signatures is None or force:
        _cache_signatures = json.loads(SIGNATURES_PATH.read_text(encoding="utf-8"))
        for nom, spec in _cache_signatures["ats"].items():
            spec["_nom"] = nom
    return _cache_signatures


def ats_connus() -> list[str]:
    return list(charger_signatures()["ats"].keys())


def ats_avec_connecteur() -> dict[str, str]:
    return {nom: spec["connector"] for nom, spec in charger_signatures()["ats"].items()
            if spec.get("connector")}


# ------------------------------------------------------------------
# Detection hors ligne
# ------------------------------------------------------------------

def _extraire_identifiant(spec: dict, texte: str):
    motif = spec.get("identifier")
    if not motif:
        return None
    try:
        m = re.search(motif, texte or "", re.I)
    except re.error:
        return None
    if not m:
        return None
    groupes = {k: v for k, v in m.groupdict().items() if v}
    if not groupes:
        return None
    if list(groupes) == ["identifiant"]:
        ident = groupes["identifiant"]
        # Un slug technique (careers-analytics.recruitee.com -> "careers-analytics")
        # n'est pas un employeur. Un hote complet (jobs.vub.be) l'est toujours.
        if "." not in ident and ident.lower() in _FAUX_TENANTS:
            return None
        if "." in ident and ident.lower().split(".")[0] in _FAUX_TENANTS and                 any(ident.lower().endswith(suf) for suf in (".recruitee.com", ".teamtailor.com", ".jobtoolz.com",
                                                             ".talentfinder.be", ".personio.de", ".personio.com")):
            return None
        # Un hote est insensible a la casse ; un slug d'URL l'est chez ces
        # ATS. Ailleurs (SmartRecruiters, Ashby) on garde la casse vue.
        if "." in ident or nom_ats_minuscules(spec):
            ident = ident.lower()
        return ident
    return groupes


# Sous-domaines techniques d'un ATS (scripts, CDN, analytics) : jamais un employeur.
_FAUX_TENANTS = {"careers-analytics", "analytics", "api", "assets", "cdn", "static", "www",
                 "app", "docs", "help", "support", "status", "embed", "widget", "widgets",
                 "images", "img", "media", "files", "js", "css", "auth", "login", "admin",
                 "boards-api", "job-boards", "jobs", "careers", "apply", "hire"}

_ATS_SLUG_MINUSCULES = {"LEVER", "GREENHOUSE", "RECRUITEE", "WORKABLE", "PERSONIO",
                        "BAMBOOHR", "BREEZY", "HOMERUN", "JOBVITE", "WELCOME_TO_THE_JUNGLE",
                        "CVWAREHOUSE"}


def nom_ats_minuscules(spec: dict) -> bool:
    return spec.get("_nom") in _ATS_SLUG_MINUSCULES


def _resultat(nom: str, spec: dict, identifiant, preuve: str, **extra) -> dict:
    return {
        "ats": nom,
        "identifiant": identifiant,
        "connecteur": spec.get("connector"),
        "strategie": spec.get("strategy"),
        "config": spec.get("config"),
        "endpoint": (spec.get("endpoint") or "").format(
            **(identifiant if isinstance(identifiant, dict) else {"identifiant": identifiant or ""})
        ) if spec.get("endpoint") and identifiant else None,
        "preuve": preuve,
        **extra,
    }


def detecter_dans_texte(texte: str, preuve: str = "TEXTE") -> list[dict]:
    """Toutes les signatures presentes dans un texte (URL ou HTML), ordre du registre."""
    trouves = []
    for nom, spec in charger_signatures()["ats"].items():
        for motif in spec.get("url_patterns") or ():
            try:
                if re.search(motif, texte or "", re.I):
                    trouves.append(_resultat(nom, spec, _extraire_identifiant(spec, texte), preuve))
                    break
            except re.error:
                continue
    return trouves


def detecter_url(url: str) -> dict | None:
    """Detection sans reseau, sur la seule URL."""
    if not url:
        return None
    for r in detecter_dans_texte(url, preuve="URL"):
        if r["ats"] not in ("RADANCY", "PHENOM", "SUCCESSFACTORS", "OTYS", "BULLHORN") or r["identifiant"]:
            return r
    return None


# ------------------------------------------------------------------
# Detection en ligne
# ------------------------------------------------------------------

def _get(url: str, session: requests.Session | None = None):
    s = session or requests
    return s.get(url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)


def _analyser_reponse(reponse) -> dict | None:
    zones = [reponse.url] + [h.headers.get("Location", "") for h in reponse.history]
    for zone in zones:
        r = detecter_url(zone)
        if r:
            r["url_finale"] = reponse.url
            return r

    corps = reponse.text[:600_000] if "html" in (reponse.headers.get("content-type") or "") or reponse.text[:1].strip() == "<" else ""
    if not corps:
        return None

    # 1) liens explicites vers un hote ATS : preuve la plus sure, identifiant fiable
    for lien in _RE_LIENS.findall(corps):
        r = detecter_url(lien)
        if r and r["identifiant"]:
            r["preuve"] = "LIEN"
            r["url_finale"] = reponse.url
            return r

    # 2) signatures dans les scripts / marqueurs DOM
    for r in detecter_dans_texte(corps, preuve="HTML"):
        r["url_finale"] = reponse.url
        # Sans identifiant, l'hote de la page carriere sert d'identifiant
        # pour les strategies sitemap (Phenom, SuccessFactors, Radancy).
        if not r["identifiant"] and r["strategie"] in ("SITEMAP_JSONLD", "SITEMAP_HTML"):
            r["identifiant"] = urlsplit(reponse.url).netloc.lower()
            r["endpoint"] = f"https://{r['identifiant']}/sitemap.xml"
        return r
    return None


_RE_LIEN_CARRIERE = re.compile(
    r"""href\s*=\s*["']([^"']*(?:career|carriere|carrière|jobs?|vacature|vacancies|emploi|"""
    r"""werken-bij|werkenbij|join-us|joinus|recrutement|solliciteer|postuler)[^"']*)["']""", re.I)


def _candidats(domaine: str) -> list[str]:
    d = domaine.lower().removeprefix("www.").strip("/")
    return [
        f"https://www.{d}/careers", f"https://www.{d}/jobs", f"https://careers.{d}/",
        f"https://jobs.{d}/", f"https://www.{d}/en/careers", f"https://www.{d}/vacatures",
        f"https://www.{d}/", f"https://{d}/",
    ]


def _liens_carriere(reponse, limite: int = 3) -> list[str]:
    from urllib.parse import urljoin
    base = reponse.url
    hote = urlsplit(base).netloc.lower().removeprefix("www.")
    trouves = []
    for lien in _RE_LIEN_CARRIERE.findall(reponse.text[:600_000]):
        absolu = urljoin(base, lien.split("#")[0])
        if not absolu.startswith("http"):
            continue
        cible = urlsplit(absolu).netloc.lower().removeprefix("www.")
        # meme domaine, sous-domaine, ou hote ATS reconnu
        if cible == hote or cible.endswith("." + hote) or detecter_url(absolu):
            if absolu not in trouves and absolu.rstrip("/") != base.rstrip("/"):
                trouves.append(absolu)
        if len(trouves) >= limite:
            break
    return trouves


def detecter_site(domaine_ou_url: str, session: requests.Session | None = None,
                  max_requetes: int = 10) -> dict:
    """
    Trouve la page carriere d'un domaine et l'ATS derriere.

    Essaie les emplacements usuels, puis suit jusqu'a trois liens "carriere"
    trouves sur les pages ouvertes. Rend toujours un dict : ats=None si rien
    n'est reconnu, avec les URL essayees pour que l'echec soit lisible.
    """
    valeur = str(domaine_ou_url or "").strip()
    essais = []
    file = [valeur] if valeur.startswith(("http://", "https://")) else _candidats(valeur)
    session = session or requests.Session()
    vus: set[str] = set()
    derniere_page = None
    a_suivre: list[str] = []
    while (file or a_suivre) and len(essais) < max_requetes:
        url = file.pop(0) if file else a_suivre.pop(0)
        if url.rstrip("/") in vus:
            continue
        vus.add(url.rstrip("/"))
        try:
            reponse = _get(url, session)
        except Exception:
            essais.append({"url": url, "statut": "reseau"})
            continue
        essais.append({"url": url, "statut": reponse.status_code, "finale": reponse.url})
        if reponse.status_code >= 400:
            continue
        vus.add(reponse.url.rstrip("/"))
        derniere_page = derniere_page or reponse.url
        r = _analyser_reponse(reponse)
        if r:
            r["entree"] = valeur
            r["essais"] = essais
            return r
        for lien in _liens_carriere(reponse):
            if lien.rstrip("/") not in vus and lien not in a_suivre:
                a_suivre.append(lien)
    return {"ats": None, "identifiant": None, "connecteur": None, "strategie": None,
            "entree": valeur, "page_carriere": derniere_page, "essais": essais}


if __name__ == "__main__":
    import sys
    for arg in sys.argv[1:] or ["https://jobs.lever.co/exemple/abc", "ucb.com"]:
        r = detecter_url(arg) if arg.startswith("http") else None
        print(json.dumps(r or detecter_site(arg), ensure_ascii=False, indent=1)[:1200])

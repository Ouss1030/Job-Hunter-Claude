"""
JOB HUNTER BELGIUM
COLLECTEUR HTML GENERIQUE - VERSION 1.1

Le dernier repli avant le navigateur : un portail carriere maison, sans
API, sans flux, sans JSON-LD — Plone (UNamur), Odoo (HENALLUX), Drupal
(GHdC, Citadelle), CMS propres (CHU Liege). C'est le cas de la plupart des
hopitaux, hautes ecoles et administrations francophones : sondage du
16 septembre 2026, 45 graines wallonnes et bruxelloises sur 67 sans voie.

    liste   la page carriere : liens internes dont le chemin ressemble a une
            offre (/emploi/…, /jobs/…, /vacature/…, /offre/…)
    detail  chaque page : JSON-LD JobPosting si present, sinon
              titre       og:title, h1, <title>
              contenu     main / article / [role=main] / #content, sans
                          nav, header, footer, aside, script, formulaires
              lieu        code postal ou commune belge trouves dans la page

Garde-fous (l'idee vient du projet principal, job_quality_guard_v416) :
une page de liste prise pour une offre a un titre du type « 12 emplois »,
« Offres d'emploi », « Jobs », « Legal Jobs » ; une page d'information a
un titre du type « FAQ », « Charte », « Procedure de recrutement »,
« Travailler a la Ville de … » ; un texte trop court ou identique a la
liste n'est pas une offre ; sans aucune preuve belge dans la page et sans
"include_unknown", l'offre est ecartee.

Preuve d'offre (V1.1, calibree le 17 septembre 2026 sur 190 pages de huit
portails) : une vraie offre parle d'au moins trois de ces sept choses —
postuler, profil, missions, contrat, competences, dates, ce qu'on offre.
Les pages de UNamur, GHdC, Prayon, Brabant wallon en citent 5 a 7 ; les
pages « Cite des Metiers », « Le Forem », « Resultats de recherche » de
namur.be et chuliege.be en citent 0 a 2.

Lieu (V1.1) : un code postal n'est retenu que suivi d'un nom (« 6220
Fleurus », « B-1000 Bruxelles ») — « Ref : 2026-88 », « Top Employer
2026 », « depuis 1991 » ne sont plus des codes postaux ; a defaut, une
commune belge connue (location_belgium.BELGIAN_CITIES) donne le lieu.

Un site = {"identifier": "https://jobs.unamur.be/liste_emplois",
"label": "UNamur", "lien_regex": optionnel, "selecteur_contenu": optionnel}
dans config/ats_employers_v2.json, connecteur HTML_SITES.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from database.models import JobOffer
from sources.location_belgium import (belgian_postal_code, detect_belgium_multi, BELGIAN_CITIES,
                                      BE_CONFIRMED, BE_LIKELY, BE_UNKNOWN)
from sources.jsonld_sitemap_v1 import _RE_URL_OFFRE, _RE_EXCLURE, convertir_posting
from sources.phenom_ats_v1 import extract_job_posting


HTML_GENERIQUE_VERSION = "1.1"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = PROJECT_ROOT / "logs" / "html_sites_cache"

TIMEOUT = 20
PAUSE = 0.5
MAX_PAGES = 120
MIN_TEXTE = 300
MIN_INDICES = 3
CACHE_JOURS = 3
HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/151.0 Safari/537.36 JobHunter/html"),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "fr-BE,fr;q=0.9,nl;q=0.8,en;q=0.7",
}

_TITRES_LISTE = [
    r"^\s*\d+\s+(?:emplois?|jobs?|vacatures?|offres?|postes?|résultats?)\b",
    r"^\s*(?:jobs?|vacatures?|vacancies|carri[eè]res?|emplois?|offres?\s+d['’]emploi|nos offres|travailler chez|werken bij|join us|rejoignez)\b",
    r"\b(?:emplois?|jobs?)\s+(?:pour|voor|in|à|a|en)\b",
    r"\b(?:jobs|emplois|vacatures|vacancies|offres)\s*$",          # « Legal Jobs » : une rubrique
    r"^\s*(?:accueil|home|contact|actualit|news|login|connexion)\b",
    r"^\s*(?:faq|charte|atouts|procédure|procedure|résultats? de recherche|zoekresultaten|search results|"
    r"travailler (?:à|au|aux|chez|pour)|werken (?:bij|voor)|working at|candidature spontanée|"
    r"spontane sollicitatie|offres de stages?|stages? (?:au sein|pour)|nos valeurs|our values|onze waarden)\b",
    r"^\s*\d+\s*$",
]
_RE_TITRES_LISTE = [re.compile(p, re.I) for p in _TITRES_LISTE]
_BALISES_BRUIT = ("nav", "header", "footer", "aside", "script", "style", "form", "noscript", "iframe", "svg", "button")
_SELECTEURS_CONTENU = ("main", "article", "[role=main]", "#main-content", "#content", ".content", "#main", ".main", ".region-content")
_RE_BELGE = re.compile(r"\b(?:belgi(?:que|ë|e|um)|brussel|bruxelles|wallonie|vlaanderen|flandre)\b", re.I)
# Plone et consorts : /emploi.2026-09-02.5293710817, /job-12345, /vacature_abc
_RE_URL_OFFRE_SEP = re.compile(r"/(?:emploi|emplois|job|jobs|vacature|vacatures|offre|offres|poste|vacancy)[._-][^/?#]{3,}$"
                               r"|/(?:job|jobs|emploi|offre|vacature)[_-](?:display|detail|details|view|show|posting|id)/[^/?#]{2,}", re.I)
# Un hub carriere qui ne liste rien lui-meme : on suit un lien "offres / emploi / jobs"
_RE_LIEN_LISTE = re.compile(r"(?:offres?-?d?-?emploi|emplois?-?en-?cours|vacatures|jobs?-?list|nos-?offres|liste_?emplois|all-?jobs|toutes)", re.I)
# "© 2026", "2026-09-02" ne sont pas des codes postaux ; "2000 Antwerpen" en est un.
_RE_ANNEE = re.compile(r"\b20[0-3]\d\b")
# Un code postal suivi d'un nom : « 6220 Fleurus », « B-1000 Bruxelles », « 1310 La Hulpe »
_RE_CP_NOM = re.compile(r"(?<![\d-])(?:B-?|BE-?)?([1-9]\d{3})[ \u00a0,]+([A-ZÀ-Ý][\w'’.-]+)(?:[ \u00a0]+([A-ZÀ-Ý][\w'’.-]+))?")
# « 1310 La Hulpe », « 1000 Sint Gillis » : le second mot n'est pris qu'apres un article
_ARTICLES_LIEU = {"la", "le", "les", "de", "den", "het", "sint", "saint", "sainte", "st", "mont", "la-"}
_PAYS = {"belgique", "belgium", "belgië", "belgie", "be"}
# « depuis 1991 », « in 1970 », « © 2019 » : une annee, meme suivie d'une majuscule
_RE_AVANT_ANNEE = re.compile(r"(?:depuis|since|sinds|en|in|of|©|anno|vanaf|dès)\s*$", re.I)
# Communes qui sont aussi des mots courants (« 3 ans », « to manage », « boom », « spa ») :
# jamais retenues sur le seul texte libre, il faut un code postal devant.
_VILLES_AMBIGUES = {"ans", "manage", "mol", "ham", "boom", "spa", "lier", "halle", "asse", "forest", "vorst",
                    "geel", "waver", "bergen", "namen", "landen", "vise", "mons", "ath", "huy", "olen", "balen",
                    "zele", "hamme", "temse", "genk", "gent", "diest", "leuze", "ciney", "thuin", "binche", "spa"}
_RE_VILLE = re.compile(r"(?<![A-Za-z])(?:" + "|".join(sorted((re.escape(v.title()) for v in set(BELGIAN_CITIES)
                                                             if v not in _VILLES_AMBIGUES), key=len, reverse=True))
                       + r")(?![a-z])")


def _sans_accents(texte: str) -> str:
    """Accents retires, casse conservee : « Liège » -> « Liege », pour reconnaitre une commune ecrite en majuscule initiale."""
    return "".join(ch for ch in unicodedata.normalize("NFKD", texte) if not unicodedata.combining(ch))
# Sept familles de vocabulaire d'une offre ; une vraie offre en cite au moins MIN_INDICES.
_INDICES_OFFRE = {
    "postuler": r"\b(?:postule[rz]|candidature|candidater|apply|application|solliciteer|sollicit\w*)\b",
    "profil": r"\b(?:profil|profile|profiel|qualifications?|requirements?|exigences|vereisten)\b",
    "missions": r"\b(?:missions?|tâches|taches|responsabilit\w+|responsibilit\w+|fonction|functie|taken|takenpakket|"
                r"rôle|role|job description|description de (?:la )?fonction)\b",
    "contrat": r"\b(?:contrat|contract|cdi|cdd|int[ée]rim|temps plein|temps partiel|mi-temps|full[- ]?time|part[- ]?time|"
               r"voltijds|deeltijds|halftijds|régime de travail|arbeidsregime|durée|duration|horaire|uurrooster)\b",
    "competences": r"\b(?:compétences?|competences?|skills?|vaardigheden|dipl[ôo]me|diploma|degree|bachelier|bachelor|"
                   r"master|graduat|expérience|experience|ervaring)\b",
    "dates": r"\b(?:date limite|deadline|closing date|uiterlijk|entrée en fonction|start date|date d['’]entrée|"
             r"indiensttreding|dès que possible|as soon as possible)\b",
    "offre": r"\b(?:nous (?:vous )?offrons|we offer|wij bieden|what we offer|ce que nous offrons|salaire|salary|"
             r"rémunération|remuneration|barème|loon|avantages|benefits|package)\b",
}
_RE_INDICES = {k: re.compile(v, re.I) for k, v in _INDICES_OFFRE.items()}


def _clean(v) -> str:
    return re.sub(r"\s+", " ", "" if v is None else str(v)).strip()


def _cache_path(host: str) -> Path:
    return CACHE_DIR / f"{re.sub(r'[^a-z0-9.-]+', '_', host.lower())}.json"


def _charger_cache(host: str) -> dict:
    p = _cache_path(host)
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except Exception:
        return {}


def _ecrire_cache(host: str, cache: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_path(host).write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


# ------------------------------------------------------------------
# Liste
# ------------------------------------------------------------------

def liens_offres(listing_url: str, html: str, lien_regex: str | None = None) -> list[str]:
    base = listing_url
    hote = urlsplit(base).netloc.lower().removeprefix("www.")
    motif = re.compile(lien_regex, re.I) if lien_regex else None
    soupe = BeautifulSoup(html, "html.parser")
    vus, sortie = set(), []
    for a in soupe.select("a[href]"):
        u = urljoin(base, a.get("href").split("#")[0].strip())
        p = urlsplit(u)
        if p.scheme not in ("http", "https") or p.netloc.lower().removeprefix("www.") != hote:
            continue
        if u.rstrip("/") == base.rstrip("/") or u in vus:
            continue
        ok = motif.search(u) if motif else ((_RE_URL_OFFRE.search(p.path) or _RE_URL_OFFRE_SEP.search(p.path))
                                            and not _RE_EXCLURE.search(p.path))
        if not ok:
            continue
        vus.add(u)
        sortie.append(u)
    return sortie


# ------------------------------------------------------------------
# Detail
# ------------------------------------------------------------------

def indices_offre(texte: str) -> list[str]:
    """Les familles de vocabulaire d'offre presentes dans le texte (voir _INDICES_OFFRE)."""
    return [k for k, r in _RE_INDICES.items() if r.search(texte)]


def _titre(soupe: BeautifulSoup) -> str:
    og = soupe.select_one("meta[property='og:title']")
    for cand in ((og.get("content") if og else ""), (soupe.h1.get_text() if soupe.h1 else ""),
                 (soupe.title.get_text() if soupe.title else "")):
        t = _clean(html.unescape(cand or ""))
        t = re.split(r"\s+[|\-–—]\s+", t)[0].strip() if len(t) > 60 else t
        if t and not any(r.search(t) for r in _RE_TITRES_LISTE):
            return t[:200]
    return ""


def _contenu(soupe: BeautifulSoup, selecteur: str | None = None) -> str:
    for tag in soupe.find_all(_BALISES_BRUIT):
        tag.decompose()
    for cls in soupe.select("[class*='cookie'], [id*='cookie'], [class*='breadcrumb'], [class*='share'], [class*='menu'], [class*='sidebar']"):
        cls.decompose()
    bloc = None
    if selecteur:
        bloc = soupe.select_one(selecteur)
    if bloc is None:
        for sel in _SELECTEURS_CONTENU:
            cand = soupe.select_one(sel)
            if cand is not None and len(_clean(cand.get_text(" "))) >= MIN_TEXTE:
                bloc = cand
                break
    bloc = bloc if bloc is not None else (soupe.body or soupe)
    texte = bloc.get_text("\n")
    texte = re.sub(r"[ \t]+", " ", texte)
    return re.sub(r"\n\s*\n+", "\n", texte).strip()


def _lieu(texte: str) -> tuple[str, str]:
    """(lieu lisible, statut) a partir d'un code postal suivi d'un nom, d'une commune ou d'une region belge."""
    extrait = _RE_ANNEE.sub(" ", texte[:6000])
    for m in _RE_CP_NOM.finditer(extrait):
        cp = belgian_postal_code(m.group(1))
        # 1900-1999 : un code postal du Brabant... ou une annee (« depuis 1991 », « in 1970 »)
        if cp and not (m.group(1).startswith("19") and _RE_AVANT_ANNEE.search(extrait[max(0, m.start() - 8):m.start()])):
            nom = m.group(2).strip('.,-')
            if m.group(3) and nom.lower() in _ARTICLES_LIEU and m.group(3).lower() not in _PAYS:
                nom += ' ' + m.group(3).strip('.,-')
            if nom.lower() in _PAYS:
                continue
            return f"{nom} ({cp[0]})", BE_CONFIRMED
    plat = _sans_accents(extrait)
    m = _RE_VILLE.search(plat)
    if m:
        return (extrait if len(plat) == len(extrait) else plat)[m.start():m.end()], BE_LIKELY
    m = _RE_BELGE.search(extrait)
    if m:
        return m.group(0), BE_LIKELY
    return "", BE_UNKNOWN


def extraire_page(url: str, html: str, listing_url: str, listing_hash: str, selecteur: str | None = None) -> dict | None:
    posting = extract_job_posting(html)
    if posting:
        return {"posting": posting}
    soupe = BeautifulSoup(html, "html.parser")
    titre = _titre(soupe)
    if not titre:
        return {"rejet": "titre de liste ou de page d'information"}
    texte = _contenu(soupe, selecteur)
    if len(texte) < MIN_TEXTE:
        return {"rejet": "texte trop court"}
    if hashlib.sha1(texte[:2000].encode("utf-8", "ignore")).hexdigest() == listing_hash:
        return {"rejet": "meme contenu que la liste"}
    indices = indices_offre(texte)
    if len(indices) < MIN_INDICES:
        return {"rejet": f"vocabulaire d'offre insuffisant ({len(indices)}/{len(_INDICES_OFFRE)})"}
    lieu, statut = _lieu(texte + " " + titre)
    return {"titre": titre, "texte": texte[:20000], "lieu": lieu, "statut": statut}


def collect_html_site(company: dict, session=None, include_unknown: bool = True,
                      max_pages: int = MAX_PAGES, source: str = "HTML_SITES",
                      verbose: bool = False) -> tuple[list[JobOffer], dict]:
    session = session or requests.Session()
    listing_url = _clean(company.get("identifier") or company.get("listing_url"))
    label = _clean(company.get("label")) or urlsplit(listing_url).netloc
    hote = urlsplit(listing_url).netloc.lower()
    meta = {"host": hote, "label": label, "liens": 0, "cache": 0, "visitees": 0, "be": 0,
            "hors_be": 0, "rejetees": 0, "echecs": 0, "error": None, "motifs": {}}
    try:
        r = session.get(listing_url, headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:
        meta["error"] = f"{type(e).__name__}: {str(e)[:80]}"
        return [], meta
    liens = liens_offres(r.url, r.text, company.get("lien_regex"))
    if not liens:
        # Page "hub" (CHU Liege) : la vraie liste est un lien plus loin.
        hote_base = urlsplit(r.url).netloc.lower().removeprefix("www.")
        candidats = []
        for a in BeautifulSoup(r.text, "html.parser").select("a[href]"):
            u = urljoin(r.url, a.get("href").split("#")[0])
            if (urlsplit(u).netloc.lower().removeprefix("www.") == hote_base
                    and _RE_LIEN_LISTE.search(urlsplit(u).path)
                    and u.rstrip("/") != r.url.rstrip("/") and u not in candidats):
                candidats.append(u)
        for u in candidats[:3]:
            try:
                r2 = session.get(u, headers=HEADERS, timeout=TIMEOUT)
                if r2.status_code == 200:
                    liens = liens_offres(r2.url, r2.text, company.get("lien_regex"))
                    if liens:
                        r = r2
                        break
            except Exception:
                continue
    meta["liens"] = len(liens)
    if not liens:
        meta["error"] = "aucun lien d'offre sur la page"
        return [], meta
    listing_hash = hashlib.sha1(_contenu(BeautifulSoup(r.text, "html.parser"))[:2000].encode("utf-8", "ignore")).hexdigest()
    cache = _charger_cache(hote)
    maintenant = datetime.now(timezone.utc)
    jobs, nouvelles = [], 0
    for url in liens:
        entree = cache.get(url)
        frais = False
        if entree:
            try:
                frais = (maintenant - datetime.fromisoformat(entree["lu"])).days < CACHE_JOURS
            except Exception:
                frais = False
        if frais:
            page = entree.get("page")
            meta["cache"] += 1
        else:
            if nouvelles >= max_pages:
                continue
            nouvelles += 1
            meta["visitees"] += 1
            try:
                rp = session.get(url, headers=HEADERS, timeout=TIMEOUT)
                page = extraire_page(url, rp.text, listing_url, listing_hash, company.get("selecteur_contenu")) if rp.status_code == 200 else None
                if rp.status_code == 404:
                    cache.pop(url, None)
                    continue
            except Exception:
                meta["echecs"] += 1
                continue
            cache[url] = {"lu": maintenant.isoformat(), "page": page}
            time.sleep(PAUSE)
        if not page or page.get("rejet"):
            meta["rejetees"] += 1
            motif = (page or {}).get("rejet") or "page vide ou en erreur"
            meta["motifs"][motif] = meta["motifs"].get(motif, 0) + 1
            continue
        if page.get("posting"):
            job = convertir_posting(url, page["posting"], source, hote, label)
            if not job:
                meta["rejetees"] += 1
                meta["motifs"]["JSON-LD JobPosting incomplet"] = meta["motifs"].get("JSON-LD JobPosting incomplet", 0) + 1
                continue
            statut = getattr(job, "location_status", BE_UNKNOWN)
        else:
            statut = page["statut"]
            job = JobOffer(
                source=source, external_id=f"{hote}:{hashlib.sha1(url.encode('utf-8')).hexdigest()[:16]}",
                title=page["titre"], company=label,
                location=page["lieu"] or ("Belgique (site employeur)" if include_unknown else "Lieu non précisé"),
                description=page["texte"], url=url, date_published=None, contract_type=None,
                language=None, salary=None, date_collected=maintenant.isoformat(timespec="seconds"),
            )
            job.collection_channel = source
            job.origin_source = hote
            job.location_status = statut
            job.detail_enrichment_attempted = True
            job.detail_enrichment_success = True
            job.detail_matching_text_length = len(page["texte"])
        if statut in (BE_CONFIRMED, BE_LIKELY) or (statut == BE_UNKNOWN and include_unknown):
            jobs.append(job)
            meta["be"] += 1
        else:
            meta["hors_be"] += 1
    _ecrire_cache(hote, cache)
    if verbose:
        print(f"  {label:<24} liens={meta['liens']:<4} cache={meta['cache']:<4} visitées={meta['visitees']:<4} "
              f"BE={meta['be']:<4} rejetées={meta['rejetees']:<3} hors BE={meta['hors_be']}")
    return jobs, meta


def sonder(listing_url: str, session=None, pages: int = 3) -> dict:
    """Pour la decouverte : combien de liens d'offre, et combien de pages exploitables parmi les premieres."""
    jobs, meta = collect_html_site({"identifier": listing_url}, session, include_unknown=True, max_pages=pages)
    meta["exploitables"] = len(jobs)
    return meta


def collect_html_sites(companies: list[dict], verbose: bool = True) -> dict:
    session = requests.Session()
    jobs, report = [], []
    for c in companies:
        if not c.get("enabled", True):
            continue
        trouves, meta = collect_html_site(c, session, include_unknown=bool(c.get("include_unknown", True)), verbose=verbose)
        jobs.extend(trouves)
        report.append(meta)
        if meta.get("error") and verbose:
            print(f"  {meta['label']:<24} ⚠️  {meta['error']}")
    dedup = {}
    for j in jobs:
        dedup[j.external_id] = j
    return {"jobs": list(dedup.values()), "report": report}

"""
JOB HUNTER BELGIUM
MATRICE DE COUVERTURE DES SOURCES - OUTIL V1.0

    python -m diagnostics.source_coverage_matrix

Produit SOURCE_COVERAGE_MATRIX.csv a la racine du projet, a partir de ce
qui est constate, pas suppose :

    - sources/registry.py            : sources declarees, actives ou non
    - database/jobs.db               : offres par source, vues au dernier run
                                       complet, avec description exploitable
    - config/ats_employers_v2.json   : employeurs decouverts et valides
    - exports/logs/discovery_*/      : candidats sans voie, ATS sans connecteur

Puis une seconde partie, manuelle, pour les familles demandees par le
cahier des charges et absentes du projet (LinkedIn, Indeed, StepStone...),
avec la methode recommandee et la raison.

Ne modifie rien. Classe en OUTILS dans run_all.py.
"""

from __future__ import annotations

import csv
import glob
import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database" / "jobs.db"
SORTIE = ROOT / "SOURCE_COVERAGE_MATRIX.csv"

COLONNES = ["SOURCE", "FAMILLE", "EXISTE", "FONCTIONNE", "METHODE_ACTUELLE", "COUVERTURE",
            "PROBLEMES", "VALEUR_AJOUTEE_POTENTIELLE", "METHODE_RECOMMANDEE", "PRIORITE", "ACTION"]

FAMILLES = {
    "FOREM": "service public", "ACTIRIS": "service public", "VDAB": "service public",
    "TALENT_BRUSSELS": "public", "TRAVAILLERPOUR": "public", "VDAB_STUDENT_WEB": "etudiant",
    "JOBAT": "job board", "REFERENCES": "job board", "ICTJOB": "job board", "EUROPHARMAJOBS": "job board",
    "ARBEITNOW": "agregateur", "REMOTIVE": "agregateur", "ADZUNA": "agregateur API",
    "CAREERJET": "agregateur API", "JOOBLE": "agregateur API", "EURAXESS_BE": "academique",
    "SMARTRECRUITERS": "ATS", "RECRUITEE": "ATS", "GREENHOUSE": "ATS", "WORKDAY_ATS": "ATS",
    "SUCCESSFACTORS_ATS": "ATS", "PHENOM_ATS": "ATS", "LEVER": "ATS", "ASHBY": "ATS",
    "WORKABLE": "ATS", "PERSONIO": "ATS", "JSONLD_SITES": "universel",
}
_INTERIM = {"RANDSTAD", "ADECCO", "MANPOWER", "SYNERGIE", "START_PEOPLE", "TEMPO_TEAM", "VIVALDIS",
            "AGILITAS", "AGO", "KONVERT", "ACCENT_JOBS", "ACTIEF_INTERIM", "FORUM_JOBS", "ASAP_BE",
            "UNIQUE_BE", "JEFFERSON_WELLS", "AKKODIS", "EXPERIS", "ROBERT_HALF", "HAYS_BE",
            "MICHAEL_PAGE", "PAGE_PERSONNEL", "WALTERS_PEOPLE", "OXFORD_GLOBAL", "BRUNEL",
            "AUSTIN_BRIGHT", "PROGRESSIVE", "SELECT_HR", "LETS_WORK", "QJOBS", "BRIGHT_PLUS",
            "SECRETARY_PLUS", "SDWORX_STAFFING", "T_INTERIM", "ABSOLUTE_JOBS"}


def _famille(cle: str, notes: str) -> str:
    if cle in FAMILLES:
        return FAMILLES[cle]
    if cle in _INTERIM:
        return "interim / recrutement"
    if "STUDENT" in cle:
        return "etudiant"
    if any(x in cle for x in ("UCLOUVAIN", "ULB", "VUB", "SCIENSANO", "SIRRIS", "CRM_GROUP", "CELABOR")):
        return "academique / recherche"
    if any(x in cle for x in ("UZ_", "SAINT_LUC", "CHIREC")):
        return "sante"
    if any(x in cle for x in ("SNCB", "INFRABEL", "STIB", "BPOST", "SWDE", "DE_WATERGROEP", "BRUSSELS_AIRPORT", "AVIAPARTNER")):
        return "public / parapublic"
    return "employeur direct"


def _base() -> tuple[dict, str | None]:
    if not DB.exists():
        return {}, None
    c = sqlite3.connect(DB)
    dernier = c.execute("select run_id from collection_runs where status='COMPLETED' order by run_id desc limit 1").fetchone()
    dernier = dernier[0] if dernier else None
    rows = c.execute("""
        select source, count(*), sum(is_active),
               sum(case when last_run_id=? then 1 else 0 end),
               sum(case when length(coalesce(description,''))>800 or detail_enrichment_success=1 then 1 else 0 end)
        from raw_jobs group by source""", (dernier,)).fetchall()
    return {r[0]: {"total": r[1], "actives": r[2] or 0, "dernier_run": r[3], "desc_ok": r[4] or 0} for r in rows}, dernier


def _decouverte() -> tuple[dict, list]:
    reg = {}
    p = ROOT / "config" / "ats_employers_v2.json"
    if p.exists():
        for e in json.loads(p.read_text(encoding="utf-8")).get("employers", []):
            reg.setdefault(e.get("connector") or e.get("ats"), []).append(e)
    lignes = []
    for f in sorted(glob.glob(str(ROOT / "exports" / "logs" / "discovery_*" / "SOURCE_RESULTS.jsonl"))):
        # split("\n") et non splitlines() : un JSON peut contenir U+2028.
        for l in Path(f).read_text(encoding="utf-8").split("\n"):
            try:
                lignes.append(json.loads(l))
            except Exception:
                pass
    return reg, lignes


# Familles du cahier des charges absentes ou partielles : constat et recommandation.
MANUEL = [
    ("VDAB (direct)", "service public", "PARTIEL", "NON", "sitemap public (pages vides, JS ; /api interdit par robots.txt)",
     "0 direct ; 8 874 via Actiris (republication)", "API officielle sur cles (ibm-api-key)", "tres elevee : ~40 % des offres belges",
     "API officielle VDAB (demande de cles partenaire) ; en attendant republication Actiris", "1",
     "Demander un acces API VDAB ; conserver la voie Actiris VDAB_FOREM"),
    ("EURES", "international", "NON", "-", "-", "0", "portail JS ; API interne non documentee", "moyenne : beaucoup de doublons Forem/VDAB/Actiris",
     "EURES Job Vacancy API (acces institutionnel) ou decouverte via Actiris/Forem", "3", "Suivre ; pas de voie publique propre aujourd'hui"),
    ("LinkedIn Jobs", "job board", "NON", "-", "-", "0", "conditions d'utilisation interdisent la collecte automatisee ; anti-bot",
     "elevee en decouverte (URL employeur), faible en canonique", "decouverte seulement : URL de candidature externe -> ATSDetector ; jamais de scraping",
     "2", "Ne pas scraper ; utiliser LinkedIn comme signal de decouverte manuel (coller une URL)"),
    ("Indeed Belgique", "job board", "NON", "-", "-", "0", "anti-bot (Cloudflare), pas d'API publique",
     "elevee en volume, faible en unique (republication)", "URL de candidature externe -> ATSDetector ; fournisseur externe en dernier recours", "3",
     "Pas de scraper artisanal ; Apify/Zyte seulement si mesure cost_per_unique_job le justifie"),
    ("StepStone Belgique", "job board", "NON", "-", "-", "0 direct ; present via Forem/Actiris partenaires",
     "anti-bot ; republie ses offres vers Forem/Actiris", "moyenne", "republication Forem/Actiris (deja absorbee) ; JSON-LD sur pages si accessibles", "3",
     "Rien a faire : couvert indirectement par l'absorption complete"),
    ("Jobat (direct)", "job board", "OUI", "NON", "cache uniquement (HTTP 403 verifie)", "901 en cache ; 158/400 offres Forem partenaires viennent de Jobat",
     "403 anti-bot", "moyenne", "republication Forem/Actiris (absorbee) ; ne pas contourner", "3", "Garder CACHE_ONLY ; couvert par Forem/Actiris"),
    ("Jooble / Adzuna / Careerjet", "agregateur API", "OUI", "NON", "API officielles, cles absentes", "0", "NEEDS_CREDENTIALS",
     "moyenne : agregateurs, beaucoup de doublons ; Adzuna/Careerjet donnent des descriptions", "cles gratuites (formulaire en ligne)", "2",
     "L'utilisateur cree les cles (gratuites) et les met dans sources/api_credentials.py"),
    ("Talent.com / Monster / Glassdoor / Jobrapido / Jobsora / GrabJobs", "agregateur", "NON", "-", "-", "0",
     "pas d'API publique ; agregateurs de republication", "faible en unique", "aucune ; ils republient ce que l'on absorbe deja", "4", "Ignorer"),
    ("Federgon (annuaire)", "decouverte", "NON", "-", "-", "-", "-", "elevee : petites agences regionales",
     "annuaire -> domaines -> source_discovery_v1", "2", "Etape suivante : extraire l'annuaire en graines de decouverte"),
    ("BCE/KBO", "decouverte", "NON", "-", "-", "-", "pas de site web dans l'open data BCE", "tres elevee a terme",
     "open data BCE -> noms -> domaines (recherche) -> source_discovery_v1", "3", "Apres Federgon, quand la decouverte est stable"),
    ("Student.be / StudentJob / NOWJOBS", "etudiant", "PARTIEL", "OUI", "HTML (student_sources_v1)", "faible",
     "pages HTML", "moyenne", "JSON-LD si present (JSONLD_SITES)", "3", "Passer les hotes au moteur de decouverte"),
]


def main():
    from sources.registry import SOURCE_SPECS, load_source_settings
    base, dernier = _base()
    reg, decouverte = _decouverte()
    settings = load_source_settings()
    lignes = []

    for spec in SOURCE_SPECS:
        cle = spec.key
        b = base.get(cle) or base.get(spec.result_key.upper()) or {}
        actif = settings.get(cle, spec.enabled_default)
        module = spec.collector.__module__.replace("sources.", "")
        nb_emp = len(reg.get(cle, []))
        fonctionne = "OUI" if b.get("dernier_run") else ("INCONNU (jamais collectee)" if not b else "NON (rien au dernier run)")
        if cle in ("LEVER", "ASHBY", "WORKABLE", "PERSONIO", "JSONLD_SITES"):
            fonctionne = f"VALIDE (decouverte) ; {nb_emp} employeurs" if nb_emp else "NOUVEAU ; aucun employeur encore"
        if cle in ("FOREM", "ACTIRIS"):
            methode = "absorption complete du catalogue (V1.0) + detail par budget"
        else:
            methode = module
        problemes = ""
        if cle == "JOBAT":
            problemes = "HTTP 403 : cache seulement"
        elif cle == "VDAB":
            problemes = "pages JS ; API interdite par robots ; desactive"
        elif cle in ("ADZUNA", "CAREERJET", "JOOBLE"):
            problemes = "cles API absentes"
        elif b and not b.get("dernier_run"):
            problemes = "aucune offre au dernier run"
        elif not b and cle not in ("LEVER", "ASHBY", "WORKABLE", "PERSONIO", "JSONLD_SITES"):
            problemes = "declaree mais jamais une offre en base"
        couverture = (f"{b.get('actives', 0)} actives / {b.get('total', 0)} vues ; {b.get('desc_ok', 0)} avec description"
                      if b else ("-" if not nb_emp else f"{sum(int(e.get('jobs_be') or 0) for e in reg.get(cle, []))} offres BE validees"))
        if cle == "ACTIRIS":
            couverture += " -> catalogue complet : 33 208"
        if cle == "FOREM":
            couverture += " -> open data complet : 26 198"
        lignes.append({
            "SOURCE": cle, "FAMILLE": _famille(cle, spec.notes), "EXISTE": "OUI",
            "FONCTIONNE": fonctionne if actif else f"DESACTIVEE ({fonctionne})",
            "METHODE_ACTUELLE": methode, "COUVERTURE": couverture, "PROBLEMES": problemes,
            "VALEUR_AJOUTEE_POTENTIELLE": "", "METHODE_RECOMMANDEE": "", "PRIORITE": "", "ACTION": "",
        })

    for m in MANUEL:
        lignes.append(dict(zip(COLONNES, m)))

    # candidats de decouverte sans voie ou ATS sans connecteur : la prochaine frontiere
    sans = Counter()
    exemples = defaultdict(list)
    for l in decouverte:
        if l.get("statut") == "ATS_SANS_CONNECTEUR" and l.get("ats"):
            sans[l["ats"]] += 1
            if len(exemples[l["ats"]]) < 6:
                exemples[l["ats"]].append(str(l.get("label")))
    for ats, n in sans.most_common():
        lignes.append({
            "SOURCE": f"ATS {ats}", "FAMILLE": "ATS sans connecteur", "EXISTE": "DETECTE", "FONCTIONNE": "NON",
            "METHODE_ACTUELLE": "-", "COUVERTURE": f"{n} employeurs detectes : {', '.join(exemples[ats])}",
            "PROBLEMES": "connecteur a ecrire", "VALEUR_AJOUTEE_POTENTIELLE": "un connecteur = tous ces employeurs",
            "METHODE_RECOMMANDEE": "endpoint JSON interne ou sitemap + HTML", "PRIORITE": "2" if n >= 3 else "3",
            "ACTION": "ecrire le connecteur generique, brancher via ats_signatures.json",
        })

    with SORTIE.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLONNES, delimiter=";")
        w.writeheader()
        for l in lignes:
            w.writerow({k: l.get(k, "") for k in COLONNES})
    print(f"{len(lignes)} lignes -> {SORTIE}")
    print(f"dernier run complet : {dernier}")
    return SORTIE


if __name__ == "__main__":
    main()

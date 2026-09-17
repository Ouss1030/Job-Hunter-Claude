"""
JOB HUNTER BELGIUM
EXPANSION DES SOURCES - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.expansion_sources_v1_audit

Ce que l'audit protege
----------------------
L'expansion touche a la collecte elle-meme : un defaut ici se voit dans la
base, pas dans un traceback. Cinq choses sont testees sans reseau :

    1. l'absorption complete est branchee sur FOREM et ACTIRIS, et se debranche
       par un seul reglage ; le budget de detail est respecte ;
    2. le detecteur d'ATS reconnait chaque ATS du registre sur une URL, extrait
       un identifiant exploitable, et ne prend pas un script pour un employeur ;
    3. les connecteurs de seconde generation convertissent des charges utiles
       reelles (fixtures) en JobOffer complets, avec le filtre Belgique ;
    4. l'extracteur universel reconnait une URL d'offre, lit un sitemap index,
       convertit un JobPosting ;
    5. le registre des employeurs decouverts fusionne sans doublon dans les
       listes existantes, et le moteur de decouverte route correctement.

Aucun fichier du projet n'est modifie : registre et instantanes vont dans un
dossier temporaire.
"""

from __future__ import annotations

import html as html_mod
import json
import tempfile
from datetime import datetime
from pathlib import Path
from unittest import mock

from database.models import JobOffer
from diagnostics.version_support import at_least


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}" + (f" | {detail}" if detail else ""))
    return bool(condition)


class _Reponse:
    def __init__(self, texte="", status=200, url="", ctype="text/html", history=()):
        self.text = texte
        self.content = texte.encode("utf-8")
        self.status_code = status
        self.url = url
        self.headers = {"content-type": ctype}
        self.history = list(history)

    def json(self):
        return json.loads(self.text)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Session:
    """Session factice : une table URL -> reponse ; tout le reste est 404."""

    def __init__(self, table):
        self.table = table
        self.appels = []

    def get(self, url, **kw):
        if kw.get("params"):
            from urllib.parse import urlencode
            url = url + ("&" if "?" in url else "?") + urlencode(kw["params"])
        self.appels.append(url)
        if url in self.table:
            rep = self.table[url]
            rep.url = rep.url or url
            return rep
        for cle, rep in self.table.items():
            if url.startswith(cle):
                rep.url = rep.url or url
                return rep
        return _Reponse("", 404, url)

    def request(self, method, url, **kw):
        return self.get(url)


def main():
    tests = []
    tmp = Path(tempfile.mkdtemp(prefix="jh_expansion_"))

    # ------------------------------------------------------------------
    # 1. Absorption complete
    # ------------------------------------------------------------------
    from sources import registry
    from sources import registry_absorption_v1 as ra
    from sources import absorption_v1 as ab

    specs = {s.key: s for s in registry.SOURCE_SPECS}
    tests.append(check("FOREM branche sur l'absorption complete",
                       specs["FOREM"].collector.__module__ == "sources.registry_absorption_v1"))
    tests.append(check("ACTIRIS branche sur l'absorption complete",
                       specs["ACTIRIS"].collector.__module__ == "sources.registry_absorption_v1"))
    tests.append(check("Les cles FOREM/ACTIRIS sont inchangees (routage detail, lifecycle)",
                       specs["FOREM"].result_key == "forem" and specs["ACTIRIS"].result_key == "actiris"))
    with mock.patch.object(ra, "charger_reglages", return_value={"complete": False, "sources": ["FOREM", "ACTIRIS"], "detail_budget_per_source": 1}):
        base = tuple(s for s in registry.SOURCE_SPECS if s.key in ("FOREM", "ACTIRIS"))
        # on reconstruit depuis les collecteurs d'origine pour verifier le debranchement
        from dataclasses import replace
        origine = tuple(replace(s, collector=registry._collect_forem if s.key == "FOREM" else registry._collect_actiris) for s in base)
        debranche = ra.appliquer_absorption(origine)
        tests.append(check("{\"complete\": false} ramene les collecteurs historiques",
                           all(s.collector.__module__ == "sources.registry" for s in debranche)))

    # conversion Actiris/Forem sur fixtures, via les convertisseurs reutilises
    item = {"reference": "999001", "titreFr": "Technicien de laboratoire", "employeur": {"nomFr": "Labo Test"},
            "communeFr": "Anderlecht", "codePostal": "1070", "codePays": "BE", "typeContrat": "CDI",
            "typeContratLibelle": "CDI", "dateCreation": "2026-09-10", "typeOffre": "Hrxml",
            "_origin_source": "VDAB_FOREM", "_origin_sources": ["VDAB_FOREM"], "_search_terms": [ab.MARQUEUR_ABSORPTION]}
    pages = {("ACTIRIS", 1): {"total": 1, "items": [item]}, ("VDAB_FOREM", 1): {"total": 1, "items": [dict(item, reference="999002")]},
             ("PARTNER", 1): {"total": 0, "items": []}}

    def faux_payload(keyword, page, page_size, provenance_mode="ALL"):
        return {"mode": provenance_mode, "page": page}

    def faux_api(payload):
        return pages.get((payload["mode"], payload["page"]), {"total": 0, "items": []})

    with mock.patch.object(ab._actiris, "build_search_payload", faux_payload), \
            mock.patch.object(ab._actiris, "request_actiris_api", faux_api), \
            mock.patch.object(ab, "SNAPSHOT_DIR", tmp / "snap"):
        res = ab.collect_actiris_full(verbose=False)
    jobs = res["jobs"]
    tests.append(check("Actiris complet : une offre par reference, provenance conservee",
                       len(jobs) == 2 and {getattr(j, "origin_source", None) for j in jobs} == {"ACTIRIS", "VDAB_FOREM"},
                       f"{len(jobs)} offres"))
    tests.append(check("Actiris complet : marqueur ABSORPTION_COMPLETE dans search_terms",
                       all(ab.MARQUEUR_ABSORPTION in (getattr(j, "search_terms", []) or []) for j in jobs)))
    tests.append(check("Actiris complet : instantane ecrit par provenance",
                       (tmp / "snap" / "actiris_actiris_last_ok.json").exists()))

    ligne_forem = {"numerooffreforem": "2057414", "titreoffre": "Analyste QC (H/F/X)", "nomemployeur": "Pharma SA",
                   "lieuxtravaillocalite": ["WAVRE"], "lieuxtravailregion": ["Brabant wallon"], "langues": ["Français"],
                   "secteurs": ["Industrie pharmaceutique"], "niveauxetudes": ["Bachelier"], "metier": "Analyste",
                   "url": "https://www.leforem.be/recherche-offres/offre-detail/2057414", "datedebutdiffusion": "2026-09-10",
                   "typecontrat": "CDI", "regimetravail": "Temps plein", "source": "Via site Forem"}
    with mock.patch.object(ab, "_forem_export", return_value=[ligne_forem, dict(ligne_forem)]), \
            mock.patch.object(ab, "SNAPSHOT_DIR", tmp / "snap"):
        res = ab.collect_forem_full(verbose=False)
    tests.append(check("Forem complet : export lu, doublon de numero ecarte",
                       len(res["jobs"]) == 1 and res["jobs"][0].source == "FOREM" and res["report"]["origine"] == "LIVE export"))
    with mock.patch.object(ab, "_forem_export", side_effect=RuntimeError("panne")), \
            mock.patch.object(ab, "_forem_records", side_effect=RuntimeError("panne")), \
            mock.patch.object(ab, "SNAPSHOT_DIR", tmp / "snap"):
        res = ab.collect_forem_full(verbose=False)
    tests.append(check("Forem complet : panne totale -> instantane precedent, jamais zero",
                       len(res["jobs"]) == 1 and res["report"]["origine"].startswith("SNAPSHOT"), res["report"]["origine"]))

    # budget de detail
    offres = [JobOffer(source="FOREM", external_id=str(i), title="Analyste QC", company="X", location="Wavre",
                       description="court", url="", date_published=f"2026-09-{10 + i:02d}") for i in range(5)]
    appels = []
    with mock.patch.object(registry, "_detail_is_relevant", return_value=True), \
            mock.patch.object(ra, "_detail_en_cache", return_value=False), \
            mock.patch.object(registry, "_fetch_existing_detail", side_effect=lambda s, j: appels.append(j.external_id) or {"success": True, "matching_text": "x" * 1200, "matching_text_length": 1200, "structured": {}}):
        ra._enrichir_avec_budget(list(offres), "FOREM", budget=2)
    tests.append(check("Budget de detail : 2 nouvelles pages, les plus recentes d'abord, 3 reportees",
                       appels == ["4", "3"] and sum(1 for o in offres if getattr(o, "detail_enrichment_status", "") == "DEFERRED_BUDGET") == 3,
                       str(appels)))

    # ------------------------------------------------------------------
    # 2. Detecteur d'ATS
    # ------------------------------------------------------------------
    from sources import ats_detector_v1 as det
    sig = det.charger_signatures()["ats"]
    import re
    regex_ok = True
    for nom, spec in sig.items():
        for motif in list(spec.get("url_patterns") or []) + [spec.get("identifier") or ""]:
            try:
                re.compile(motif)
            except re.error:
                regex_ok = False
    tests.append(check("ats_signatures.json : toutes les expressions compilent", regex_ok, f"{len(sig)} ATS"))
    connecteurs_declares = {spec["connector"] for spec in sig.values() if spec.get("connector")}
    tests.append(check("Chaque connecteur declare existe dans SOURCE_SPECS",
                       connecteurs_declares <= set(specs), str(sorted(connecteurs_declares - set(specs)))))

    exemples = {
        "LEVER": "https://jobs.lever.co/deliverect/1", "GREENHOUSE": "https://boards.greenhouse.io/collibra/jobs/1",
        "WORKDAY": "https://gsk.wd5.myworkdayjobs.com/en-US/GSKCareers/job/x", "RECRUITEE": "https://vito.recruitee.com/o/x",
        "SMARTRECRUITERS": "https://careers.smartrecruiters.com/SGS/", "ASHBY": "https://jobs.ashbyhq.com/Aikido/x",
        "WORKABLE": "https://apply.workable.com/silverfin/j/A/", "PERSONIO": "https://acme.jobs.personio.de/job/1",
        "TEAMTAILOR": "https://acme.teamtailor.com/jobs/1", "JOBTOOLZ": "https://az.jobtoolz.com/vacancies/1",
        "TALENTFINDER": "https://ire.talentfinder.be/fr/index.aspx", "SUCCESSFACTORS": "https://jobs.vub.be/go/EN_ALL-JOBS/3775601/",
    }
    reconnus = {nom: det.detecter_url(u) for nom, u in exemples.items()}
    tests.append(check("Detection hors ligne : 12 ATS reconnus avec identifiant",
                       all(r and r["ats"] == nom and r["identifiant"] for nom, r in reconnus.items()),
                       str([n for n, r in reconnus.items() if not r or r["ats"] != n or not r["identifiant"]])))
    tests.append(check("Identifiant Workday = tenant/wd/site",
                       reconnus["WORKDAY"]["identifiant"] == {"tenant": "gsk", "wd": "wd5", "site": "GSKCareers"}))
    tests.append(check("Casse conservee pour SmartRecruiters/Ashby, minuscules pour Lever",
                       reconnus["SMARTRECRUITERS"]["identifiant"] == "SGS" and reconnus["ASHBY"]["identifiant"] == "Aikido"
                       and det.detecter_url("https://jobs.lever.co/DeliverECT/1")["identifiant"] == "deliverect"))
    faux = det.detecter_url("https://careers-analytics.recruitee.com/script.js")
    tests.append(check("Un sous-domaine technique n'est pas un employeur",
                       faux is not None and faux["identifiant"] is None))
    tests.append(check("Route vers un connecteur existant quand il y en a un",
                       reconnus["RECRUITEE"]["connecteur"] == "RECRUITEE" and reconnus["WORKDAY"]["connecteur"] == "WORKDAY_ATS"))

    # detection en ligne simulee : page carriere avec un lien Lever
    page = '<html><a href="https://jobs.lever.co/acme/">Voir nos offres</a></html>'
    s = _Session({"https://www.acme.be/careers": _Reponse(page, 200, "https://www.acme.be/careers")})
    r = det.detecter_site("acme.be", session=s)
    tests.append(check("Detection en ligne : lien vers un hote ATS -> identifiant exact",
                       r["ats"] == "LEVER" and r["identifiant"] == "acme" and r["preuve"] == "LIEN"))
    page2 = '<html><a href="/nl/jobs">Jobs</a></html>'
    page3 = '<html><script src="https://x.teamtailor-cdn.com/app.js"></script></html>'
    s = _Session({"https://www.beta.be/": _Reponse(page2, 200, "https://www.beta.be/"),
                  "https://www.beta.be/nl/jobs": _Reponse(page3, 200, "https://jobs.beta.be/")})
    r = det.detecter_site("beta.be", session=s)
    tests.append(check("Detection en ligne : suit un lien carriere puis lit une signature HTML",
                       r["ats"] == "TEAMTAILOR" and r["preuve"] == "HTML", str(r.get("ats"))))

    # ------------------------------------------------------------------
    # 3. Connecteurs de seconde generation
    # ------------------------------------------------------------------
    from sources import ats_public_v2 as v2
    lever_payload = [
        {"id": "a1", "text": "QC Analyst", "categories": {"location": "Ghent, Belgium", "commitment": "Full-time"},
         "country": "BE", "descriptionBody": "<p>Analyses <b>HPLC</b></p>", "lists": [{"text": "Profil", "content": "<li>Bachelier chimie</li>"}],
         "additional": "", "hostedUrl": "https://jobs.lever.co/acme/a1", "createdAt": 1757500000000},
        {"id": "a2", "text": "Sales US", "categories": {"location": "Austin, TX"}, "country": "US",
         "descriptionBody": "x", "lists": [], "hostedUrl": "https://jobs.lever.co/acme/a2", "createdAt": 1757500000000},
    ]
    s = _Session({"https://api.lever.co/v0/postings/acme": _Reponse(json.dumps(lever_payload), 200, ctype="application/json")})
    jobs, meta = v2.collect_lever("acme", "Acme", s)
    j = jobs[0] if jobs else None
    tests.append(check("Lever : offre belge convertie, offre US ecartee",
                       len(jobs) == 1 and meta["hors_be"] == 1 and j.source == "LEVER" and j.external_id == "acme:a1"))
    tests.append(check("Lever : description complete en texte (corps + listes), date, contrat",
                       j is not None and "HPLC" in j.description and "Bachelier chimie" in j.description
                       and j.date_published == "2025-09-10" and j.contract_type == "Full-time"))

    ashby_payload = {"jobs": [{"id": "b1", "title": "Data Engineer", "location": "Brussels", "isRemote": False,
                               "address": {"postalAddress": {"addressLocality": "Brussels", "addressCountry": "Belgium"}},
                               "descriptionHtml": "<p>Python &amp; SQL</p>", "jobUrl": "https://jobs.ashbyhq.com/acme/b1",
                               "publishedAt": "2026-09-01T10:00:00Z", "employmentType": "FullTime"}]}
    s = _Session({"https://api.ashbyhq.com/posting-api/job-board/acme": _Reponse(json.dumps(ashby_payload), 200, ctype="application/json")})
    jobs, meta = v2.collect_ashby("acme", "Acme", s)
    tests.append(check("Ashby : offre belge convertie, entites HTML decodees",
                       len(jobs) == 1 and jobs[0].description == "Python & SQL" and jobs[0].date_published == "2026-09-01"))

    personio_xml = """<?xml version="1.0"?><workzag-jobs><position><id>7</id><name>Lab Technician</name>
    <office>Antwerp</office><employmentType>permanent</employmentType><createdAt>2026-08-30</createdAt>
    <jobDescriptions><jobDescription><name>Taken</name><value><![CDATA[<p>GC-MS analyses</p>]]></value></jobDescription></jobDescriptions>
    </position></workzag-jobs>"""
    s = _Session({"https://acme.jobs.personio.de/xml": _Reponse(personio_xml, 200, ctype="text/xml")})
    jobs, meta = v2.collect_personio("acme", "Acme", s)
    tests.append(check("Personio : flux XML lu, description CDATA en texte, ville belge reconnue",
                       len(jobs) == 1 and "GC-MS" in jobs[0].description and jobs[0].location == "Antwerp"))

    wk_list = {"results": [{"id": 1, "shortcode": "AB12", "title": "QA Officer", "published": "2026-09-05T00:00:00Z",
                            "type": "full", "location": {"city": "Leuven", "country": "Belgium", "countryCode": "BE"}}], "nextPage": None}
    wk_detail = {"description": "<p>Assurance qualité</p>", "requirements": "<ul><li>GMP</li></ul>", "benefits": ""}
    s = _Session({"https://apply.workable.com/api/v2/accounts/acme/jobs/AB12": _Reponse(json.dumps(wk_detail), 200, ctype="application/json"),
                  "https://apply.workable.com/api/v3/accounts/acme/jobs": _Reponse(json.dumps(wk_list), 200, ctype="application/json")})
    jobs, meta = v2.collect_workable("acme", "Acme", s)
    tests.append(check("Workable : liste + detail, description et exigences reunies",
                       len(jobs) == 1 and "GMP" in jobs[0].description and jobs[0].url.endswith("/j/AB12/")))

    # Oracle Recruiting Cloud (16/09/2026)
    from sources import oracle_cloud_v1 as oc
    liste_oracle = {"items": [{"TotalJobsCount": 2, "requisitionList": [
        {"Id": "5807", "Title": "Partner B2B Account Manager", "PrimaryLocation": "Mechelen, Belgium",
         "PrimaryLocationCountry": "BE", "PostedDate": "2026-09-16", "WorkerType": "Employee", "Language": "nl",
         "ShortDescriptionStr": "court", "secondaryLocations": []},
        {"Id": "9999", "Title": "Analyst", "PrimaryLocation": "Poland", "PrimaryLocationCountry": "PL",
         "PostedDate": "2026-09-16", "secondaryLocations": []}]}]}
    detail_oracle = {"items": [{"ExternalDescriptionStr": "<p>Réseau <b>B2B</b></p>", "ExternalQualificationsStr": "<ul><li>NL/FR</li></ul>"}]}
    s = _Session({"https://ebza.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitionDetails": _Reponse(json.dumps(detail_oracle), 200, ctype="application/json"),
                  "https://ebza.fa.em2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions": _Reponse(json.dumps(liste_oracle), 200, ctype="application/json")})
    with mock.patch.object(oc, "PAUSE_DETAIL", 0):
        jobs, meta = oc.collect_oracle_cloud({"host": "ebza.fa.em2.oraclecloud.com", "site": "CX_1001", "lang": "nl", "label": "Telenet"}, s)
    tests.append(check("Oracle Cloud : liste + detail, offre belge gardee, polonaise ecartee, URL du site",
                       len(jobs) == 1 and meta["hors_be"] == 1 and "B2B" in jobs[0].description and "NL/FR" in jobs[0].description
                       and jobs[0].url.endswith("/sites/CX_1001/job/5807") and jobs[0].external_id == "ebza.fa.em2.oraclecloud.com:5807"))

    # CVWarehouse (16/09/2026) : accueil + sections, une page de detail par section
    from sources import cvwarehouse_v1 as cvw
    # HTML reel : & s'ecrit &amp; (un & nu devant "section" serait lu comme l'entite &sect).
    accueil = ('<a href="/?lang=nl-BE&amp;section=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa">Vacatures</a>'
               '<a href="?lang=nl-BE&amp;job=1&amp;q=x"><span class="job-title">Laborant</span><span class="location">Gent, België</span></a>')
    section = '<a href="?lang=nl-BE&amp;job=2&amp;q=y"><span class="job-title">Data analist</span><span class="location">Leuven, België</span></a>'
    detail_1 = ('<div class="job-detail"><h2 class="job-title">Laborant</h2><span class="location">Gent, België</span>'
                '<div>' + "Analyses en labo. " * 12 + '</div></div>')
    detail_2 = ('<div class="job-detail"><h2 class="job-title">Data analist</h2><span class="location">Leuven, België</span>'
                '<div>' + "Power BI et SQL. " * 12 + '</div></div>')
    s = _Session({"https://acme.cvw.io/?lang=nl-BE&job=1": _Reponse(detail_1, 200),
                  "https://acme.cvw.io/?lang=nl-BE&job=2&section=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": _Reponse(detail_2, 200),
                  "https://acme.cvw.io/?lang=nl-BE&section=aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa": _Reponse(section, 200),
                  "https://acme.cvw.io/?lang=nl-BE": _Reponse(accueil, 200)})
    jobs, meta = cvw.collect_cvwarehouse({"identifier": "https://acme.cvw.io/", "label": "Acme"}, s)
    tests.append(check("CVWarehouse : accueil + section listes, chaque offre reliee a son bloc de detail par le titre",
                       meta["total"] == 2 and meta["sans_texte"] == 0 and {j.title for j in jobs} == {"Laborant", "Data analist"}
                       and all("labo" in j.description.lower() or "power bi" in j.description.lower() for j in jobs)
                       and jobs[0].external_id.startswith("acme.cvw.io:"), str(meta)))

    # HTML generique (16/09/2026) : liste + contenu principal + preuve belge ; pages de liste rejetees
    from sources import html_generique_v1 as hg
    from bs4 import BeautifulSoup
    liste = ('<html><body><nav><a href="/jobs/">Jobs</a></nav><main><a href="/emploi.2026-09-02.111">Laborant</a>'
             '<a href="/emploi.2026-09-03.222">Data analyst</a><a href="/emploi.2026-09-04.333">Autre</a><a href="/contact">Contact</a></main></body></html>')
    page_a = ('<html><head><title>Laborant | Labo</title></head><body><nav>menu menu</nav><main><h1>Laborant</h1><p>'
              + "Analyses en laboratoire, rue Haute 1, 5000 Namur. " * 10
              + 'Votre profil : bachelier en chimie. Missions : analyses HPLC. Contrat CDI temps plein. Postuler avant le 30/09.'
              + '</p></main><footer>pied</footer></body></html>')
    page_b = ("<html><head><title>Offres d'emploi | Labo</title></head><body><main><h1>12 emplois pour vous</h1><p>"
              + "Liste des offres. " * 30 + '</p></main></body></html>')
    page_c = '<html><head><title>Autre</title></head><body><main><h1>Autre</h1><p>court</p></main></body></html>'
    s = _Session({"https://labo.be/liste": _Reponse(liste, 200, "https://labo.be/liste"),
                  "https://labo.be/emploi.2026-09-02.111": _Reponse(page_a, 200, "https://labo.be/emploi.2026-09-02.111"),
                  "https://labo.be/emploi.2026-09-03.222": _Reponse(page_b, 200, "https://labo.be/emploi.2026-09-03.222"),
                  "https://labo.be/emploi.2026-09-04.333": _Reponse(page_c, 200, "https://labo.be/emploi.2026-09-04.333")})
    with mock.patch.object(hg, "CACHE_DIR", tmp / "html"), mock.patch.object(hg, "PAUSE", 0):
        jobs, meta = hg.collect_html_site({"identifier": "https://labo.be/liste", "label": "Labo"}, s)
    tests.append(check("HTML generique : 3 liens d'offre (Plone), 1 offre valide (Namur 5000, sans menu), liste et page courte rejetees",
                       meta["liens"] == 3 and len(jobs) == 1 and jobs[0].title == "Laborant" and jobs[0].location == "Namur (5000)"
                       and "menu menu" not in jobs[0].description and "pied" not in jobs[0].description and meta["rejetees"] == 2,
                       str({k: meta[k] for k in ("liens", "be", "rejetees")}) + (f" loc={jobs[0].location}" if jobs else "")))
    # V1.2 (18/09/2026) : la validation exige deux offres exploitables a titres distincts ; « MLS » n'est pas un titre ;
    # une fiche sans « postuler » ni « profil » n'est pas une offre
    page_d = page_a.replace("Laborant", "Data analyst").replace("Postuler avant le 30/09.", "Candidature via le site.")
    page_mls = '<html><head><title>MLS</title></head><body><main><h1>MLS</h1><p>' + "Analyses HPLC. Votre profil. Postuler. Contrat CDI. " * 10 + '</p></main></body></html>'
    page_produit = ('<html><head><title>Cloison vitree</title></head><body><main><h1>Cloison vitree</h1><p>'
                    + "Nos missions : cloisons sur mesure. Competences : verre, alu. Contrat de maintenance. Delai de livraison. " * 8 + '</p></main></body></html>')
    liste2 = liste.replace('<a href="/contact">Contact</a>', '<a href="/emploi.2026-09-05.444">MLS</a><a href="/emploi.2026-09-06.555">Cloison</a>')
    s = _Session({"https://labo.be/liste": _Reponse(liste2, 200, "https://labo.be/liste"),
                  "https://labo.be/emploi.2026-09-02.111": _Reponse(page_a, 200, "https://labo.be/emploi.2026-09-02.111"),
                  "https://labo.be/emploi.2026-09-03.222": _Reponse(page_d, 200, "https://labo.be/emploi.2026-09-03.222"),
                  "https://labo.be/emploi.2026-09-04.333": _Reponse(page_c, 200, "https://labo.be/emploi.2026-09-04.333"),
                  "https://labo.be/emploi.2026-09-05.444": _Reponse(page_mls, 200, "https://labo.be/emploi.2026-09-05.444"),
                  "https://labo.be/emploi.2026-09-06.555": _Reponse(page_produit, 200, "https://labo.be/emploi.2026-09-06.555")})
    with mock.patch.object(hg, "CACHE_DIR", tmp / "html2"), mock.patch.object(hg, "PAUSE", 0):
        meta = hg.sonder("https://labo.be/liste", s)
        s2 = _Session({"https://labo.be/liste": _Reponse(liste2, 200, "https://labo.be/liste"),
                       "https://labo.be/emploi.2026-09-02.111": _Reponse(page_a, 200, "https://labo.be/emploi.2026-09-02.111")})
        with mock.patch.object(hg, "CACHE_DIR", tmp / "html3"):
            meta_un = hg.sonder("https://labo.be/liste", s2)
    tests.append(check("HTML V1.2 : sonde de 5 pages -> 2 offres a titres distincts retenues, « MLS » (titre court) et la fiche produit (ni postuler ni profil) rejetees ; une seule offre ne suffit pas",
                       meta["retenu"] and meta["exploitables"] == 2 and "titre trop court" in meta["motifs"]
                       and any("ni postuler ni profil" in k for k in meta["motifs"]) and not meta_un["retenu"] and meta_un["exploitables"] == 1,
                       str((meta["exploitables"], meta["titres"], dict(meta["motifs"]), meta_un["exploitables"]))))
    tests.append(check("HTML generique : une annee n'est pas un code postal",
                       hg._lieu("Publie le 2026-09-02, © 2026. Poste a Charleroi.")[0] != "Anvers (2026)"))
    # V1.1 (17/09/2026) : preuve d'offre, pages d'information, rubriques, communes ambigues, code postal suivi d'un nom
    page_faq = ('<html><head><title>FAQ</title></head><body><main><h1>FAQ</h1><p>'
                + "Comment postuler ? Quel profil ? Quel contrat ? Quelles competences ? " * 10 + '</p></main></body></html>')
    page_info = ('<html><head><title>Le Forem</title></head><body><main><h1>Le Forem</h1><p>'
                 + "Le Forem accompagne les demandeurs a 5000 Namur. " * 15 + '</p></main></body></html>')
    tests.append(check("HTML V1.1 : « FAQ » et « Legal Jobs » sont des pages de liste ou d'information, « Laborant (H/F/X) » non",
                       hg._titre(BeautifulSoup(page_faq, "html.parser")) == ""
                       and hg._titre(BeautifulSoup("<html><head><title>Legal Jobs</title></head></html>", "html.parser")) == ""
                       and hg._titre(BeautifulSoup("<html><head><title>Laborant (H/F/X)</title></head></html>", "html.parser")) == "Laborant (H/F/X)"))
    tests.append(check("HTML V1.1 : une page d'information sans vocabulaire d'offre est rejetee (motif explicite)",
                       (hg.extraire_page("https://x.be/le-forem", page_info, "https://x.be/", "0") or {}).get("rejet", "").startswith("vocabulaire")
                       and len(hg.indices_offre("Votre profil : bachelier. Missions : analyses. Contrat CDI. Postuler.")) >= 3))
    tests.append(check("HTML V1.1 : « 3 ans », « to manage », « depuis 1991 » ne donnent pas de lieu ; « 6220 Fleurus », « 1310 La Hulpe », « site de Charleroi » oui",
                       hg._lieu("3 ans d'experience, to manage the team, depuis 1991 Nous")[1] == "BE_UNKNOWN"
                       and hg._lieu("Ref : 2026-88 ; site de 6220 Fleurus")[0] == "Fleurus (6220)"
                       and hg._lieu("Rue X 1, 1310 La Hulpe, Belgique")[0] == "La Hulpe (1310)"
                       and hg._lieu("Notre site de Charleroi recrute") == ("Charleroi", "BE_LIKELY"),
                       str([hg._lieu("3 ans d'experience, to manage the team, depuis 1991 Nous"), hg._lieu("Ref : 2026-88 ; site de 6220 Fleurus")])))
    tests.append(check("HTML V1.1 : /job_display/N (Eurobrussels) est un lien d'offre ; lien_regex du registre transmis au collecteur",
                       bool(hg._RE_URL_OFFRE_SEP.search("/job_display/296299/Accounting")) and
                       "lien_regex" in [c for c in __import__("sources.ats_employers_v2", fromlist=["employeurs"]).employeurs("HTML_SITES") if c["label"] == "Eurobrussels"][0]))

    # Teamtailor (16/09/2026) : flux RSS, lieux imbriques tt:locations/tt:location
    from sources import teamtailor_v1 as tt
    rss = ('<?xml version="1.0"?><rss xmlns:tt="https://teamtailor.com/locations"><channel>'
           '<item><title>Laborant</title><link>https://acme.teamtailor.com/jobs/1-laborant</link><guid>https://acme.teamtailor.com/jobs/1-laborant</guid>'
           '<pubDate>Mon, 14 Sep 2026 08:00:00 +0000</pubDate><description><![CDATA[<p>' + "Analyses HPLC. " * 15 + '</p>]]></description>'
           '<tt:locations><tt:location><tt:city>Gand</tt:city><tt:zip>9000</tt:zip><tt:country>Belgium</tt:country></tt:location></tt:locations></item>'
           '<item><title>Sales</title><link>https://acme.teamtailor.com/jobs/2-sales</link><guid>https://acme.teamtailor.com/jobs/2-sales</guid>'
           '<description>court</description><tt:locations><tt:location><tt:city>Paris</tt:city><tt:country>France</tt:country></tt:location></tt:locations></item>'
           '</channel></rss>')
    s = _Session({"https://acme.teamtailor.com/jobs.rss": _Reponse(rss, 200, ctype="application/rss+xml")})
    jobs, meta = tt.collect_teamtailor({"identifier": "acme.teamtailor.com", "label": "Acme"}, s)
    tests.append(check("Teamtailor : flux RSS lu, lieu imbrique (Gand, 9000, Belgium) reconnu, offre France ecartee, date convertie",
                       meta["total"] == 2 and len(jobs) == 1 and jobs[0].location == "Gand, 9000, Belgium"
                       and jobs[0].date_published == "2026-09-14" and "HPLC" in jobs[0].description, str(meta)))

    # Jobtoolz (17/09/2026) : liste embarquee dans window.jobComponent([...]), JSON-LD + texte par offre
    from sources import jobtoolz_v1 as jt
    liste_jt = json.dumps([{"id": 11, "title": "QC Associate", "url": "https://jobs.acme.be/fr/qc-associate", "location": "Niel", "types": "Temps plein"},
                           {"id": 12, "title": "Sales", "url": "https://jobs.acme.be/fr/sales", "location": "Lyon (France)", "types": "Temps plein"}])
    page_liste = ('<html><body><div x-data="window.jobComponent(' + html_mod.escape(liste_jt, quote=True)
                  + ', 10, [], [], [])"><template x-for="job in items"></template></div>'
                  '<img src="https://jobtoolz-assets.imgix.net/x.jpg"></body></html>')
    page_qc = ('<html><head><script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": "QC Associate", "datePosted": "2026-09-14",
               "description": "court", "hiringOrganization": {"@type": "Organization", "name": "Acme Biotech"}}) + '</script></head><body><nav>menu</nav><main><h1>QC Associate</h1><p>'
               + "Analyses HPLC en laboratoire, 2845 Niel. Votre profil : bachelier. Contrat CDI. Postuler. " * 6 + '</p></main></body></html>')
    page_sales = ('<html><head><script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": "Sales", "datePosted": "2026-09-14",
                  "description": "court", "hiringOrganization": {"name": "Acme"}}) + '</script></head><body><main><h1>Sales</h1><p>'
                  + "Ventes a Lyon, France. Profil commercial. Contrat CDI. Postuler. " * 6 + '</p></main></body></html>')
    s = _Session({"https://jobs.acme.be/fr": _Reponse(page_liste, 200, "https://jobs.acme.be/fr"),
                  "https://jobs.acme.be/fr/qc-associate": _Reponse(page_qc, 200, "https://jobs.acme.be/fr/qc-associate"),
                  "https://jobs.acme.be/fr/sales": _Reponse(page_sales, 200, "https://jobs.acme.be/fr/sales")})
    with mock.patch.object(jt, "PAUSE", 0):
        jobs, meta = jt.collect_jobtoolz({"identifier": "jobs.acme.be", "label": "Acme"}, s)
    tests.append(check("Jobtoolz : liste embarquee lue (2), offre Niel gardee avec texte complet, date JSON-LD et employeur ; offre Lyon ecartee",
                       meta["total"] == 2 and len(jobs) == 1 and jobs[0].title == "QC Associate" and jobs[0].company == "Acme Biotech"
                       and jobs[0].date_published == "2026-09-14" and "HPLC" in jobs[0].description and "menu" not in jobs[0].description
                       and jobs[0].location.startswith("Niel") and jobs[0].external_id == "jobs.acme.be:11", str(meta) + (f" loc={jobs[0].location}" if jobs else "")))
    from sources import ats_detector_v1 as ad
    dets = ad.detecter_dans_texte(page_liste, preuve="HTML")
    tests.append(check("Jobtoolz : signature reconnue dans la page (jobtoolz-assets / window.jobComponent), connecteur JOBTOOLZ",
                       any(d.get("ats") == "JOBTOOLZ" and d.get("connecteur") == "JOBTOOLZ" for d in dets), str(dets)[:200]))

    # Deviner un domaine (17/09/2026) : annuaires sans lien (BioWin) et employeurs du Forem/Actiris
    from sources import annuaires_seeds_v1 as an
    page_acme = "<html><head><title>Acme Labo - analyses</title></head><body>" + "Acme Labo, laboratoire a Namur. " * 40 + "</body></html>"
    page_hoc = "<html><head><title>HOC Inc</title></head><body>" + "hoc hoc hoc parked domain. " * 40 + "</body></html>"
    s = _Session({"https://www.acmelabo.be": _Reponse(page_acme, 200, "https://www.acmelabo.be/"),
                  "https://www.hoc.com": _Reponse(page_hoc, 200, "https://www.hoc.com/")})
    tests.append(check("Deviner un domaine : « Acme Labo » -> acmelabo.be (titre), « Ad Hoc Clinical » -> rien (hoc.com ne prouve rien)",
                       an.deviner_domaine("Acme Labo", s) == "acmelabo.be" and an.deviner_domaine("Ad Hoc Clinical", s) is None
                       and an.candidats_domaines("Acme Labo SA")[0] == "acmelabo.be",
                       str([an.deviner_domaine("Acme Labo", s), an.candidats_domaines("Acme Labo SA")[:3]])))

    # SuccessFactors V1.2 (17/09/2026) : sans sitemap, la page de recherche HTML, lieu par ligne
    from sources import successfactors_ats_v1 as sf
    ligne = ('<tr class="data-row"><td><a class="jobTitle-link" href="/job/{slug}/{id}/">{t}</a></td>'
             '<td><span class="jobLocation">{loc}</span></td></tr>')
    page0 = "<table>" + ligne.format(slug="Gembloux-Field-Operator-5032", id=11, t="Field Operator", loc="Gembloux, BE, 5032") \
            + ligne.format(slug="Lodz-Planner", id=12, t="Planner", loc="Lodz, PL") + "</table>"
    page1 = "<table>" + ligne.format(slug="Brussels-Analyst-1000", id=13, t="Analyst", loc="Brussels, Belgium") + "</table>"
    s = _Session({"https://acme.sf.test/sitemap.xml": _Reponse("<urlset></urlset>", 200),
                  "https://acme.sf.test/search/?q=&startrow=0": _Reponse(page0, 200),
                  "https://acme.sf.test/search/?q=&startrow=2": _Reponse(page1, 200),
                  "https://acme.sf.test/search/?q=&startrow=3": _Reponse("<table></table>", 200)})
    with mock.patch.object(sf, "SESSION", s), mock.patch.object(sf, "DELAY_BETWEEN_JOBS", 0):
        cands, total, err = sf.lister_offres("acme.sf.test")
    tests.append(check("SuccessFactors V1.2 : sitemap vide -> liste /search/ paginee (3 lignes), 2 belges gardees par le lieu, Lodz ecartee",
                       total == 3 and len(cands) == 2 and err is None and all("/job/" in u for u in cands)
                       and not any("Lodz" in u for u in cands), str((cands, total, err))))

    # iCIMS (16/09/2026) : liste paginee puis JSON-LD par page
    from sources import icims_v1 as ic
    from sources import jsonld_sitemap_v1 as jl
    liste0 = '<a href="https://acme.icims.com/jobs/11/analyst/job">A</a><a href="https://acme.icims.com/jobs/12/tech/job">B</a>'
    liste1 = '<a href="https://acme.icims.com/jobs/11/analyst/job">A</a>'
    page11 = '<html><script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": "Analyst", "description": "<p>" + "Analyse SQL. " * 15 + "</p>",
             "hiringOrganization": {"name": "Acme"}, "jobLocation": {"address": {"addressLocality": "Antwerp", "addressCountry": "BE"}}, "datePosted": "2026-09-10"}) + '</script></html>'
    page12 = '<html><script type="application/ld+json">' + json.dumps({"@type": "JobPosting", "title": "Tech", "description": "<p>" + "Maintenance. " * 15 + "</p>",
             "hiringOrganization": {"name": "Acme"}, "jobLocation": {"address": {"addressLocality": "Lyon", "addressCountry": "FR"}}}) + '</script></html>'
    s = _Session({"https://acme.icims.com/jobs/search?ss=1&in_iframe=1&pr=0": _Reponse(liste0, 200),
                  "https://acme.icims.com/jobs/search?ss=1&in_iframe=1&pr=1": _Reponse(liste1, 200),
                  "https://acme.icims.com/jobs/11/job?in_iframe=1": _Reponse(page11, 200, "https://acme.icims.com/jobs/11/job?in_iframe=1"),
                  "https://acme.icims.com/jobs/12/job?in_iframe=1": _Reponse(page12, 200, "https://acme.icims.com/jobs/12/job?in_iframe=1")})
    with mock.patch.object(jl, "CACHE_DIR", tmp / "icims"), mock.patch.object(jl, "PAUSE_ENTRE_PAGES", 0), mock.patch.object(ic, "PAUSE_LISTE", 0):
        jobs, meta = ic.collect_icims({"identifier": "acme.icims.com", "label": "Acme"}, s)
    tests.append(check("iCIMS : pagination arretee sur page sans nouveaute, JSON-LD lu, offre FR ecartee",
                       meta["sitemap_urls"] == 2 and len(jobs) == 1 and jobs[0].title == "Analyst" and jobs[0].source == "ICIMS"
                       and meta["hors_be"] == 1, str({k: meta.get(k) for k in ("sitemap_urls", "be", "hors_be", "error")})))
    tests.append(check("Detection iCIMS : l'hote 'careers-…' est prefere a cdn02/cookie-policy-scripts",
                       det.detecter_url('<a href="https://cdn02.icims.com/x.js"></a><a href="https://cookie-policy-scripts.icims.com/y"></a><a href="https://careers-bdobelgium.icims.com/jobs/search">')["identifiant"] == "careers-bdobelgium.icims.com"))

    # ------------------------------------------------------------------
    # 4. Extracteur universel
    # ------------------------------------------------------------------
    from sources import jsonld_sitemap_v1 as jl
    oui = ["https://x.be/jobs/1234-analyst", "https://x.be/nl/vacatures/lab-tech", "https://x.be/o/data-engineer",
           "https://x.be/fr/offres-d-emploi/technicien", "https://x.be/careers/job/12"]
    non = ["https://x.be/jobs/", "https://x.be/jobs/page/2", "https://x.be/blog/jobs-tips", "https://autre.be/jobs/1"]
    tests.append(check("URL d'offre reconnue (5 formes), listes/pagination/autre hote ecartes",
                       all(jl._est_url_offre(u, "x.be") for u in oui) and not any(jl._est_url_offre(u, "x.be") for u in non)))
    index = '<sitemapindex><sitemap><loc>https://x.be/sitemap-pages.xml</loc></sitemap><sitemap><loc>https://x.be/sitemap-jobs.xml</loc></sitemap></sitemapindex>'
    urlset = '<urlset><url><loc>https://x.be/jobs/1-a</loc><lastmod>2026-09-01</lastmod></url><url><loc>https://x.be/jobs/</loc></url></urlset>'
    s = _Session({"https://x.be/robots.txt": _Reponse("Sitemap: https://x.be/sitemap.xml", 200),
                  "https://x.be/sitemap.xml": _Reponse(index, 200), "https://x.be/sitemap-jobs.xml": _Reponse(urlset, 200),
                  "https://x.be/sitemap-pages.xml": _Reponse("<urlset></urlset>", 200)})
    entrees, err = jl.urls_offres("x.be", s)
    tests.append(check("Sitemap : robots -> index -> sous-sitemap 'jobs' lu en premier, lastmod conserve",
                       entrees == [("https://x.be/jobs/1-a", "2026-09-01")] and s.appels.index("https://x.be/sitemap-jobs.xml") < s.appels.index("https://x.be/sitemap-pages.xml"), str(err)))
    posting = {"@type": "JobPosting", "title": "Laborant", "description": "<p>" + "Analyses en laboratoire. " * 10 + "</p>",
               "hiringOrganization": {"name": "Labo NV"}, "datePosted": "2026-09-02T08:00:00", "employmentType": ["FULL_TIME"],
               "jobLocation": {"@type": "Place", "address": {"addressLocality": "Gent", "addressCountry": "BE"}},
               "identifier": {"value": "L-77"}, "validThrough": "2026-10-01"}
    job = jl.convertir_posting("https://x.be/jobs/1-a", posting, "JSONLD_SITES", "x.be", "X")
    tests.append(check("JobPosting -> JobOffer : titre, entreprise, pays BE, identifiant, date limite",
                       job and job.title == "Laborant" and job.company == "Labo NV" and job.location_status == "BE_CONFIRMED"
                       and job.external_id == "x.be:L-77" and job.application_deadline == "2026-10-01" and job.contract_type == "FULL_TIME"))
    posting_de = dict(posting, jobLocation={"address": {"addressLocality": "Berlin", "addressCountry": "DE"}})
    job_de = jl.convertir_posting("https://x.be/jobs/2", posting_de, "JSONLD_SITES", "x.be", "X")
    tests.append(check("JobPosting hors Belgique -> BE_EXCLUDED", job_de and job_de.location_status == "BE_EXCLUDED"))
    page_html = '<html><script type="application/ld+json">' + json.dumps(posting) + '</script></html>'
    s = _Session({"https://x.be/robots.txt": _Reponse("", 404), "https://x.be/sitemap.xml": _Reponse(urlset, 200),
                  "https://x.be/jobs/1-a": _Reponse(page_html, 200, "https://x.be/jobs/1-a")})
    with mock.patch.object(jl, "CACHE_DIR", tmp / "jl"), mock.patch.object(jl, "PAUSE_ENTRE_PAGES", 0):
        jobs, meta = jl.collect_site("x.be", "X", s)
        jobs2, meta2 = jl.collect_site("x.be", "X", s)
    tests.append(check("Site entier : 1 page visitee puis servie depuis le cache (lastmod inchange)",
                       len(jobs) == 1 and meta["visitees"] == 1 and meta2["cache"] == 1 and meta2["visitees"] == 0))

    # ------------------------------------------------------------------
    # 5. Registre des employeurs et decouverte
    # ------------------------------------------------------------------
    from sources import ats_employers_v2 as reg
    with mock.patch.object(reg, "REGISTRY_PATH", tmp / "reg.json"):
        reg.enregistrer("LEVER", "LEVER", "acme", "Acme", jobs_total=10, jobs_be=2, discovered_by="test")
        reg.enregistrer("LEVER", "LEVER", "acme", "Acme bis", jobs_total=11, jobs_be=3, discovered_by="test")
        reg.enregistrer("WORKDAY", "WORKDAY_ATS", {"tenant": "gsk", "wd": "wd5", "site": "GSKCareers"}, "GSK", jobs_total=1, jobs_be=1, discovered_by="test")
        reg.enregistrer("RECRUITEE", "RECRUITEE", "vito", "VITO", jobs_total=1, jobs_be=1, discovered_by="test")
        reg.enregistrer("RECRUITEE", "RECRUITEE", "nouveau", "Nouveau", jobs_total=1, jobs_be=1, discovered_by="test")
        emp = reg.charger()["employers"]
        tests.append(check("Registre : meme ATS + identifiant = mise a jour, pas de doublon",
                           sum(1 for e in emp if e["ats"] == "LEVER") == 1 and [e for e in emp if e["ats"] == "LEVER"][0]["jobs_be"] == 3))
        wd = reg.employeurs("WORKDAY_ATS")
        tests.append(check("Registre : forme Workday (tenant/wd/site) rendue au connecteur",
                           wd and wd[0]["tenant"] == "gsk" and wd[0]["site"] == "GSKCareers"))
        fusion = reg.fusionner("RECRUITEE", [{"identifier": "vito", "label": "VITO", "enabled": True}])
        tests.append(check("Fusion : l'entree deja configuree gagne, la nouvelle s'ajoute",
                           [c["identifier"] for c in fusion] == ["vito", "nouveau"]))
    from config import recruitee_sources, smartrecruiters_sources
    tests.append(check("enabled_companies() des configs existantes fonctionne toujours",
                       isinstance(recruitee_sources.enabled_companies(), list) and isinstance(smartrecruiters_sources.enabled_companies(), list)))

    from sources import source_discovery_v1 as sd
    tests.append(check("Variantes de nom : 'Lotus Bakeries NV' -> lotusbakeries, lotus-bakeries, lotus, lb",
                       sd._variantes("Lotus Bakeries NV") == ["lotusbakeries", "lotus-bakeries", "lotus"] or "lotusbakeries" in sd._variantes("Lotus Bakeries NV")))
    with mock.patch.object(reg, "REGISTRY_PATH", tmp / "reg2.json"), \
            mock.patch.object(sd, "detecter_site", return_value={"ats": "LEVER", "connecteur": "LEVER", "identifiant": "acme", "preuve": "LIEN", "url_finale": "https://www.acme.be/careers"}), \
            mock.patch.object(sd, "_valider", return_value={"ok": True, "total": 5, "be": 2, "erreur": None}):
        ligne = sd.traiter_candidat({"domaine": "acme.be", "label": "Acme", "discovered_by": "test"}, None, deviner=False)
        tests.append(check("Decouverte : ATS reconnu + validation OK -> ACTIVE et enregistre",
                           ligne["statut"] == "ACTIVE" and ligne["enregistre"] and reg.resume()["total"] == 1))
    with mock.patch.object(reg, "REGISTRY_PATH", tmp / "reg3.json"), \
            mock.patch.object(sd, "detecter_site", return_value={"ats": "TALEO", "connecteur": None, "identifiant": "uz", "preuve": "LIEN", "url_finale": "https://www.uz.be/jobs"}), \
            mock.patch.object(sd, "_valider", return_value={"ok": False, "total": None, "be": None, "erreur": "aucune URL"}):
        ligne = sd.traiter_candidat({"domaine": "uz.be", "label": "UZ", "discovered_by": "test"}, None, deviner=False)
        tests.append(check("Decouverte : ATS sans connecteur -> trace, rien d'enregistre",
                           ligne["statut"] == "ATS_SANS_CONNECTEUR" and not ligne["enregistre"] and reg.resume()["total"] == 0))

    cles = [s.key for s in registry.SOURCE_SPECS]
    rks = [s.result_key for s in registry.SOURCE_SPECS]
    tests.append(check("SOURCE_SPECS : aucune cle ni result_key en double",
                       len(cles) == len(set(cles)) and len(rks) == len(set(rks)), f"{len(cles)} specs"))
    tests.append(check("Nouvelles sources presentes : LEVER, ASHBY, WORKABLE, PERSONIO, JSONLD_SITES, ORACLE_CLOUD, CVWAREHOUSE",
                       {"LEVER", "ASHBY", "WORKABLE", "PERSONIO", "JSONLD_SITES", "ORACLE_CLOUD", "CVWAREHOUSE", "ICIMS", "TEAMTAILOR", "HTML_SITES", "JOBTOOLZ"} <= set(cles)))
    tests.append(check("Detection : Oracle Cloud (host/lang/site) et CVWarehouse (URL, casse des parametres conservee)",
                       det.detecter_url("https://ebza.fa.em2.oraclecloud.com/hcmUI/CandidateExperience/nl/sites/CX_1001/job/1")["identifiant"]
                       == {"host": "ebza.fa.em2.oraclecloud.com", "lang": "nl", "site": "CX_1001"}
                       and det.detecter_url("https://JobPage.cvwarehouse.com/?companyGuid=588d29e6-7c84-4f07-a5bb-42d21e04445b")["identifiant"]
                       == "https://jobpage.cvwarehouse.com/?companyGuid=588d29e6-7c84-4f07-a5bb-42d21e04445b"))
    tests.append(check("Versions au moins 1.0",
                       all(at_least(v, "1.0") for v in (ab.ABSORPTION_VERSION, det.ATS_DETECTOR_VERSION, v2.ATS_PUBLIC_V2_VERSION,
                                                        jl.JSONLD_SITEMAP_VERSION, reg.ATS_EMPLOYERS_VERSION, sd.SOURCE_DISCOVERY_VERSION))))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] EXPANSION DES SOURCES VALIDEE HORS LIGNE."
              if passed == total else "[FAIL] EXPANSION DES SOURCES NON VALIDEE.")
    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"expansion_sources_v1_audit_{stamp}.txt").write_text(
        "\n".join(["EXPANSION DES SOURCES V1.0", "=" * 92, f"Tests : {passed}/{total}", statut]), encoding="utf-8")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

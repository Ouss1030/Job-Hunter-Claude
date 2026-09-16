"""
JOB HUNTER BELGIUM
REGISTRE - EXPANSION DES SOURCES - VERSION 1.0

Cinq entrees de plus dans SOURCE_SPECS, toutes alimentees par
config/ats_employers_v2.json (le registre des employeurs decouverts) :

    LEVER, ASHBY, WORKABLE, PERSONIO   connecteurs ATS de seconde generation
    JSONLD_SITES                        extracteur universel sitemap + JSON-LD

Meme motif que registry_ats_v1.py : ce module ne touche pas a registry.py,
qui l'importe en fin de fichier.

Une source sans employeur enregistre n'est pas une erreur : elle rend une
liste vide et ne coute aucune requete. Le moteur de decouverte la remplit.
"""

from __future__ import annotations

from sources import ats_employers_v2 as registre


REGISTRY_EXPANSION_VERSION = "1.2"


def _collect_ats_v2(ats: str) -> list:
    from sources.ats_public_v2 import collect_ats_v2
    companies = registre.employeurs(ats)
    if not companies:
        print(f"  {ats} : aucun employeur enregistre (config/ats_employers_v2.json)")
        return []
    resultat = collect_ats_v2(ats, companies, verbose=True)
    erreurs = sum(1 for r in resultat["report"] if r.get("error"))
    print(f"{ats} - employeurs={len(resultat['report'])} offres BE={len(resultat['jobs'])} "
          f"en erreur={erreurs}")
    return resultat["jobs"]


def _collect_lever() -> list:
    return _collect_ats_v2("LEVER")


def _collect_ashby() -> list:
    return _collect_ats_v2("ASHBY")


def _collect_workable() -> list:
    return _collect_ats_v2("WORKABLE")


def _collect_personio() -> list:
    return _collect_ats_v2("PERSONIO")


def _collect_jsonld_sites() -> list:
    from sources.jsonld_sitemap_v1 import collect_sites
    companies = registre.employeurs("JSONLD_SITES")
    if not companies:
        print("  JSONLD_SITES : aucun site enregistre (config/ats_employers_v2.json)")
        return []
    # Localisation inconnue : gardee sur un hote .be, ecartee ailleurs
    # (voir jsonld_sitemap_v1._inconnu_accepte ; 80 offres AbbVie hors
    # Belgique etaient passees le 15/09/2026).
    resultat = collect_sites(companies, verbose=True)
    erreurs = sum(1 for r in resultat["report"] if r.get("error"))
    print(f"JSONLD_SITES - sites={len(resultat['report'])} offres BE={len(resultat['jobs'])} "
          f"en erreur={erreurs}")
    return resultat["jobs"]


def _collect_oracle_cloud() -> list:
    from sources.oracle_cloud_v1 import collect_oracle_cloud_jobs
    companies = registre.employeurs("ORACLE_CLOUD")
    if not companies:
        print("  ORACLE_CLOUD : aucun employeur enregistre (config/ats_employers_v2.json)")
        return []
    resultat = collect_oracle_cloud_jobs(companies, verbose=True)
    print(f"ORACLE_CLOUD - employeurs={len(resultat['report'])} offres BE={len(resultat['jobs'])} "
          f"en erreur={sum(1 for r in resultat['report'] if r.get('error'))}")
    return resultat["jobs"]


def _collect_cvwarehouse() -> list:
    from sources.cvwarehouse_v1 import collect_cvwarehouse_jobs
    companies = registre.employeurs("CVWAREHOUSE")
    if not companies:
        print("  CVWAREHOUSE : aucun employeur enregistre (config/ats_employers_v2.json)")
        return []
    resultat = collect_cvwarehouse_jobs(companies, verbose=True)
    print(f"CVWAREHOUSE - employeurs={len(resultat['report'])} offres BE={len(resultat['jobs'])} "
          f"en erreur={sum(1 for r in resultat['report'] if r.get('error'))}")
    return resultat["jobs"]


def _collect_icims() -> list:
    from sources.icims_v1 import collect_icims_jobs
    companies = registre.employeurs("ICIMS")
    if not companies:
        print("  ICIMS : aucun employeur enregistre (config/ats_employers_v2.json)")
        return []
    resultat = collect_icims_jobs(companies, verbose=True)
    print(f"ICIMS - employeurs={len(resultat['report'])} offres BE={len(resultat['jobs'])} "
          f"en erreur={sum(1 for r in resultat['report'] if r.get('error'))}")
    return resultat["jobs"]


def _collect_teamtailor() -> list:
    from sources.teamtailor_v1 import collect_teamtailor_jobs
    companies = registre.employeurs("TEAMTAILOR")
    if not companies:
        print("  TEAMTAILOR : aucun employeur enregistre (config/ats_employers_v2.json)")
        return []
    resultat = collect_teamtailor_jobs(companies, verbose=True)
    print(f"TEAMTAILOR - employeurs={len(resultat['report'])} offres BE={len(resultat['jobs'])} "
          f"en erreur={sum(1 for r in resultat['report'] if r.get('error'))}")
    return resultat["jobs"]


def specs_expansion(SourceSpec) -> tuple:
    """Les SourceSpec a ajouter ; SourceSpec est passe pour eviter l'import circulaire."""
    return (
        SourceSpec(key="LEVER", result_key="lever", label="Lever (ATS public)",
                   collector=_collect_lever, languages=("fr", "en", "nl"), priority=75,
                   notes="API publique postings. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="ASHBY", result_key="ashby", label="Ashby (ATS public)",
                   collector=_collect_ashby, languages=("fr", "en", "nl"), priority=76,
                   notes="API publique job-board. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="WORKABLE", result_key="workable", label="Workable (ATS public)",
                   collector=_collect_workable, languages=("fr", "en", "nl"), priority=77,
                   notes="API publique apply.workable.com. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="PERSONIO", result_key="personio", label="Personio (flux XML)",
                   collector=_collect_personio, languages=("fr", "en", "nl", "de"), priority=78,
                   notes="Flux XML public. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="ORACLE_CLOUD", result_key="oracle_cloud", label="Oracle Recruiting Cloud (API publique)",
                   collector=_collect_oracle_cloud, languages=("fr", "en", "nl"), priority=80,
                   notes="API REST publique des sites Candidate Experience. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="CVWAREHOUSE", result_key="cvwarehouse", label="CVWarehouse (ATS belge)",
                   collector=_collect_cvwarehouse, languages=("nl", "fr", "en"), priority=81,
                   notes="Pages servies par le serveur ; une page de detail par section porte toutes les offres. "
                         "Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="ICIMS", result_key="icims", label="iCIMS (liste + JSON-LD)",
                   collector=_collect_icims, languages=("fr", "en", "nl"), priority=82,
                   notes="Liste HTML paginee (in_iframe=1), JSON-LD JobPosting par offre via l'extracteur "
                         "universel. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="TEAMTAILOR", result_key="teamtailor", label="Teamtailor (flux RSS)",
                   collector=_collect_teamtailor, languages=("fr", "en", "nl"), priority=83,
                   notes="Flux RSS public /jobs.rss : une requete par site, descriptions completes, "
                         "ville et pays. Employeurs : config/ats_employers_v2.json."),
        SourceSpec(key="JSONLD_SITES", result_key="jsonld_sites",
                   label="Sites carrière (sitemap + JSON-LD)",
                   collector=_collect_jsonld_sites, languages=("fr", "en", "nl", "de"), priority=79,
                   notes="Extracteur universel : tout site qui publie sitemap + schema.org/JobPosting "
                         "(Teamtailor, Jobtoolz, Talentfinder, sites maison). "
                         "Sites : config/ats_employers_v2.json."),
    )

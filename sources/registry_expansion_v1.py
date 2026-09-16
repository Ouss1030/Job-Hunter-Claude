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


REGISTRY_EXPANSION_VERSION = "1.0"


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
        SourceSpec(key="JSONLD_SITES", result_key="jsonld_sites",
                   label="Sites carrière (sitemap + JSON-LD)",
                   collector=_collect_jsonld_sites, languages=("fr", "en", "nl", "de"), priority=79,
                   notes="Extracteur universel : tout site qui publie sitemap + schema.org/JobPosting "
                         "(Teamtailor, Jobtoolz, Talentfinder, sites maison). "
                         "Sites : config/ats_employers_v2.json."),
    )

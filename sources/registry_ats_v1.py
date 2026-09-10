"""
JOB HUNTER BELGIUM
CONNECTEURS ATS PUBLICS - EXTENSION DU REGISTRE V1

Les cinq connecteurs ATS construits dans ce dossier (Recruitee, Greenhouse,
Workday, SuccessFactors, Phenom) vivent ici plutot que dans registry.py.

Pourquoi les isoler
-------------------
registry.py est repris tel quel du projet principal pour rester
resynchronisable. Y melanger des ajouts locaux obligerait a refaire la
fusion a chaque mise a jour. En extension, la resynchronisation redevient
une simple copie.
"""

from __future__ import annotations

from sources.recruitee import collect_recruitee_jobs
from sources.greenhouse import collect_greenhouse_jobs
from sources.workday_ats_v1 import collect_workday_jobs
from sources.successfactors_ats_v1 import collect_successfactors_jobs
from sources.phenom_ats_v1 import collect_phenom_jobs


def _collect_recruitee() -> list:
    """ATS public Recruitee. Le filtrage Belgique est fait par le connecteur."""
    resultat = collect_recruitee_jobs(verbose=False)
    total, hors_be, echecs = 0, 0, 0
    for ligne in resultat["report"]:
        total += ligne["offers_total"]
        hors_be += ligne["outside_belgium"]
        echecs += ligne["failures"]
        if ligne["error"]:
            print(f"  {ligne['label']:<20} ⚠️  {ligne['error']}")
        else:
            print(f"  {ligne['label']:<20} total={ligne['offers_total']:<4} "
                  f"BE={ligne['converted']:<4} hors BE={ligne['outside_belgium']:<4} "
                  f"échecs={ligne['failures']}")
    print("RECRUITEE - offres hors Belgique écartées :", hors_be)
    print("RECRUITEE - échecs de conversion          :", echecs)
    return resultat["jobs"]


def _collect_greenhouse() -> list:
    """
    ATS public Greenhouse.

    include_unknown_location reste à False : un board Greenhouse est
    majoritairement international, et conserver tous les "Remote" mondiaux
    noierait les rares offres belges.
    """
    resultat = collect_greenhouse_jobs(verbose=False)
    hors_be, inconnues, echecs, nl = 0, 0, 0, 0
    for ligne in resultat["report"]:
        hors_be += ligne["outside_belgium"]
        inconnues += ligne["unknown_location"]
        echecs += ligne["failures"]
        nl += ligne["dutch_postings"]
        if ligne["error"]:
            print(f"  {ligne['label']:<20} ⚠️  {ligne['error']}")
        else:
            print(f"  {ligne['label']:<20} total={ligne['offers_total']:<4} "
                  f"BE={ligne['retained']:<4} hors BE={ligne['outside_belgium']:<4} "
                  f"inconnues={ligne['unknown_location']:<4} échecs={ligne['failures']}")
    print("GREENHOUSE - offres hors Belgique écartées :", hors_be)
    print("GREENHOUSE - localisations non exploitables:", inconnues)
    print("GREENHOUSE - annonces en néerlandais       :", nl)
    print("GREENHOUSE - échecs de conversion          :", echecs)
    return resultat["jobs"]


def _collect_workday() -> list:
    """
    Sites carrière d'employeurs directs (GSK, Sanofi, Baxter, Pfizer).

    Seule voie vers les grands employeurs pharma belges : ils ne publient
    ni sur Forem/Actiris, ni sur les ATS à API documentée.
    """
    resultat = collect_workday_jobs(verbose=False)
    hors_be, echecs = 0, 0
    for ligne in resultat["report"]:
        hors_be += ligne["outside_belgium"]
        echecs += ligne["failures"]
        if ligne["error"]:
            print(f"  {ligne['label']:<16} ⚠️  {ligne['error']}")
        else:
            print(f"  {ligne['label']:<16} listées={ligne['listed']:<4} "
                  f"BE={ligne['retained']:<4} hors BE={ligne['outside_belgium']:<3} "
                  f"échecs={ligne['failures']}")
    print("WORKDAY - offres hors Belgique écartées :", hors_be)
    print("WORKDAY - échecs de détail              :", echecs)
    return resultat["jobs"]


def _collect_successfactors() -> list:
    """
    Sites carrière SuccessFactors, lus via leur sitemap public.

    Seul connecteur du projet qui analyse du HTML : il surveille donc son
    propre taux d'échec, qui signale un changement de gabarit.
    """
    resultat = collect_successfactors_jobs(verbose=False)
    alertes = 0
    for ligne in resultat["report"]:
        if ligne["error"]:
            print(f"  {ligne['label']:<12} ⚠️  {ligne['error']}")
            continue
        print(f"  {ligne['label']:<12} sitemap={ligne['sitemap_urls']:<4} "
              f"candidates={ligne['candidates']:<4} BE={ligne['retained']:<4} "
              f"échecs={ligne['failures']} ({ligne['failure_rate']:.0%})")
        if ligne["layout_warning"]:
            alertes += 1
            print(f"               ⚠️  gabarit probablement modifié chez "
                  f"{ligne['label']}")
    print("SUCCESSFACTORS - alertes de gabarit :", alertes)
    return resultat["jobs"]


def _collect_phenom() -> list:
    """
    Sites carrière Phenom, lus via leur JSON-LD schema.org.

    Données structurées : pays, date et description arrivent en champs,
    sans analyse de mise en page. Le connecteur le plus robuste du projet.
    """
    resultat = collect_phenom_jobs(verbose=False)
    for ligne in resultat["report"]:
        if ligne["error"]:
            print(f"  {ligne['label']:<18} ⚠️  {ligne['error']}")
            continue
        print(f"  {ligne['label']:<18} sitemap={ligne['sitemap_urls']:<4} "
              f"visitées={ligne['visited']:<4} BE={ligne['retained']:<4} "
              f"hors BE={ligne['outside_belgium']:<4} "
              f"échecs={ligne['failures']} ({ligne['failure_rate']:.0%})")
        if ligne["jsonld_warning"]:
            print(f"                     ⚠️  JSON-LD manquant sur plus d'une "
                  f"page sur deux chez {ligne['label']}")
    return resultat["jobs"]


from sources.vdab import collect_vdab_jobs  # noqa: E402


def _collect_vdab() -> list:
    """
    Service public flamand, lu via son sitemap public.

    L'API officielle exige des identifiants ; le sitemap est declare dans
    robots.txt et /vindeenjob/jobs/ n'est pas interdit. Rien n'est contourne.
    """
    resultat = collect_vdab_jobs(verbose=False)
    c = resultat["compteurs"]
    print(f"  VDAB  vues={c['seen']:<5} converties={c['converted']:<5} "
          f"BE={c['geography_accepted']:<5} inconnues={c['geography_unknown']:<4} "
          f"hors BE={c['geography_rejected']:<4} echecs={c['detail_failed']}")
    for erreur in resultat["erreurs"][:3]:
        print(f"  VDAB  ⚠️  {erreur}")
    return resultat["jobs"]

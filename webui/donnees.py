"""
JOB HUNTER BELGIUM
INTERFACE WEB - PREPARATION DES DONNEES - VERSION 1.0

Le serveur route et rend ; ce module calcule. Les separer evite que
serveur.py devienne le fourre-tout ou la moitie de la logique finit par
s'installer sans qu'on l'ait decide.

Rien ici n'invente : tout vient de interface/, matching/ et statistiques/,
qui ne dependent d'aucun framework d'affichage.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from interface.data_access import (
    decorate_scored_jobs,
    load_latest_delta,
    load_latest_final_pool,
)
from interface.lifecycle_service import relances_dues, suivis_par_cle
from matching.verdict import VERDICT_VERSION, evaluer
from statistiques.marche import _ville
from webui.memo import MEMOIRE


DONNEES_VERSION = "1.2"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"


LOG_DIR = PROJECT_ROOT / "exports" / "logs"


def _empreinte_pool() -> tuple:
    """
    Ce dont dependent les verdicts : l'artefact de pool, et le moteur.

    Calculee SANS lire les fichiers. load_latest_final_pool() parse chaque
    artefact de pool present — six fichiers d'un quart de mega — juste pour
    trouver le plus recent : 36 ms par appel, et l'empreinte etait appelee
    plusieurs fois par page. Le nom du fichier porte deja l'horodatage ; il
    suffit de trier dessus et de lire la date de modification.

    La version du moteur en fait partie : corriger le verdict sans relancer
    le serveur doit rendre des resultats a jour, pas les anciens.
    """
    chemins = sorted(LOG_DIR.glob("final_application_pool_v*.json"),
                     key=lambda c: c.name)
    if not chemins:
        return ("aucun", VERDICT_VERSION)
    dernier = chemins[-1]
    try:
        return (dernier.name, dernier.stat().st_mtime_ns, VERDICT_VERSION)
    except OSError:
        return ("aucun", VERDICT_VERSION)


def _pool() -> tuple[list[dict], Path | None]:
    """Le pool parse une seule fois par artefact."""
    def _charger():
        pool, _meta, chemin = load_latest_final_pool()
        return (pool, chemin)
    return MEMOIRE.obtenir("pool_brut", _empreinte_pool(), _charger)


# Compteur de generations du suivi.
#
# La base est en mode WAL : une ecriture va dans jobs.db-wal, et la date de
# jobs.db peut rester inchangee jusqu'au prochain checkpoint. Se fier a
# cette date ferait afficher un ancien statut apres un triage. Chaque
# ecriture incremente donc ce compteur, et c'est lui qui invalide.
_GENERATION_SUIVI = [0]


def invalider_suivi() -> None:
    """A appeler apres toute ecriture de statut ou de suivi."""
    _GENERATION_SUIVI[0] += 1


def _empreinte_base() -> tuple:
    """Ce dont depend le suivi : chaque ecriture, comptee explicitement."""
    try:
        wal = DB_PATH.with_name(DB_PATH.name + "-wal")
        mtime = (wal.stat().st_mtime_ns if wal.exists()
                 else DB_PATH.stat().st_mtime_ns)
    except OSError:
        mtime = 0
    return (_GENERATION_SUIVI[0], mtime)


def _empreinte_collecte() -> tuple:
    """
    Ce dont depend le marche : le dernier run de collecte.

    Pas la date de la base : un triage la modifie sans changer une seule
    offre, et relancer treize secondes de calcul pour un clic serait absurde.
    """
    import sqlite3
    try:
        c = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
        try:
            run = c.execute("SELECT MAX(run_id) FROM collection_runs").fetchone()[0]
        finally:
            c.close()
        return (run, VERDICT_VERSION)
    except Exception:
        return _empreinte_base()

# Champs transmis a la page. En envoyer davantage alourdirait le chargement
# sans rien apporter : la description complete fait plusieurs milliers de
# caracteres et n'est utile qu'au panneau de detail.
CHAMPS = (
    "stable_item_key", "pool_rank_v12", "title", "company", "location",
    "source", "url", "verdict", "verdict_obstacle", "verdict_formation",
    "recommended_action_v12", "priority_v12", "final_score_v12", "track",
    "cv_track", "guard_level", "application_status", "applied",
    "preferred_location", "reasons", "description",
)


def _analyse_ecart(titre: str, texte: str) -> dict:
    """
    Ce que l'offre demande et que vous avez — ou non.

    L'original rend « exigences / correspondances / ecarts » par offre. La
    difference tient a la preuve : notre moteur cite la phrase de l'annonce
    qui fonde chaque barriere, la leur affirme sans montrer. Un obstacle
    qu'on peut relire est un obstacle qu'on peut contester.
    """
    resultat = evaluer(f"{titre or ''}\n{texte or ''}")
    return {
        "verdict": resultat.verdict,
        "formation": bool(resultat.formation),
        "barrieres": [
            {"critere": c.critere, "message": c.message, "preuve": c.preuve}
            for c in resultat.barrieres
        ],
        "alertes": [
            {"critere": c.critere, "message": c.message, "preuve": c.preuve}
            for c in resultat.alertes
        ],
        "atouts": list(resultat.atouts),
        "manques": [str(x) for x in resultat.manques],
    }


def _offres_sans_suivi() -> tuple[list[dict], str]:
    """
    La partie couteuse et stable : verdicts et extraits.

    Memorisee sur l'empreinte du pool. Un triage ne la touche pas — il ne
    change ni le texte des offres ni leur verdict.
    """
    pool, chemin = _pool()
    decorees = decorate_scored_jobs(pool, final=True)

    lignes = []
    for offre in decorees:
        ligne = {champ: offre.get(champ) for champ in CHAMPS}
        texte = str(offre.get("description") or "")
        # Les sources ecrivent l'adresse complete : « Avenue Jules Bordet 168
        # 1140 Bruxelles Telework No telework ». Illisible dans un tableau.
        ligne["ville"] = _ville(offre.get("location") or "")
        ligne["extrait"] = texte[:1200]
        ligne.pop("description", None)
        try:
            ligne["ecart"] = _analyse_ecart(offre.get("title"), texte)
        except Exception:
            ligne["ecart"] = {}
        lignes.append(ligne)

    return lignes, (chemin.name if chemin else "aucun artefact")


def offres() -> tuple[list[dict], str]:
    """
    Pool courant, allege, avec suivi et analyse d'ecart.

    Deux memoires a deux rythmes : les verdicts suivent le pool (un run),
    le suivi suit la base (un triage). Le statut de candidature vient aussi
    de la base — decorate_scored_jobs le lit — et doit donc etre rafraichi
    au rythme du suivi, pas du pool.
    """
    lignes_stables, artefact = MEMOIRE.obtenir(
        "offres", _empreinte_pool(), _offres_sans_suivi)

    def _avec_suivi():
        suivis = suivis_par_cle()
        # decorate_scored_jobs relit statut et marquage « postule » en base :
        # on ne memorise que ces deux champs-la, pas tout le decorage.
        pool, _chemin = _pool()
        statuts = {
            o.get("stable_item_key"): (o.get("application_status"),
                                       o.get("applied"))
            for o in decorate_scored_jobs(pool, final=True)
        }
        resultat = []
        for ligne in lignes_stables:
            copie = dict(ligne)
            cle = copie.get("stable_item_key")
            copie["suivi"] = suivis.get(cle, {})
            statut, postule = statuts.get(cle, (None, None))
            copie["application_status"] = statut
            copie["applied"] = postule
            resultat.append(copie)
        return resultat

    lignes = MEMOIRE.obtenir(
        "offres_avec_suivi", (_empreinte_pool(), _empreinte_base()),
        _avec_suivi)
    return lignes, artefact


def offre_par_cle(cle: str) -> dict | None:
    index = MEMOIRE.obtenir(
        "index_pool", _empreinte_pool(),
        lambda: {o.get("stable_item_key"): o for o in _pool()[0]})
    return index.get(cle)


# Statuts poses par le pipeline lui-meme, par opposition a ceux qui
# traduisent une decision du candidat.
#
# La distinction porte tout l'ecran du jour : une offre marquee READY n'a
# ete jugee par personne — c'est le pipeline qui a constate que son dossier
# etait pret. La confondre avec un choix humain reviendrait a dire que 103
# offres sur 117 sont deja traitees, alors qu'aucune ne l'est.
_STATUTS_PIPELINE = frozenset({
    "", "DISCOVERED", "READY", "DOCUMENTS_READY",
})


def journee(lignes: list[dict]) -> dict:
    """
    Ce qui demande une decision aujourd'hui.

    Trois questions, pas sept compteurs : quelles relances sont dues, quelles
    offres attendent un tri, qu'est-ce qui est nouveau. Un tableau de bord
    qui affiche tout n'oriente vers rien.
    """
    aujourdhui = date.today().isoformat()

    try:
        dues = MEMOIRE.obtenir(
            "relances", (_empreinte_base(), aujourdhui),
            lambda: relances_dues(aujourdhui))
    except Exception:
        dues = []

    non_triees = [
        o for o in lignes
        if (o.get("application_status") or "") in _STATUTS_PIPELINE
    ]
    a_postuler = [
        o for o in non_triees
        if str(o.get("recommended_action_v12") or "").startswith("APPLY")
        and o.get("verdict") != "FERMEE"
    ]

    try:
        delta, chemin_delta = load_latest_delta()
        resume = (delta or {}).get("summary") or {}
        nouveautes = {
            "artefact": chemin_delta.name if chemin_delta else None,
            "nouvelles": resume.get("new_total") or resume.get("new") or 0,
            "nouvelles_a_postuler": resume.get("new_apply_now") or 0,
            "disparues": resume.get("disappeared_total")
            or resume.get("disappeared") or 0,
        }
    except Exception:
        nouveautes = {}

    return {
        "relances_dues": dues,
        "non_triees": len(non_triees),
        "a_postuler_non_triees": len(a_postuler),
        "prioritaires": [
            {
                "cle": o.get("stable_item_key"),
                "titre": o.get("title"),
                "entreprise": o.get("company"),
                "ville": o.get("ville"),
                "score": o.get("final_score_v12"),
                "verdict": o.get("verdict"),
            }
            for o in sorted(
                a_postuler,
                key=lambda x: -(float(x.get("final_score_v12") or 0)),
            )[:8]
        ],
        "nouveautes": nouveautes,
    }


def etat_du_run() -> dict:
    """Etat courant du pipeline, pour l'affichage en direct."""
    from interface import pipeline_runner as runner
    from interface import progress_monitor as moniteur

    try:
        en_cours = runner.is_running()
    except Exception:
        en_cours = False

    try:
        _chemin, manifest = moniteur.latest_daily_manifest()
    except Exception:
        manifest = {}

    try:
        etapes = moniteur.step_rows(manifest)
    except Exception:
        etapes = []

    try:
        activite = moniteur.active_step_activity(manifest) or {}
    except Exception:
        activite = {}

    try:
        secondes = moniteur.run_elapsed_seconds(manifest)
        duree = moniteur.format_duration(secondes)
    except Exception:
        duree = None

    return {
        "en_cours": en_cours,
        "run_id": manifest.get("run_id"),
        "statut": manifest.get("status"),
        "etape_courante": moniteur.current_step(manifest) if manifest else None,
        "terminees": moniteur.completed_steps(manifest) if manifest else 0,
        "total_etapes": len(etapes),
        "duree": duree,
        "etapes": etapes,
        "activite": activite,
    }


def journal_du_run(lignes_max: int = 60) -> list[str]:
    """Fin du journal en cours, pour voir ce qui se passe vraiment."""
    from interface import pipeline_runner as runner

    try:
        chemin = runner.latest_ui_log()
    except Exception:
        chemin = None
    if not chemin or not Path(chemin).exists():
        return []
    try:
        contenu = Path(chemin).read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    return contenu.splitlines()[-lignes_max:]


def marche(complet: bool = False) -> dict:
    """
    Analyse de marche, memorisee sur le dernier run de collecte.

    Treize secondes mesurees pour 1 500 offres, a chaque visite de la page.
    Le marche ne change qu'a une collecte ; l'analyse n'a donc a etre
    refaite qu'a ce moment-la.
    """
    from statistiques.marche import analyser_marche

    limite = None if complet else 1500
    empreinte = _empreinte_collecte()
    nom = f"marche_{'complet' if complet else 'apercu'}"
    run = str(empreinte[0] or "aucun").replace(":", "-")
    return MEMOIRE.obtenir(
        nom, empreinte,
        lambda: analyser_marche(limite=limite),
        # Treize secondes par collecte, jamais au demarrage.
        fichier=LOG_DIR / f"{nom}_{run}.json")


def prechauffer() -> None:
    """
    Calcule d'avance ce que la premiere visite demanderait.

    Lance en arriere-plan au demarrage du serveur : la premiere page ne
    doit pas payer treize secondes que les suivantes ne paieront plus.
    """
    import threading

    def _travail():
        try:
            offres()
            statistiques_pipeline()
            marche(complet=False)
            # En dernier : c'est le plus long, et il n'est calcule que si
            # aucun artefact n'existe pour cette collecte.
            conseils()
        except Exception:
            # Un echec de prechauffage n'est pas une erreur : la page
            # calculera elle-meme, simplement moins vite.
            pass

    threading.Thread(target=_travail, daemon=True,
                     name="prechauffage").start()


def _empreinte_artefacts() -> tuple:
    """Le dernier artefact de file : l'entonnoir ne change qu'a un run."""
    chemins = sorted(LOG_DIR.glob("application_queue_v1_*.json"),
                     key=lambda c: c.name)
    if not chemins:
        return ("aucun",)
    try:
        return (chemins[-1].name, chemins[-1].stat().st_mtime_ns, len(chemins))
    except OSError:
        return ("aucun",)


def statistiques_pipeline() -> dict:
    """Entonnoir, evolution et rendement, memorises sur le dernier run."""
    from statistiques.pipeline import (
        entonnoir_par_run, evolution, rendement_des_sources)

    def _calcul():
        entonnoir = entonnoir_par_run()
        return {
            "entonnoir": entonnoir,
            "evolution": evolution(entonnoir),
            "rendement": [x for x in rendement_des_sources()
                          if x["offres"] >= 2],
        }
    return MEMOIRE.obtenir("pipeline", _empreinte_artefacts(), _calcul)


def statistiques_candidatures() -> dict:
    from statistiques.candidatures import analyser_candidatures
    return MEMOIRE.obtenir("candidatures", _empreinte_base(),
                           analyser_candidatures)


def conseils() -> dict:
    """
    Conseils de marche : un artefact par collecte, ecrit sur disque.

    Le calcul passe les 11 905 offres au crible de tous les vocabulaires :
    une cinquantaine de secondes de Python pur. Le faire en arriere-plan au
    demarrage semblait une bonne idee ; en pratique le thread de calcul
    monopolise l'interpreteur et chaque page ramait pendant cinquante
    secondes — mesure : 13 s pour l'ecran du jour.

    Le resultat ne change qu'a une collecte. Il est donc ecrit dans
    exports/logs sous le nom du run, et relu instantanement tant que ce run
    est le dernier. Le calcul n'est paye qu'une fois par collecte, jamais
    au demarrage.
    """
    from statistiques.conseils import analyser

    empreinte = _empreinte_collecte()
    run = str(empreinte[0] or "aucun").replace(":", "-")
    return MEMOIRE.obtenir(
        "conseils", empreinte, analyser,
        fichier=LOG_DIR / f"conseils_marche_{run}.json")


def conseils_prets() -> bool:
    """Vrai si les conseils sont disponibles sans calcul long."""
    empreinte = _empreinte_collecte()
    run = str(empreinte[0] or "aucun").replace(":", "-")
    return (LOG_DIR / f"conseils_marche_{run}.json").exists()         or "conseils" in MEMOIRE.etat()

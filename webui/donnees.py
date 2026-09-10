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
from interface.lifecycle_service import get_suivi, relances_dues
from matching.verdict import evaluer
from statistiques.marche import _ville


DONNEES_VERSION = "1.0"

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


def offres() -> tuple[list[dict], str]:
    """Pool courant, allege, avec suivi et analyse d'ecart."""
    pool, _meta, chemin = load_latest_final_pool()
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
            ligne["suivi"] = get_suivi(offre)
        except Exception:
            # Le suivi est un confort : son echec ne doit jamais empecher
            # d'afficher la liste des offres.
            ligne["suivi"] = {}
        try:
            ligne["ecart"] = _analyse_ecart(offre.get("title"), texte)
        except Exception:
            ligne["ecart"] = {}
        lignes.append(ligne)

    return lignes, (chemin.name if chemin else "aucun artefact")


def offre_par_cle(cle: str) -> dict | None:
    pool, _meta, _chemin = load_latest_final_pool()
    for offre in pool:
        if offre.get("stable_item_key") == cle:
            return offre
    return None


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
        dues = relances_dues(aujourdhui)
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

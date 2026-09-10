"""
JOB HUNTER BELGIUM
INTERFACE WEB - VERSION 0.2

    python -m webui.serveur
    -> http://127.0.0.1:8600

Pourquoi une seconde interface
------------------------------
Streamlit impose son rendu. On lui decrit des composants, il decide de leur
apparence, de leur densite et de leur mise en page. C'est excellent pour
sortir un outil interne en une soiree, et c'est une impasse des qu'on veut
maitriser la forme.

Cette interface-ci est servie en HTML : chaque pixel est ecrit ici ou dans
la feuille de style. Rien n'est impose.

Aucune dependance nouvelle
--------------------------
Starlette, Jinja2 et uvicorn sont deja presents dans l'environnement — ils
arrivent avec Streamlit. Aucun `pip install`, aucun Node, aucune etape de
compilation.

V0.2 — le triage et le suivi
----------------------------
La V0.1 affichait. Celle-ci permet de decider.

Deux idees viennent du tableau de bord V7 de l'original, et elles sont
bonnes : le triage directement dans la liste, et la case a cocher obligatoire
avant de marquer une candidature envoyee. Cette seconde trouvaille merite
d'etre soulignee — elle transforme une regle ecrite dans un document
(« la machine ne marque jamais APPLIED ») en une contrainte que l'interface
rend impossible a contourner par distraction.

Ce qui change par rapport a eux : leur triage recharge toute la page a
chaque clic, ce qui rend le tri de cent offres interminable. Ici, l'action
part en arriere-plan et la ligne se met a jour seule ; le clavier permet
d'enchainer sans jamais viser un bouton.

Toute la logique metier vient de interface/, qui ne depend d'aucun framework
d'affichage : cette page ne fait que presenter et transmettre.
"""

from __future__ import annotations

import json
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from interface.data_access import decorate_scored_jobs, load_latest_final_pool
from interface.lifecycle_service import (
    USER_STATUSES,
    get_suivi,
    relances_dues,
    save_suivi,
    set_status,
)
from statistiques.marche import _ville


WEBUI_VERSION = "0.2"

RACINE = Path(__file__).resolve().parent
GABARITS = Jinja2Templates(directory=str(RACINE / "templates"))

# Champs reellement affiches. En envoyer davantage alourdirait la page sans
# rien apporter : la description complete fait plusieurs milliers de
# caracteres et n'est utile qu'au panneau de detail.
_CHAMPS = (
    "stable_item_key", "pool_rank_v12", "title", "company", "location",
    "source", "url", "verdict", "verdict_obstacle", "verdict_formation",
    "recommended_action_v12", "priority_v12", "final_score_v12", "track",
    "cv_track", "guard_level", "application_status", "applied",
    "preferred_location", "reasons", "description",
)

# Statuts proposes au triage rapide, dans l'ordre du parcours.
#
# Le cycle de vie en compte dix ; les exposer tous ferait de chaque decision
# un choix a dix branches. Le triage n'a besoin que du premier tri : ca
# m'interesse, j'y reviendrai, non merci.
TRIAGE = (
    {"statut": "SHORTLISTED", "libelle": "Intéressé", "touche": "i"},
    {"statut": "DISCOVERED", "libelle": "À revoir", "touche": "a"},
    {"statut": "WITHDRAWN", "libelle": "Écarter", "touche": "x"},
)


def _offres() -> tuple[list[dict], str]:
    """Pool courant, allege et pret a etre serialise."""
    pool, _meta, chemin = load_latest_final_pool()
    decorees = decorate_scored_jobs(pool, final=True)

    lignes = []
    for offre in decorees:
        ligne = {champ: offre.get(champ) for champ in _CHAMPS}
        # Les sources ecrivent l'adresse complete : « Avenue Jules Bordet 168
        # 1140 Bruxelles Telework No telework ». Illisible dans un tableau.
        ligne["ville"] = _ville(offre.get("location") or "")
        ligne["extrait"] = str(offre.get("description") or "")[:1200]
        ligne.pop("description", None)
        try:
            ligne["suivi"] = get_suivi(offre)
        except Exception:
            # Le suivi est un confort : son echec ne doit jamais empecher
            # d'afficher la liste des offres.
            ligne["suivi"] = {}
        lignes.append(ligne)

    return lignes, (chemin.name if chemin else "aucun artefact")


def _offre_par_cle(cle: str) -> dict | None:
    pool, _meta, _chemin = load_latest_final_pool()
    for offre in pool:
        if offre.get("stable_item_key") == cle:
            return offre
    return None


# ------------------------------------------------------------------ pages

async def page_offres(request):
    lignes, artefact = _offres()
    return GABARITS.TemplateResponse(
        request,
        "offres.html",
        {
            "version": WEBUI_VERSION,
            "artefact": artefact,
            "offres_json": json.dumps(lignes, ensure_ascii=False),
            "triage_json": json.dumps(TRIAGE, ensure_ascii=False),
            "total": len(lignes),
            "dues": len(relances_dues()),
        },
    )


async def page_a_venir(request):
    titre = request.path_params.get("nom", "").replace("-", " ").capitalize()
    return GABARITS.TemplateResponse(
        request, "a_venir.html",
        {"version": WEBUI_VERSION, "titre": titre or "Cet écran"})


# -------------------------------------------------------------------- api

async def api_offres(request):
    lignes, artefact = _offres()
    return JSONResponse({"artefact": artefact, "offres": lignes})


async def api_statut(request):
    """
    Change le statut d'une offre.

    APPLIED est refuse ici, deliberement : il ne peut etre pose que par la
    route dediee, qui exige une confirmation explicite. La regle du projet
    est que la machine ne declare jamais une candidature envoyee, et une
    regle qui depend de la vigilance de l'appelant n'est pas une regle.
    """
    corps = await request.json()
    cle = str(corps.get("cle") or "")
    statut = str(corps.get("statut") or "").upper()

    if statut == "APPLIED":
        return JSONResponse(
            {"erreur": "APPLIED exige une confirmation explicite."}, 400)
    if statut not in USER_STATUSES:
        return JSONResponse({"erreur": f"Statut inconnu : {statut}"}, 400)

    offre = _offre_par_cle(cle)
    if not offre:
        return JSONResponse({"erreur": "Offre introuvable."}, 404)

    try:
        applique = set_status(offre, statut, note=corps.get("note"))
        return JSONResponse({"cle": cle, "statut": applique})
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_postule(request):
    """Marque APPLIED — uniquement sur confirmation explicite du candidat."""
    corps = await request.json()
    if not corps.get("confirme"):
        return JSONResponse(
            {"erreur": "Confirmation manquante : APPLIED refusé."}, 400)

    offre = _offre_par_cle(str(corps.get("cle") or ""))
    if not offre:
        return JSONResponse({"erreur": "Offre introuvable."}, 404)

    try:
        set_status(offre, "APPLIED", note=corps.get("note"))
        return JSONResponse({"cle": offre["stable_item_key"],
                             "statut": "APPLIED"})
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_suivi(request):
    corps = await request.json()
    offre = _offre_par_cle(str(corps.get("cle") or ""))
    if not offre:
        return JSONResponse({"erreur": "Offre introuvable."}, 404)

    try:
        valeurs = save_suivi(
            offre,
            next_action_date=corps.get("next_action_date"),
            contact_name=corps.get("contact_name"),
            contact_channel=corps.get("contact_channel"),
            note=corps.get("note"),
        )
        return JSONResponse({"cle": offre["stable_item_key"], "suivi": valeurs})
    except ValueError as erreur:
        return JSONResponse({"erreur": str(erreur)}, 400)
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_relances(request):
    return JSONResponse({"dues": relances_dues()})


application = Starlette(
    routes=[
        Route("/", page_offres),
        Route("/bientot/{nom}", page_a_venir),
        Route("/api/offres", api_offres),
        Route("/api/statut", api_statut, methods=["POST"]),
        Route("/api/postule", api_postule, methods=["POST"]),
        Route("/api/suivi", api_suivi, methods=["POST"]),
        Route("/api/relances", api_relances),
        Mount("/static", StaticFiles(directory=str(RACINE / "static")),
              name="static"),
    ]
)


def main() -> None:
    print("=" * 70)
    print(f"JOBHUNTER — INTERFACE WEB V{WEBUI_VERSION}")
    print("=" * 70)
    print("  http://127.0.0.1:8600")
    print("  Ctrl+C pour arrêter.")
    print()
    uvicorn.run(application, host="127.0.0.1", port=8600, log_level="warning")


if __name__ == "__main__":
    main()

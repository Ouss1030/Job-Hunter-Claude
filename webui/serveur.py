"""
JOB HUNTER BELGIUM
INTERFACE WEB - VERSION 0.1 (MAQUETTE)

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
compilation : le projet se lance avec le meme interpreteur que le reste.

Ce que cette version est
------------------------
Une MAQUETTE : un seul ecran, celui des offres, mais fini. Le but est de
juger le style sur de vraies donnees avant d'aller plus loin. L'ancienne
interface Streamlit reste en place et fonctionnelle pendant ce temps.

Toute la logique metier vient de interface/, qui ne depend d'aucun
framework d'affichage : cette page ne fait que presenter ce que les services
existants rendent deja.
"""

from __future__ import annotations

import json
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from interface.data_access import decorate_scored_jobs, load_latest_final_pool
from statistiques.marche import _ville


WEBUI_VERSION = "0.1"

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
        ligne["extrait"] = (str(offre.get("description") or "")[:1200])
        ligne.pop("description", None)
        lignes.append(ligne)

    return lignes, (chemin.name if chemin else "aucun artefact")


async def page_offres(request):
    lignes, artefact = _offres()
    return GABARITS.TemplateResponse(
        request,
        "offres.html",
        {
            "version": WEBUI_VERSION,
            "artefact": artefact,
            "offres_json": json.dumps(lignes, ensure_ascii=False),
            "total": len(lignes),
        },
    )


async def api_offres(request):
    lignes, artefact = _offres()
    return JSONResponse({"artefact": artefact, "offres": lignes})


async def page_a_venir(request):
    titre = request.path_params.get("nom", "").replace("-", " ").capitalize()
    return GABARITS.TemplateResponse(
        request, "a_venir.html",
        {"version": WEBUI_VERSION, "titre": titre or "Cet écran"})


application = Starlette(
    routes=[
        Route("/", page_offres),
        Route("/api/offres", api_offres),
        Route("/bientot/{nom}", page_a_venir),
        Mount("/static", StaticFiles(directory=str(RACINE / "static")),
              name="static"),
    ]
)


def main() -> None:
    print("=" * 70)
    print(f"JOBHUNTER — INTERFACE WEB V{WEBUI_VERSION} (maquette)")
    print("=" * 70)
    print("  http://127.0.0.1:8600")
    print("  Ctrl+C pour arrêter.")
    print()
    uvicorn.run(application, host="127.0.0.1", port=8600, log_level="warning")


if __name__ == "__main__":
    main()

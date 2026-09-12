"""
JOB HUNTER BELGIUM
INTERFACE WEB - VERSION 0.3

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

V0.3 — l'ecran du jour, le run, les statistiques
-------------------------------------------------
L'ecran du jour remplace leur « Command Center ». Eux affichent sept
compteurs cote a cote ; un tableau de bord qui montre tout n'oriente vers
rien. Trois questions suffisent : quelles relances sont dues, quelles offres
attendent une decision, qu'est-ce qui est nouveau.

Le lancement de run reprend leur boite de processus, avec une difference :
la leur affiche « PID 1432 en cours » et le journal brut. Ici les etapes
nommees defilent, parce que progress_monitor sait deja les lire.

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

from interface.lifecycle_service import USER_STATUSES, save_suivi, set_status
from webui import donnees


# La version figure dans l'URL des fichiers statiques (?v=...). La changer
# force le navigateur a recharger CSS et JS : sans cela, une correction dans
# la feuille de style reste invisible tant que le cache n'est pas vide — et
# rien n'indique a l'utilisateur qu'il regarde une version perimee.
WEBUI_VERSION = "0.4"

RACINE = Path(__file__).resolve().parent
GABARITS = Jinja2Templates(directory=str(RACINE / "templates"))

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


# ------------------------------------------------------------------ pages

def _commun(actif: str, total: int, dues: int) -> dict:
    return {"version": WEBUI_VERSION, "actif": actif,
            "total": total, "dues": dues}


async def page_jour(request):
    lignes, artefact = donnees.offres()
    jour = donnees.journee(lignes)
    return GABARITS.TemplateResponse(
        request, "jour.html",
        {**_commun("jour", len(lignes), len(jour["relances_dues"])),
         "artefact": artefact, "jour": jour,
         "run": donnees.etat_du_run()})


async def page_offres(request):
    lignes, artefact = donnees.offres()
    jour = donnees.journee(lignes)
    return GABARITS.TemplateResponse(
        request, "offres.html",
        {**_commun("offres", len(lignes), len(jour["relances_dues"])),
         "artefact": artefact,
         "offres_json": json.dumps(lignes, ensure_ascii=False),
         "triage_json": json.dumps(TRIAGE, ensure_ascii=False)})


async def page_statistiques(request):
    lignes, _artefact = donnees.offres()
    jour = donnees.journee(lignes)

    # Apercu par defaut : le calcul complet evalue plusieurs milliers
    # d'annonces. Memorise : il n'est refait qu'apres une collecte.
    complet = request.query_params.get("complet") == "1"
    pipeline = donnees.statistiques_pipeline()

    return GABARITS.TemplateResponse(
        request, "statistiques.html",
        {**_commun("statistiques", len(lignes), len(jour["relances_dues"])),
         "complet": complet, "marche": donnees.marche(complet=complet),
         **pipeline,
         "candidatures": donnees.statistiques_candidatures()})


async def page_a_venir(request):
    titre = request.path_params.get("nom", "").replace("-", " ").capitalize()
    lignes, _artefact = donnees.offres()
    return GABARITS.TemplateResponse(
        request, "a_venir.html",
        {**_commun("", len(lignes), 0), "titre": titre or "Cet écran"})


# -------------------------------------------------------------------- api

async def api_offres(request):
    lignes, artefact = donnees.offres()
    return JSONResponse({"artefact": artefact, "offres": lignes})


async def api_run_etat(request):
    return JSONResponse({**donnees.etat_du_run(),
                         "journal": donnees.journal_du_run(40)})


async def api_run_lancer(request):
    """
    Lance le pipeline complet.

    Le refus quand un run tourne deja n'est pas une precaution de confort :
    deux pipelines simultanes ecriraient dans la meme base et produiraient
    des artefacts entremeles. Le verrou existe cote runner ; on le respecte
    ici plutot que de decouvrir le conflit apres coup.
    """
    from interface import pipeline_runner as runner

    if runner.is_running():
        return JSONResponse({"erreur": "Un run est déjà en cours."}, 409)
    try:
        journal = runner.launch_daily_run()
        return JSONResponse({"lance": True, "journal": str(journal)})
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


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

    offre = donnees.offre_par_cle(cle)
    if not offre:
        return JSONResponse({"erreur": "Offre introuvable."}, 404)

    try:
        donnees.invalider_suivi()
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

    offre = donnees.offre_par_cle(str(corps.get("cle") or ""))
    if not offre:
        return JSONResponse({"erreur": "Offre introuvable."}, 404)

    try:
        donnees.invalider_suivi()
        set_status(offre, "APPLIED", note=corps.get("note"))
        return JSONResponse({"cle": offre["stable_item_key"],
                             "statut": "APPLIED"})
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_suivi(request):
    corps = await request.json()
    offre = donnees.offre_par_cle(str(corps.get("cle") or ""))
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
        donnees.invalider_suivi()
        return JSONResponse({"cle": offre["stable_item_key"], "suivi": valeurs})
    except ValueError as erreur:
        return JSONResponse({"erreur": str(erreur)}, 400)
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_relances(request):
    from interface.lifecycle_service import relances_dues
    return JSONResponse({"dues": relances_dues()})


application = Starlette(
    routes=[
        Route("/", page_jour),
        Route("/offres", page_offres),
        Route("/statistiques", page_statistiques),
        Route("/bientot/{nom}", page_a_venir),
        Route("/api/offres", api_offres),
        Route("/api/run", api_run_etat),
        Route("/api/run/lancer", api_run_lancer, methods=["POST"]),
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
    # Les calculs couteux partent tout de suite en arriere-plan : la premiere
    # page ne doit pas payer treize secondes que les suivantes ne paieront plus.
    donnees.prechauffer()
    uvicorn.run(application, host="127.0.0.1", port=8600, log_level="warning")


if __name__ == "__main__":
    main()

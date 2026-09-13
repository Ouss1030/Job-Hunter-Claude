"""
JOB HUNTER BELGIUM
INTERFACE WEB - VERSION 1.0

    python -m webui.serveur
    -> http://127.0.0.1:8600

Pourquoi une seconde interface
------------------------------
Streamlit impose son rendu. On lui decrit des composants, il decide de leur
apparence, de leur densite et de leur mise en page. C'est excellent pour
sortir un outil interne en une soiree, et c'est une impasse des qu'on veut
maitriser la forme.

Cette interface est servie en HTML : chaque pixel est ecrit ici ou dans la
feuille de style. Rien n'est impose.

V1.0 — une seule page
---------------------
Les versions 0.x rendaient une page par ecran, rechargee entierement a
chaque navigation : l'aller-retour serveur etait visible, et l'utilisateur
l'a nomme « pas fluide ». Il avait raison.

Le serveur ne rend plus qu'une coquille HTML, une fois. Tout le reste est
du JSON, et c'est le navigateur qui dessine les ecrans et anime les
transitions. Passer d'un ecran a l'autre ne coute plus qu'un appel leger,
souvent aucun — les donnees deja recues sont gardees.

Aucune dependance nouvelle
--------------------------
Starlette, Jinja2 et uvicorn sont deja presents. Aucun Node, aucune etape
de compilation : les graphiques sont dessines en SVG par le navigateur, sans
bibliotheque.

Ce qui est conserve des versions precedentes
--------------------------------------------
Tout : le triage au clavier, la fiche de suivi, l'analyse d'ecart avec ses
preuves, le lancement de run avec suivi, la memoire des calculs, la case a
cocher obligatoire avant APPLIED. Seule la facon de les presenter change.

Toute la logique metier vient de interface/ et statistiques/, qui ne
dependent d'aucun framework d'affichage.
"""

from __future__ import annotations

from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from interface.lifecycle_service import USER_STATUSES, save_suivi, set_status
from webui import donnees


WEBUI_VERSION = "1.1"

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

# Ce qui se passe APRES l'envoi : ce sont des faits que seul le candidat
# connait, il les declare lui-meme. APPLIED n'est pas dans cette liste —
# il garde sa route dediee et sa confirmation explicite.
SUITE = (
    {"statut": "INTERVIEW", "libelle": "Entretien"},
    {"statut": "OFFER", "libelle": "Offre reçue"},
    {"statut": "REJECTED", "libelle": "Refus"},
)


# --------------------------------------------------------------- coquille

async def coquille(request):
    """
    La seule page servie. Toutes les routes d'ecran y menent : le navigateur
    lit l'adresse et dessine l'ecran voulu.
    """
    return GABARITS.TemplateResponse(
        request, "app.html", {"version": WEBUI_VERSION})


# -------------------------------------------------------------------- api

async def api_jour(request):
    lignes, artefact = donnees.offres()
    return JSONResponse({
        "artefact": artefact,
        "total": len(lignes),
        "jour": donnees.journee(lignes),
        "run": donnees.etat_du_run(),
    })


async def api_offres(request):
    lignes, artefact = donnees.offres()
    feedbacks = donnees.feedbacks_par_cle()
    for ligne in lignes:
        fb = feedbacks.get(ligne.get("stable_item_key"))
        ligne["feedback"] = ({"etoiles": round(float(fb.get("user_score") or 0) / 20) or None,
                              "note": fb.get("note") or ""} if fb else None)
    return JSONResponse({"artefact": artefact, "offres": lignes,
                         "triage": list(TRIAGE), "suite": list(SUITE)})


async def api_suivi_tableau(request):
    return JSONResponse(donnees.suivi())


async def api_feedback(request):
    corps = await request.json()
    offre = donnees.offre_par_cle(str(corps.get("cle") or ""))
    if not offre:
        return JSONResponse({"erreur": "Offre introuvable."}, 404)
    try:
        return JSONResponse(donnees.enregistrer_feedback(
            offre, corps.get("etoiles"), str(corps.get("note") or "")))
    except ValueError as erreur:
        return JSONResponse({"erreur": str(erreur)}, 400)
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_handoff(request):
    return JSONResponse(donnees.handoff_etat())


async def api_handoff_creer(request):
    """
    Cree les paquets a coller dans ChatGPT, a partir des offres choisies.

    L'ancienne interface filtrait par action (APPLY_NOW) et generait tout.
    Ici le candidat coche ce qu'il veut : dix offres bien choisies valent
    mieux que soixante-quatorze dont il n'a pas encore decide.
    """
    corps = await request.json()
    cles = [str(c) for c in (corps.get("cles") or []) if c]
    if not cles:
        return JSONResponse({"erreur": "Aucune offre sélectionnée."}, 400)
    try:
        return JSONResponse(donnees.handoff_creer(
            cles, int(corps.get("taille") or 10)))
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_ouvrir_dossier(request):
    """Ouvre un dossier d'export dans l'explorateur — local, jamais distant."""
    from interface.handoff_service import open_folder
    corps = await request.json()
    chemin = Path(str(corps.get("chemin") or ""))
    # On n'ouvre que sous exports/ : une route qui ouvrirait n'importe quel
    # chemin serait une porte, meme sur une machine locale.
    racine = RACINE.parent / "exports"
    try:
        if not chemin.resolve().is_relative_to(racine.resolve()):
            return JSONResponse({"erreur": "Chemin hors de exports/."}, 400)
        open_folder(chemin)
        return JSONResponse({"ouvert": str(chemin)})
    except Exception as erreur:
        return JSONResponse({"erreur": str(erreur)}, 500)


async def api_conseils(request):
    # Si l'artefact n'existe pas encore, la premiere demande le calcule et
    # attend. La page affiche « calcul en cours » pendant ce temps plutot
    # que de laisser un ecran vide sans explication.
    if not donnees.conseils_prets():
        if request.query_params.get("attendre") != "1":
            return JSONResponse({"en_cours": True}, 202)
    return JSONResponse(donnees.conseils())


async def api_statistiques(request):
    complet = request.query_params.get("complet") == "1"
    return JSONResponse({
        "marche": donnees.marche(complet=complet),
        "complet": complet,
        **donnees.statistiques_pipeline(),
        "candidatures": donnees.statistiques_candidatures(),
    })


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
        applique = set_status(offre, statut, note=corps.get("note"))
        donnees.invalider_suivi()
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
        set_status(offre, "APPLIED", note=corps.get("note"))
        donnees.invalider_suivi()
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


ECRANS = ("/", "/offres", "/suivi", "/conseils", "/statistiques", "/handoff")

application = Starlette(
    routes=[
        *[Route(chemin, coquille) for chemin in ECRANS],
        Route("/api/jour", api_jour),
        Route("/api/offres", api_offres),
        Route("/api/conseils", api_conseils),
        Route("/api/statistiques", api_statistiques),
        Route("/api/run", api_run_etat),
        Route("/api/run/lancer", api_run_lancer, methods=["POST"]),
        Route("/api/statut", api_statut, methods=["POST"]),
        Route("/api/postule", api_postule, methods=["POST"]),
        Route("/api/suivi", api_suivi, methods=["POST"]),
        Route("/api/relances", api_relances),
        Route("/api/suivi-tableau", api_suivi_tableau),
        Route("/api/feedback", api_feedback, methods=["POST"]),
        Route("/api/handoff", api_handoff),
        Route("/api/handoff/creer", api_handoff_creer, methods=["POST"]),
        Route("/api/ouvrir", api_ouvrir_dossier, methods=["POST"]),
        Mount("/static", StaticFiles(directory=str(RACINE / "static")),
              name="static"),
    ]
)


def _console_utf8() -> None:
    """
    La console Windows est en cp1252. Un service qui imprime un emoji —
    handoff_service ecrit « ✅ » — faisait echouer la requete entiere sur
    UnicodeEncodeError, mesure le 13 septembre 2026. Le lanceur pose
    PYTHONUTF8, mais le serveur ne doit pas dependre de la facon dont on le
    lance : un caractere non encodable devient « ? », jamais une erreur.
    """
    import sys
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def main() -> None:
    _console_utf8()
    print("=" * 70)
    print(f"JOBHUNTER — INTERFACE WEB V{WEBUI_VERSION}")
    print("=" * 70)
    print("  http://127.0.0.1:8600")
    print("  Ctrl+C pour arrêter.")
    print()
    # Les calculs couteux partent tout de suite en arriere-plan : la premiere
    # page ne doit pas payer ce que les suivantes ne paieront plus.
    donnees.prechauffer()
    uvicorn.run(application, host="127.0.0.1", port=8600, log_level="warning")


if __name__ == "__main__":
    main()

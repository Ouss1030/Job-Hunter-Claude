"""
JOB HUNTER BELGIUM
INTERFACE WEB - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.webui_v1_audit

Ce que l'audit protege
----------------------
Une interface qui ne demarre pas se voit tout de suite. Une interface qui
demarre en affichant des donnees fausses ne se voit pas du tout — et c'est
elle qui oriente les decisions.

L'audit verifie donc surtout des proprietes de sens :

    1. les gabarits compilent, et chacun herite bien du gabarit commun ;
    2. l'ecran du jour distingue les statuts poses par le PIPELINE de ceux
       qui traduisent une DECISION du candidat — sans quoi il annoncerait
       que tout est traite alors que rien ne l'est ;
    3. l'analyse d'ecart transporte la PREUVE, pas seulement le verdict.

Ce troisieme point n'est pas cosmetique : trois faux positifs du moteur ont
ete trouves le 10 septembre 2026 en lisant a l'ecran la phrase citee, et
aucun n'aurait ete visible autrement.

Aucun serveur n'est demarre, aucune requete n'est emise.
"""

from __future__ import annotations

import inspect
from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least
from webui import donnees, serveur


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"
GABARITS = Path(__file__).resolve().parents[1] / "webui" / "templates"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print(f"INTERFACE WEB V{serveur.WEBUI_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    print("A. GABARITS")
    print("-" * 92)
    from jinja2 import Environment, FileSystemLoader
    env = Environment(loader=FileSystemLoader(str(GABARITS)))
    attendus = ("_base.html", "jour.html", "offres.html",
                "statistiques.html", "a_venir.html")
    for nom in attendus:
        try:
            env.get_template(nom)
            ok = True
        except Exception as erreur:
            ok, nom = False, f"{nom} : {erreur}"
        tests.append(check(f"Gabarit compile : {nom}", ok))

    # Un ecran qui n'herite pas du gabarit commun perd la navigation, et
    # devient une impasse pour qui y arrive.
    for nom in ("jour.html", "offres.html", "statistiques.html", "a_venir.html"):
        source = (GABARITS / nom).read_text(encoding="utf-8")
        tests.append(check(f"{nom} hérite du gabarit commun",
                           'extends "_base.html"' in source))

    print()
    print("B. ROUTES")
    print("-" * 92)
    chemins = {r.path for r in serveur.application.routes if hasattr(r, "path")}
    for chemin in ("/", "/offres", "/statistiques", "/api/offres",
                   "/api/run", "/api/run/lancer", "/api/statut",
                   "/api/postule", "/api/suivi", "/api/relances"):
        tests.append(check(f"Route déclarée : {chemin}", chemin in chemins))

    methodes = {r.path: getattr(r, "methods", set())
                for r in serveur.application.routes if hasattr(r, "path")}
    for chemin in ("/api/statut", "/api/postule", "/api/suivi",
                   "/api/run/lancer"):
        tests.append(check(f"{chemin} n'accepte que POST",
                           "POST" in (methodes.get(chemin) or set())
                           and "GET" not in (methodes.get(chemin) or set()),
                           str(sorted(methodes.get(chemin) or []))))

    print()
    print("C. L'ECRAN DU JOUR DISTINGUE PIPELINE ET DECISION")
    print("-" * 92)
    # READY et DOCUMENTS_READY sont poses par le pipeline. Les compter comme
    # des decisions ferait dire a l'ecran que 103 offres sur 117 sont
    # traitees, alors qu'aucune ne l'est.
    tests.append(check(
        "READY compte comme non triée",
        "READY" in donnees._STATUTS_PIPELINE))
    tests.append(check(
        "DOCUMENTS_READY aussi",
        "DOCUMENTS_READY" in donnees._STATUTS_PIPELINE))
    tests.append(check(
        "SHORTLISTED est une décision, pas un statut de pipeline",
        "SHORTLISTED" not in donnees._STATUTS_PIPELINE))
    tests.append(check(
        "APPLIED non plus",
        "APPLIED" not in donnees._STATUTS_PIPELINE))

    fausses = [
        {"application_status": s, "recommended_action_v12": "APPLY_NOW",
         "verdict": "ACCESSIBLE", "final_score_v12": 100,
         "stable_item_key": f"K{i}", "title": f"T{i}", "company": "C",
         "ville": "V"}
        for i, s in enumerate(("", "READY", "SHORTLISTED", "APPLIED"))
    ]
    jour = donnees.journee(fausses)
    tests.append(check("Deux offres sur quatre restent à trier",
                       jour["non_triees"] == 2, str(jour["non_triees"])))
    tests.append(check("Et les deux sont recommandées",
                       jour["a_postuler_non_triees"] == 2))
    tests.append(check("Une offre FERMEE n'est jamais proposée au tri",
                       donnees.journee([{**fausses[0], "verdict": "FERMEE"}])
                       ["a_postuler_non_triees"] == 0))
    tests.append(check("Liste vide : aucune exception",
                       donnees.journee([])["non_triees"] == 0))

    print()
    print("D. L'ANALYSE D'ECART TRANSPORTE LA PREUVE")
    print("-" * 92)
    bourrage = (" Nous offrons un environnement agreable et une equipe "
                "soudee sur notre site belge. " * 4)
    ecart = donnees._analyse_ecart(
        "Ingenieur systemes",
        "Vous etes titulaire d'un master en informatique de gestion."
        + bourrage)
    tests.append(check("Une barrière est rendue", bool(ecart["barrieres"])))
    tests.append(check("Elle porte un message lisible",
                       bool(ecart["barrieres"][0]["message"])))
    tests.append(check("Elle cite la phrase de l'annonce",
                       bool(ecart["barrieres"][0]["preuve"]),
                       ecart["barrieres"][0]["preuve"][:60]))
    tests.append(check("La preuve vient bien du texte fourni",
                       "informatique" in ecart["barrieres"][0]["preuve"].lower()))

    ouvert = donnees._analyse_ecart(
        "Technicien de laboratoire",
        "Analyses de routine au laboratoire, HPLC et Excel." + bourrage)
    tests.append(check("Une offre ouverte n'a aucune barrière",
                       ouvert["barrieres"] == []))
    tests.append(check("Mais ses atouts sont remontés",
                       bool(ouvert["atouts"]), str(ouvert["atouts"][:4])))
    tests.append(check("Texte vide : structure quand même valide",
                       donnees._analyse_ecart("", "")["barrieres"] == []))

    print()
    print("E. LE TRIAGE RESTE SUR DES STATUTS SURS")
    print("-" * 92)
    source_lancer = inspect.getsource(serveur.api_run_lancer)
    tests.append(check("Un run déjà en cours est refusé",
                       "is_running()" in source_lancer and "409" in source_lancer))
    tests.append(check("Le journal du run est borné",
                       "lignes_max" in inspect.getsource(donnees.journal_du_run)))

    print()
    print("G. DEUX DEFAUTS QUI ONT RENDU TOUS LES BOUTONS MUETS")
    print("-" * 92)
    # Le 12 septembre 2026, aucun bouton ne repondait plus. Rien dans le code
    # des boutons n'etait en cause : la carte des raccourcis clavier, marquee
    # hidden mais en display:grid, recouvrait la page entiere en z-index 40
    # et avalait chaque clic. L'attribut hidden n'a que la priorite de la
    # feuille de style du navigateur ; une regle d'auteur le bat.
    css = (GABARITS.parent / "static" / "style.css").read_text(encoding="utf-8")
    tests.append(check(
        "[hidden] est declare avec !important",
        "[hidden]" in css and "!important" in css.split("[hidden]", 1)[1][:80]))

    import re
    # Le correctif CSS restait invisible : le navigateur servait l'ancien
    # fichier depuis son cache. Les URL statiques portent donc la version.
    for nom in ("_base.html", "offres.html", "jour.html"):
        source = (GABARITS / nom).read_text(encoding="utf-8")
        refs = re.findall(r'/static/[^"\s]+', source)
        tests.append(check(
            f"{nom} : toute URL statique est versionnée",
            refs and all("?v=" in r for r in refs), str(refs)))

    print()
    print("H. LA MEMOIRE DES CALCULS")
    print("-" * 92)
    # Mesure du 13 septembre 2026, avant la memoire : page Offres 1 457 ms,
    # page Statistiques 13 446 ms, tout recalcule a chaque clic. Apres :
    # 10 ms et 3 ms. Le cache doit rendre vite ET ne jamais rendre du perime.
    from webui.memo import Memoire
    m = Memoire()
    appels = []
    calcul = lambda: appels.append(1) or len(appels)
    a = m.obtenir("x", ("e1",), calcul)
    b = m.obtenir("x", ("e1",), calcul)
    tests.append(check("Meme empreinte : une seule execution du calcul",
                       a == b == 1 and len(appels) == 1))
    c = m.obtenir("x", ("e2",), calcul)
    tests.append(check("Empreinte changee : recalcul",
                       c == 2 and len(appels) == 2))
    m.oublier("x")
    d = m.obtenir("x", ("e2",), calcul)
    tests.append(check("Oubli explicite : recalcul meme a empreinte egale",
                       d == 3))

    # La base est en WAL : la date de jobs.db ne bouge pas a chaque
    # ecriture. L'invalidation doit donc etre explicite.
    avant = donnees._empreinte_base()
    donnees.invalider_suivi()
    tests.append(check("invalider_suivi() change l'empreinte du suivi",
                       donnees._empreinte_base() != avant))
    tests.append(check("L'empreinte du pool se calcule sans lire de JSON",
                       "json.loads" not in inspect.getsource(donnees._empreinte_pool)
                       and "read_text" not in inspect.getsource(donnees._empreinte_pool)))
    tests.append(check("Chaque ecriture du serveur invalide la memoire",
                       inspect.getsource(serveur).count("invalider_suivi()") >= 3))

    print()
    print("F. VERSIONS")
    print("-" * 92)
    tests.append(check("Interface web au moins 0.4",
                       at_least(serveur.WEBUI_VERSION, "0.4"),
                       serveur.WEBUI_VERSION))
    tests.append(check("Préparation des données au moins 1.0",
                       at_least(donnees.DONNEES_VERSION, "1.1"),
                       donnees.DONNEES_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] INTERFACE WEB VALIDEE HORS LIGNE."
              if passed == total else "[FAIL] INTERFACE WEB NON VALIDEE.")

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"webui_v1_audit_{stamp}.txt").write_text(
        "\n".join([f"INTERFACE WEB V{serveur.WEBUI_VERSION}", "=" * 92,
                   f"Tests : {passed}/{total}", statut]), encoding="utf-8")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

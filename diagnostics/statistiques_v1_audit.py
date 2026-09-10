"""
JOB HUNTER BELGIUM
STATISTIQUES - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.statistiques_v1_audit

Une statistique fausse est pire qu'aucune statistique : elle se lit comme un
fait et oriente des decisions. Ce projet en a fait l'experience le
10 septembre 2026 — le compteur de competences manquantes annoncait 407
offres exigeant la « culture cellulaire » alors qu'il comptait des
« culture d'entreprise ».

L'audit verifie donc trois choses :

    1. les mesures se calculent sans exception sur des donnees vides,
       partielles ou aberrantes ;
    2. les comptages portent bien sur les offres OUVERTES, pas sur tout ;
    3. l'etat « aucune candidature envoyee » est rendu explicitement, et
       jamais confondu avec un taux de reponse de zero.

Bases et dossiers temporaires : l'audit ne lit jamais jobs.db ni
exports/logs. Un test dont le resultat depend du contenu du jour ne prouve
rien.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least
from statistiques import STATISTIQUES_VERSION
from statistiques.candidatures import analyser_candidatures
from statistiques.marche import _ville, analyser_marche
from statistiques.pipeline import (
    entonnoir_par_run,
    evolution,
    rendement_des_sources,
)


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"

BOURRAGE = (" Nous offrons un environnement de travail agreable et une equipe "
            "soudee. Le poste est a pourvoir immediatement sur notre site "
            "belge, en Belgique. " * 3)


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def base_marche(dossier: Path) -> Path:
    """Trois offres ouvertes, une fermee : les comptages doivent ignorer la fermee."""
    chemin = dossier / "marche.db"
    c = sqlite3.connect(chemin)
    c.execute("CREATE TABLE raw_jobs (id INTEGER PRIMARY KEY, is_active INTEGER,"
              " title TEXT, company TEXT, location TEXT, source TEXT,"
              " contract_type TEXT, description TEXT, detail_matching_text TEXT)")

    def ajouter(ident, actif, titre, societe, lieu, source, texte):
        c.execute("INSERT INTO raw_jobs VALUES (?,?,?,?,?,?,?,?,?)",
                  (ident, actif, titre, societe, lieu, source, "CDI",
                   texte + BOURRAGE, texte + BOURRAGE))

    ajouter(1, 1, "Technicien de laboratoire", "ACME", "1000 Bruxelles",
            "FOREM", "Analyses en controle qualite, HPLC et Excel au quotidien.")
    ajouter(2, 1, "Laborantin", "ACME", "2000 Anvers", "FOREM",
            "Connaissance HACCP requise en agroalimentaire, Excel exige.")
    ajouter(3, 1, "Analyste QC", "BIOTECH", "1000 Bruxelles", "ACTIRIS",
            "Analyses de routine au laboratoire, GMP et Excel.")
    # Fermee : un master en informatique, domaine incompatible.
    ajouter(4, 1, "Ingenieur systemes", "SOFT", "1000 Bruxelles", "ACTIRIS",
            "Vous etes titulaire d'un master en informatique de gestion.")
    # Inactive : ne doit jamais compter.
    ajouter(5, 0, "Poste ferme", "VIEUX", "1000 Bruxelles", "FOREM",
            "Analyses en laboratoire, Excel et HPLC.")
    # Deux HACCP de plus : le seuil de significativite est de trois offres,
    # et c'est voulu — en dessous, un comptage n'est qu'un accident. Le jeu
    # d'essai doit donc franchir ce seuil pour l'exercer vraiment.
    ajouter(6, 1, "Technicien qualite", "ACME", "1000 Bruxelles", "FOREM",
            "Normes HACCP en agroalimentaire, suivi sous Excel.")
    ajouter(7, 1, "Laborantin agro", "ACME", "2000 Anvers", "FOREM",
            "Plan HACCP a maintenir, rapports Excel hebdomadaires.")
    c.commit()
    c.close()
    return chemin


def dossier_artefacts(dossier: Path) -> Path:
    """Deux runs successifs, pour que l'evolution ait un sens."""
    racine = dossier / "logs"
    racine.mkdir()

    def file(stamp, pretes, tension, verif, ecart, source="FOREM"):
        items = []
        for i in range(pretes):
            items.append({"queue_status": "READY_APPLY", "verdict": "ACCESSIBLE",
                          "source": source, "title": f"pret {i}"})
        for i in range(tension):
            items.append({"queue_status": "READY_STRETCH", "verdict": "A_VERIFIER",
                          "source": "ACTIRIS", "title": f"tension {i}"})
        for i in range(verif):
            items.append({"queue_status": "VERIFY_FIRST", "verdict": "INCONNU",
                          "source": "ACTIRIS", "title": f"verif {i}"})
        for i in range(ecart):
            items.append({"queue_status": "EXCLUDED", "verdict": "FERMEE",
                          "source": "ACTIRIS", "title": f"ecart {i}"})
        (racine / f"application_queue_v1_{stamp}.json").write_text(
            json.dumps(items), encoding="utf-8")

    def pool(stamp, total):
        (racine / f"final_application_pool_v12_{stamp}.json").write_text(
            json.dumps({"pool": [{"recommended_action_v12": "APPLY_NOW"}
                                 for _ in range(total)]}), encoding="utf-8")

    file("20260901_100000", 10, 5, 3, 20)
    pool("20260901_100500", 8)
    file("20260902_100000", 14, 6, 4, 25)
    pool("20260902_100500", 12)
    return racine


def main():
    print("=" * 92)
    print(f"STATISTIQUES V{STATISTIQUES_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    with tempfile.TemporaryDirectory() as tmp:
        dossier = Path(tmp)

        print("A. MARCHE — LE PERIMETRE EST BIEN LES OFFRES OUVERTES")
        print("-" * 92)
        marche = analyser_marche(chemin_base=base_marche(dossier))
        tests.append(check("Les offres inactives sont exclues",
                           marche["offres_actives"] == 6,
                           str(marche["offres_actives"])))
        tests.append(check("Seules les offres ouvertes sont comptees",
                           marche["offres_ouvertes"] == 5,
                           f"{marche['offres_ouvertes']} / "
                           f"{marche['offres_actives']}"))
        tests.append(check("L'offre fermee est vue comme fermee",
                           marche["verdicts"].get("FERMEE") == 1,
                           str(marche["verdicts"])))

        acquerir = {x["nom"]: x["offres"] for x in marche["a_acquerir"]}
        tests.append(check("HACCP compte comme manque",
                           any("HACCP" in n for n in acquerir), str(acquerir)))
        valoriser = {x["nom"]: x["offres"] for x in marche["a_valoriser"]}
        tests.append(check("Excel compte dans les cinq offres ouvertes",
                           valoriser.get("Excel") == 5, str(valoriser)))
        tests.append(check(
            "Sous le seuil de trois offres, rien n'est remonte",
            all(x["offres"] >= 3 for x in marche["a_acquerir"]),
            str(acquerir)))
        tests.append(check(
            "Aucun comptage ne depasse le nombre d'offres ouvertes",
            all(x["offres"] <= marche["offres_ouvertes"]
                for x in marche["a_valoriser"] + marche["a_acquerir"])))
        tests.append(check(
            "Les parts sont des pourcentages plausibles",
            all(0 <= x["part"] <= 100
                for x in marche["a_valoriser"] + marche["employeurs"])))

        print()
        print("B. MARCHE — ROBUSTESSE")
        print("-" * 92)
        tests.append(check("Base absente : erreur nommee, pas d'exception",
                           "erreur" in analyser_marche(
                               chemin_base=dossier / "absente.db")))
        vide = dossier / "vide.db"
        c = sqlite3.connect(vide)
        c.execute("CREATE TABLE raw_jobs (id INTEGER PRIMARY KEY,"
                  " is_active INTEGER, title TEXT, company TEXT,"
                  " location TEXT, source TEXT, contract_type TEXT,"
                  " description TEXT, detail_matching_text TEXT)")
        c.commit()
        c.close()
        resultat_vide = analyser_marche(chemin_base=vide)
        tests.append(check("Base vide : zero partout, pas de division par zero",
                           resultat_vide["offres_ouvertes"] == 0
                           and resultat_vide["a_acquerir"] == []))

        print()
        print("C. VILLE — LES ADRESSES NE SONT PAS DES VILLES")
        print("-" * 92)
        # Sans ce nettoyage, chaque offre aurait un lieu unique et le
        # classement des localisations ne dirait rien.
        for brut, attendu in (
            ("Avenue Jules Bordet 168 1140 Bruxelles", "Bruxelles"),
            ("2000 Anvers", "Anvers"),
            ("", "inconnu"),
        ):
            obtenu = _ville(brut)
            tests.append(check(f"« {brut[:34]} » -> {obtenu}",
                               attendu in obtenu, obtenu))

        print()
        print("D. PIPELINE — L'ENTONNOIR ET SON EVOLUTION")
        print("-" * 92)
        artefacts = dossier_artefacts(dossier)
        lignes = entonnoir_par_run(artefacts)
        tests.append(check("Un run par artefact de file", len(lignes) == 2,
                           str(len(lignes))))
        tests.append(check("Les runs sont ordonnes du plus ancien au recent",
                           lignes[0]["quand"] < lignes[1]["quand"],
                           f"{lignes[0]['quand']} -> {lignes[1]['quand']}"))
        tests.append(check("Les statuts sont comptes correctement",
                           lignes[1]["pretes"] == 14
                           and lignes[1]["a_tension"] == 6
                           and lignes[1]["ecartees"] == 25))
        tests.append(check("Le pool du meme run est rattache",
                           lignes[1]["pool"] == 12, str(lignes[1]["pool"])))

        ecart = evolution(lignes)
        tests.append(check("L'evolution mesure le delta premier -> dernier",
                           ecart["ecarts"]["pretes"]["delta"] == 4,
                           str(ecart["ecarts"]["pretes"])))
        tests.append(check("Un seul run : aucune evolution inventee",
                           evolution(lignes[:1]) == {}))
        tests.append(check("Dossier absent : liste vide, pas d'exception",
                           entonnoir_par_run(dossier / "nulle part") == []))

        print()
        print("E. PIPELINE — RENDEMENT REEL DES SOURCES")
        print("-" * 92)
        rendement = {x["source"]: x for x in rendement_des_sources(artefacts)}
        tests.append(check(
            "Le rendement rapporte les PRETES, pas le volume",
            rendement["FOREM"]["pretes"] == 14
            and rendement["ACTIRIS"]["pretes"] == 0,
            str({k: v["pretes"] for k, v in rendement.items()})))
        tests.append(check(
            "Une source volumineuse et sterile a un rendement nul",
            rendement["ACTIRIS"]["offres"] > rendement["FOREM"]["offres"]
            and rendement["ACTIRIS"]["rendement"] == 0.0,
            f"ACTIRIS {rendement['ACTIRIS']['offres']} offres, "
            f"{rendement['ACTIRIS']['rendement']} %"))

        print()
        print("F. CANDIDATURES — L'ETAT VIDE EST EXPLICITE")
        print("-" * 92)
        base = dossier / "cand.db"
        c = sqlite3.connect(base)
        c.execute("CREATE TABLE application_events (id INTEGER PRIMARY KEY,"
                  " entity_id INTEGER, event_type TEXT, status TEXT,"
                  " event_at TEXT, source TEXT)")
        c.execute("CREATE TABLE application_entities (id INTEGER PRIMARY KEY,"
                  " title TEXT, company TEXT, track TEXT)")
        c.execute("INSERT INTO application_entities VALUES (1,'T','C','LAB_QC')")
        c.execute("INSERT INTO application_events VALUES "
                  "(1,1,'SEEN','SEEN','2026-09-01T10:00:00','FOREM')")
        c.commit()
        c.close()
        vide_cand = analyser_candidatures(chemin_base=base)
        tests.append(check("Aucun envoi : etat nomme, pas un taux de 0 %",
                           vide_cand["etat"] == "AUCUNE_CANDIDATURE_ENVOYEE"))
        tests.append(check("Aucun taux de reponse n'est invente",
                           "taux_de_reponse" not in vide_cand,
                           str(sorted(vide_cand))))
        tests.append(check("Les dossiers suivis restent comptes",
                           vide_cand["dossiers_suivis"] == 1))

        c = sqlite3.connect(base)
        c.execute("INSERT INTO application_events VALUES "
                  "(2,1,'STATUS','APPLIED','2026-09-02T10:00:00','FOREM')")
        c.execute("INSERT INTO application_events VALUES "
                  "(3,1,'STATUS','INTERVIEW','2026-09-07T10:00:00','FOREM')")
        c.commit()
        c.close()
        actif = analyser_candidatures(chemin_base=base)
        tests.append(check("Un envoi bascule l'etat en ACTIF",
                           actif["etat"] == "ACTIF" and actif["envoyees"] == 1))
        tests.append(check("Le delai de reponse est mesure en jours",
                           actif["delai_median_jours"] == 5,
                           str(actif["delai_median_jours"])))
        tests.append(check("Le taux de reponse est calcule",
                           actif["taux_de_reponse"] == 100.0))
        tests.append(check("Base absente : erreur nommee",
                           "erreur" in analyser_candidatures(
                               chemin_base=dossier / "rien.db")))

    print()
    print("G. VERSION")
    print("-" * 92)
    tests.append(check("Version au moins 1.0",
                       at_least(STATISTIQUES_VERSION, "1.0"),
                       STATISTIQUES_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] STATISTIQUES VALIDEES HORS LIGNE."
              if passed == total else "[FAIL] STATISTIQUES NON VALIDEES.")

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"statistiques_v1_audit_{stamp}.txt").write_text(
        "\n".join([f"STATISTIQUES V{STATISTIQUES_VERSION}", "=" * 92,
                   f"Tests : {passed}/{total}", statut]), encoding="utf-8")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

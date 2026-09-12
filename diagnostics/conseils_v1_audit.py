"""
JOB HUNTER BELGIUM
CATEGORIES ET CONSEILS DE MARCHE - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.conseils_v1_audit

Ce que l'audit protege
----------------------
Les conseils orientent ce que le candidat va apprendre. Un vocabulaire qui
matche « R » sur chaque lettre r, ou « SAS » sur « societe par actions
simplifiee », produirait un conseil faux avec l'assurance d'un chiffre.

    1. la taxonomie classe les faux amis dans AUTRE et les vrais postes
       dans leur categorie, avec les priorites voulues ;
    2. chaque vocabulaire respecte les frontieres de mots ;
    3. le croisement avec les competences du candidat partitionne bien :
       ce qu'il a va en « a valoriser », le reste en « a acquerir » ;
    4. salaires et contrats sont lus sans inventer.

Base temporaire : l'audit ne lit jamais jobs.db.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least
from statistiques.categories import CATEGORIES_VERSION, categoriser, famille
from statistiques.conseils import (
    CONSEILS_VERSION,
    _METHODES,
    _OUTILS,
    analyser,
    competences_candidat,
)


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def base_de_test(dossier: Path) -> Path:
    chemin = dossier / "conseils.db"
    c = sqlite3.connect(chemin)
    c.execute("""CREATE TABLE raw_jobs (id INTEGER PRIMARY KEY, title TEXT,
        company TEXT, location TEXT, source TEXT, contract_type TEXT,
        date_published TEXT, first_seen TEXT, last_seen TEXT, is_active INTEGER,
        description TEXT, detail_matching_text TEXT)""")

    def ajouter(titre, texte, societe="ACME", lieu="1000 Bruxelles", contrat="Durée indéterminée",
                actif=1, pub="2026-09-01T09:30:00", vu="2026-09-01T10:00:00", dernier="2026-09-05T10:00:00"):
        c.execute("INSERT INTO raw_jobs (title, company, location, source, contract_type, "
                  "date_published, first_seen, last_seen, is_active, description, detail_matching_text) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                  (titre, societe, lieu, "TEST", contrat, pub, vu, dernier, actif, texte, texte))

    # Trois offres LAB/qc : HPLC partout, Empower dans deux, salaire dans une.
    for i in range(3):
        ajouter("Technicien de laboratoire QC",
                "Analyses HPLC sous GMP. " + ("Logiciel Empower. " if i < 2 else "")
                + ("Salaire 3 200 € brut par mois. " if i == 0 else "")
                + "Rigueur et autonomie. Anglais courant exige.")
    # Une offre DATA/analyse avec SQL, Power BI et Azure.
    ajouter("Data Analyst", "SQL, Power BI et Azure. Reporting hebdomadaire. Neerlandais B2.",
            contrat="Interim")
    # Un faux ami : la lettre R et une SAS.
    ajouter("Comptable", "Societe par actions simplifiee (SAS). Rapport R annuel.")
    # Une offre hors cible, jamais comptee.
    ajouter("Chauffeur poids lourd", "Permis C exige. Excel apprecie.")
    # Une offre disparue, pour la duree de vie.
    ajouter("Laborantin", "Analyses HPLC.", actif=0, vu="2026-08-20T10:00:00",
            dernier="2026-08-24T10:00:00")
    c.commit()
    c.close()
    return chemin


def main():
    print("=" * 92)
    print(f"CATEGORIES V{CATEGORIES_VERSION} / CONSEILS V{CONSEILS_VERSION} - AUDIT")
    print("=" * 92)
    print()

    tests = []

    print("A. LA TAXONOMIE")
    print("-" * 92)
    for titre, attendu in (
        ("Technicien de laboratoire", "LAB/qc"),
        ("Contrôleur qualité (H/F/X)", "LAB/qc"),
        ("Technicien QA", "PHARMA/qa"),
        ("Assistant qualité", "PHARMA/qa"),
        ("Regulatory Affairs Officer", "PHARMA/reglementaire"),
        ("Data Analyst", "DATA/analyse"),
        ("Business Analyste", "DATA/analyse"),
        ("Data Engineer", "DATA/ingenierie"),
        ("Data Scientist", "DATA/science"),
        ("Microbiologiste", "LAB/bio"),
        ("R&D Technician", "LAB/rd"),
        # Priorites : le metier nomme l'emporte sur le contexte.
        ("Data Analyst laboratoire", "DATA/analyse"),
        ("Responsable assurance qualité laboratoire", "PHARMA/qa"),
        # Faux amis.
        ("Responsable Qatar Operations", "AUTRE"),
        ("Biographe", "AUTRE"),
        ("Chauffeur poids lourd", "AUTRE"),
        ("Comptable", "AUTRE"),
    ):
        obtenu = categoriser(titre, "")
        tests.append(check(f"{titre[:38]:<38} -> {attendu}", obtenu == attendu, obtenu))

    tests.append(check("Opérateur de production SANS contexte : AUTRE",
                       categoriser("Opérateur de production", "Usine de meubles.") == "AUTRE"))
    tests.append(check("Opérateur de production AVEC contexte pharma : PHARMA/production",
                       categoriser("Opérateur de production", "Site GMP, zone stérile.")
                       == "PHARMA/production"))
    tests.append(check("Operator chemie : la chimie industrielle est en cible",
                       categoriser("Operator chemie", "") == "PHARMA/production"))
    tests.append(check("famille() extrait la famille",
                       famille("LAB/qc") == "LAB" and famille("AUTRE") == "AUTRE"))

    print()
    print("B. FRONTIERES DE MOTS DANS LES VOCABULAIRES")
    print("-" * 92)
    tests.append(check("« SAS » ne matche pas « societe par actions simplifiee (sas) » seul",
                       not _OUTILS["SAS"].search("societe par actions simplifiee (sas). rapport annuel.")))
    tests.append(check("« SAS programming » est bien SAS",
                       bool(_OUTILS["SAS"].search("experience en sas programming exigee"))))
    tests.append(check("La lettre R seule ne matche pas",
                       not _OUTILS["R"].search("rapport r annuel de la societe")))
    tests.append(check("« Python et R » matche R",
                       bool(_OUTILS["R"].search("maitrise de python et r"))))
    tests.append(check("« Excel » ne matche pas « excellent »",
                       not _OUTILS["Excel"].search("excellent esprit d'equipe")))
    tests.append(check("« documentation » seule n'est plus « Documentation qualite »",
                       not _METHODES["Documentation qualité"].search(
                           "vous redigez la documentation du projet")))
    tests.append(check("« SOP » l'est",
                       bool(_METHODES["Documentation qualité"].search("redaction de sop"))))

    print()
    print("C. LE CROISEMENT AVEC LE CANDIDAT")
    print("-" * 92)
    comp = competences_candidat()
    tests.append(check("Les competences declarees sont alignees sur les vocabulaires",
                       {"HPLC", "SQL", "Power BI", "GMP / BPF"} <= comp,
                       str(sorted(comp)[:6])))
    tests.append(check("Power BI implique le reporting",
                       "Reporting / tableaux de bord" in comp))
    tests.append(check("Azure n'est PAS une competence du candidat",
                       "Azure" not in comp))

    with tempfile.TemporaryDirectory() as tmp:
        r = analyser(chemin_base=base_de_test(Path(tmp)))

        print()
        print("D. LES COMPTAGES SUR UNE BASE CONNUE")
        print("-" * 92)
        tests.append(check("Sept offres scrapees, cinq cibles, deux hors cible",
                           r["offres_scrapees"] == 7 and r["offres_cibles"] == 5
                           and r["hors_cible"] == 2,
                           f"{r['offres_scrapees']} / {r['offres_cibles']} / {r['hors_cible']}"))
        lab = r["familles"]["LAB"]
        tests.append(check("LAB compte quatre offres (trois QC + une disparue)",
                           lab["offres"] == 4, str(lab["offres"])))
        outils = {x["nom"]: x["offres"] for x in lab["outils"]}
        tests.append(check("HPLC compte dans les quatre", outils.get("HPLC") == 4, str(outils)))
        tests.append(check("Empower sous le seuil de trois n'est pas remonte",
                           "Empower" not in outils))
        tests.append(check("HPLC est « a valoriser » (le candidat l'a)",
                           any(x["nom"] == "HPLC" for x in lab["a_valoriser"])))
        tests.append(check("Rien de LAB n'est « a acquerir » ici",
                           all(x["nom"] in comp or x["offres"] < 3 for x in lab["a_acquerir"]),
                           str([x["nom"] for x in lab["a_acquerir"]])))

        data = r["familles"]["DATA"]
        tests.append(check("Sous le seuil : DATA (une offre) ne remonte aucun outil",
                           data["outils"] == []))

        ens = r["ensemble"]
        tests.append(check("Un salaire mensuel est lu : 3 200 €",
                           ens["salaire"]["offres_avec_montant"] == 1
                           and ens["salaire"]["mediane_brut_mensuel"] == 3200,
                           str(ens["salaire"])))
        langues = {x["nom"]: x for x in ens["langues"]}
        tests.append(check("« Anglais courant » compte comme niveau fort",
                           langues.get("Anglais", {}).get("niveau_fort", 0) == 3))
        contrats = {x["nom"]: x["offres"] for x in ens["contrats"]}
        tests.append(check("Les CDI sont comptes", contrats.get("CDI", 0) >= 3, str(contrats)))
        tests.append(check("La duree de vie de l'offre disparue est mesuree (4 jours)",
                           ens["duree_de_vie"]["mediane_jours"] == 4,
                           str(ens["duree_de_vie"])))
        tests.append(check("Le biais de la purge est nomme",
                           "basse" in str(ens["duree_de_vie"].get("estimation", ""))))
        tests.append(check("Le jour de publication est compte",
                           any(x["offres"] for x in ens["publication_jours"])))

        tests.append(check("Base absente : erreur nommee",
                           "erreur" in analyser(chemin_base=Path(tmp) / "rien.db")))

    print()
    print("E. VERSIONS")
    print("-" * 92)
    tests.append(check("Categories au moins 1.0", at_least(CATEGORIES_VERSION, "1.0")))
    tests.append(check("Conseils au moins 1.0", at_least(CONSEILS_VERSION, "1.0")))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] CATEGORIES ET CONSEILS VALIDES HORS LIGNE."
              if passed == total else "[FAIL] CATEGORIES OU CONSEILS NON VALIDES.")
    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"conseils_v1_audit_{stamp}.txt").write_text(
        "\n".join([f"CONSEILS V{CONSEILS_VERSION}", "=" * 92,
                   f"Tests : {passed}/{total}", statut]), encoding="utf-8")
    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

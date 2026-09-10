"""
JOB HUNTER BELGIUM
PISTES DE CANDIDATURE - AUDIT V1.0 (HORS LIGNE)

    python -m diagnostics.piste_accessible_v1_audit

Aucun reseau, aucune base.

Ce que cet audit protege
------------------------
Le classement en pistes repose sur un equilibre fragile : elargir la piste
industrielle est facile, et chaque elargissement y fait entrer du bruit.

Deux faux positifs releves dans la base pendant la mise au point :

    « Coach Sportif / Preparateur Physique »
    « Preparateur.trice de Projets / Bureau d'Etudes »

Tous deux attrapes par le mot « preparateur » employe seul. C'est le meme
piege que « technicien » qui remonterait « Technicien de surface », ou
« labo » qui matcherait « elaboration ».

La regle de conception est donc : expressions composees uniquement, et une
liste d'exclusion explicite pour les metiers ou le bagage chimie ne sert a
rien.

L'ordre de priorite compte aussi
--------------------------------
Une offre dont le titre contient a la fois un terme de specialite et un terme
industriel doit rester dans la SPECIALITE. Un « Technicien de production QC »
est un poste QC, pas un poste de production.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from matching.piste_accessible import (
    ACCESSIBLE_INDUSTRIE,
    ACCESSIBLE_LARGE,
    HORS_PORTEE,
    INDETERMINE,
    LIBELLES,
    ORDRE_LECTURE,
    PISTES_VERSION,
    SPECIALITE,
    classer,
    est_industrie_accessible,
    famille_specialite,
    piste,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# Le moteur de verdict refuse de se prononcer sous 300 caracteres.
BOURRAGE = (" Vous rejoindrez une equipe soudee dans nos installations "
            "belges, avec des horaires reguliers et un contrat a la cle. " * 4)


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def piste_de(titre: str, texte: str = "") -> str:
    return piste(titre, (texte or titre) + BOURRAGE)[0]


def main():
    print("=" * 92)
    print(f"PISTES DE CANDIDATURE V{PISTES_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    print("A. LA SPECIALITE")
    print("-" * 92)
    for titre in ("Technicien QA (H/F/X)",
                  "Technicien de laboratoire QC",
                  "Contrôleur qualité (H/F/X)",
                  "Quality Control Technician",
                  "Data Analyst",
                  "Laborantin"):
        tests.append(check(f"specialite : {titre}",
                           piste_de(titre) == SPECIALITE))

    print()
    print("B. LA PISTE INDUSTRIELLE")
    print("-" * 92)
    for titre in ("Opérateur de production H/F/X",
                  "Ouvrier de production",
                  "Opérateur de machine",
                  "Production Technician",
                  "Procesoperator",
                  "Productiemedewerker",
                  "Opérateur de conditionnement",
                  "Préparateur de commandes"):
        tests.append(check(f"industrie : {titre}",
                           piste_de(titre) == ACCESSIBLE_INDUSTRIE))

    print()
    print("C. LES FAUX POSITIFS RELEVES DANS LA BASE")
    print("-" * 92)
    # Ces deux titres etaient attrapes par « preparateur » employe seul.
    for titre, pourquoi in (
            ("Coach Sportif / Préparateur Physique H/F/X", "sport"),
            ("Préparateur.trice de Projets / Bureau d'Études", "bureau d'études"),
            ("Technicien de surface H/F/X", "agent d'entretien"),
            ("Chauffeur C/Productiemedewerker", "conduite"),
            ("Couturier.ère en atelier", "textile")):
        obtenu = piste_de(titre)
        tests.append(check(
            f"PAS industrie : {titre[:42]} — {pourquoi}",
            obtenu != ACCESSIBLE_INDUSTRIE, obtenu))

    tests.append(check(
        "La fonction d'exclusion repond directement",
        not est_industrie_accessible("Coach Sportif / Préparateur Physique")))

    print()
    print("D. L'ORDRE DE PRIORITE — LA SPECIALITE L'EMPORTE")
    print("-" * 92)
    # Un titre portant les deux vocabulaires reste dans la specialite.
    for titre in ("Technicien de production QC",
                  "Opérateur de production - contrôle qualité",
                  "Production Technician Quality Control"):
        obtenu = piste_de(titre)
        tests.append(check(f"specialite prioritaire : {titre[:44]}",
                           obtenu == SPECIALITE, obtenu))

    print()
    print("E. LES BARRIERES L'EMPORTENT SUR TOUT")
    print("-" * 92)
    # Une offre fermee ne doit jamais apparaitre dans une piste ouverte,
    # meme si son titre est parfaitement dans la cible.
    tests.append(check(
        "Specialite mais master exige : hors de portee",
        piste_de("Technicien QA",
                 "Technicien QA. Vous etes titulaire d'un Master en sciences.")
        == HORS_PORTEE))
    tests.append(check(
        "Industrie mais neerlandais courant exige : hors de portee",
        piste_de("Opérateur de production",
                 "Operateur de production. Vloeiend Nederlands is vereist.")
        == HORS_PORTEE))
    tests.append(check(
        "Industrie avec formation proposée : reste accessible",
        piste_de("Opérateur de production",
                 "Operateur de production. Formation assuree en interne, "
                 "aucune experience requise.") == ACCESSIBLE_INDUSTRIE))

    print()
    print("F. LA PISTE LARGE")
    print("-" * 92)
    # Metier etranger au profil mais sans aucune barriere : accessible,
    # range a part pour ne pas noyer les vraies cibles.
    for titre in ("Employé administratif polyvalent",
                  "Vendeur en magasin",
                  "Agent d'accueil"):
        tests.append(check(f"piste large : {titre}",
                           piste_de(titre) == ACCESSIBLE_LARGE))

    print()
    print("G. TEXTE INSUFFISANT")
    print("-" * 92)
    tests.append(check(
        "Sans description : indetermine, on ne classe pas au hasard",
        piste("Opérateur de production", "trop court")[0] == INDETERMINE))
    tests.append(check("Texte vide accepte sans exception",
                       piste("", "")[0] == INDETERMINE))

    print()
    print("H. LE CLASSEMENT D'ENSEMBLE")
    print("-" * 92)
    lot = [
        ("Technicien QA", "Technicien QA en industrie chimique." + BOURRAGE),
        ("Opérateur de production", "Operateur de production." + BOURRAGE),
        ("Vendeur en magasin", "Vendeur en magasin." + BOURRAGE),
        ("Ingénieur R&D", "Vous etes titulaire d'un Master." + BOURRAGE),
    ]
    resultat = classer(lot)
    tests.append(check("Chaque piste recoit son offre",
                       len(resultat[SPECIALITE]) == 1
                       and len(resultat[ACCESSIBLE_INDUSTRIE]) == 1
                       and len(resultat[ACCESSIBLE_LARGE]) == 1
                       and len(resultat[HORS_PORTEE]) == 1))
    tests.append(check("Aucune offre perdue au classement",
                       sum(len(v) for v in resultat.values()) == len(lot)))
    tests.append(check("La specialite vient en tete de l'ordre de lecture",
                       ORDRE_LECTURE[0] == SPECIALITE))
    tests.append(check("Les offres fermees viennent en dernier",
                       ORDRE_LECTURE[-1] == HORS_PORTEE))
    tests.append(check("Chaque piste porte un libellé lisible",
                       all(p in LIBELLES and len(LIBELLES[p]) > 10
                           for p in ORDRE_LECTURE)))

    print()
    print("I. LA RAISON EST TOUJOURS DONNEE")
    print("-" * 92)
    # Un classement sans motif ne se conteste pas, donc ne se corrige pas.
    for titre, texte in (("Technicien QA", "Technicien QA en chimie."),
                         ("Opérateur de production", "Operateur de production."),
                         ("Ingénieur", "Vous avez un Master en sciences.")):
        _, raison = piste(titre, texte + BOURRAGE)
        tests.append(check(f"raison fournie : {titre[:32]}",
                           bool(raison and len(raison) > 5), raison[:44]))

    tests.append(check("famille_specialite nomme la famille",
                       famille_specialite("Technicien QA") == "quality",
                       famille_specialite("Technicien QA")))
    tests.append(check("famille_specialite reste vide hors profil",
                       famille_specialite("Vendeur en magasin") == ""))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"piste_accessible_v1_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "pistes_version": PISTES_VERSION,
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] PISTES DE CANDIDATURE NON VALIDEES.")
    print("[PASS] PISTES DE CANDIDATURE VALIDEES.")


if __name__ == "__main__":
    main()

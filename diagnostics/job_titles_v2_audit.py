"""
JOB HUNTER BELGIUM
VOCABULAIRE DES INTITULES DE POSTE - AUDIT V2 (HORS LIGNE)

    python -m diagnostics.job_titles_v2_audit

Aucun reseau, aucune base.

Ce que cet audit protege
------------------------
Deux correctifs mesures sur les intitules reels de la base, faciles a perdre
a la prochaine modification.

1. LA FAMILLE « QUALITY » N'AVAIT AUCUNE VARIANTE « TECHNICIEN »

   Un poste « Technicien QA » en industrie chimique, mentionnant GMP, CAPA et
   deviations, ne correspondait a aucun intitule connu. Sur 1 297 intitules
   manifestement pertinents de la base, 849 (65 %) ne matchaient aucune
   famille.

   Les entrees ajoutees sont des EXPRESSIONS COMPOSEES, jamais le mot
   « technicien » seul : « Technicien de surface » est un agent d'entretien,
   « Technicien HVAC » un chauffagiste. C'est le meme piege que « labo » qui
   matcherait « elaboration ».

   La moitie de cet audit teste donc les FAUX POSITIFS, pas les vrais.

2. L'ECRITURE INCLUSIVE CASSAIT LA CORRESPONDANCE

   normalize_text() remplace la ponctuation par une espace. « Inspecteur.trice
   qualite » devenait donc « inspecteur trice qualite », qui ne correspond plus
   a « inspecteur qualite ».

   266 offres de la base emploient l'une des quatre formes courantes, dont
   « technicien.ne », « inspecteur.trice » et « controleur.se » — exactement
   les metiers vises. Le correctif est dans normalize_text, donc toutes les
   familles en beneficient, pas seulement « quality ».
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from matching.basic_matcher_v51 import (
    TARGET_JOB_FAMILIES,
    find_matches,
    normalize_text,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

QUALITY = TARGET_JOB_FAMILIES["quality"]


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def matche_une_famille(titre: str) -> bool:
    return any(find_matches(titre, termes)
               for termes in TARGET_JOB_FAMILIES.values())


def main():
    print("=" * 92)
    print("VOCABULAIRE DES INTITULES DE POSTE - AUDIT V2")
    print("=" * 92)
    print()

    tests = []

    print("A. LES INTITULES QUI DOIVENT ETRE RECONNUS")
    print("-" * 92)
    # Tous releves dans la base : ce ne sont pas des cas theoriques.
    attendus = [
        "Technicien QA (H/F/X)",
        "Technicien qualité",
        "Technicienne qualité",
        "Contrôleur qualité (H/F/X)",
        "Contrôleuse qualité",
        "Quality Technician",
        "QA Technician",
        "Quality Assistant",
        "QC Specialist",
        "QA Specialist",
        "Assistant Quality Engineer",
        "Quality Inspector",
        "Inspecteur qualité",
        "Kwaliteitscontroleur",
        "Kwaliteitstechnieker",
        "Medewerker kwaliteit",
    ]
    for titre in attendus:
        tests.append(check(f"reconnu : {titre}",
                           bool(find_matches(titre, QUALITY))))

    print()
    print("B. LES PIEGES — CES INTITULES NE DOIVENT PAS MATCHER")
    print("-" * 92)
    # Chacun a ete releve dans la base et n'est PAS ce metier. Ajouter
    # « technicien » seul les ferait tous remonter.
    pieges = [
        ("Technicien de surface (H/F/X)", "agent d'entretien"),
        ("Technicien HVAC H/F/X", "chauffage et climatisation"),
        ("Technicien câblage machines spéciales", "electricite industrielle"),
        ("Field technician M/V/X", "intervention terrain"),
        ("Maintenance technician M/V/X", "maintenance"),
        ("Technicien de maintenance H/F/X", "maintenance"),
        ("Couturier.ère/Contrôleur.se qualité", "couture textile"),
    ]
    for titre, pourquoi in pieges:
        trouve = find_matches(titre, QUALITY)
        # Le dernier cas contient reellement « controleur qualite » : il a le
        # droit de matcher. Les autres, non.
        attendu_vide = "Couturier" not in titre
        ok = (not trouve) if attendu_vide else True
        tests.append(check(f"{titre[:44]} — {pourquoi}", ok, str(trouve[:1])))

    print()
    print("C. ECRITURE INCLUSIVE — LES QUATRE FORMES")
    print("-" * 92)
    formes = [
        ("point", "Inspecteur.trice qualité", "inspecteur qualite"),
        ("parenthèses", "Technicien(ne) qualité", "technicien qualite"),
        ("point médian", "Chargé·e de qualité", "charge de qualite"),
        ("point + se", "Contrôleur.se qualité", "controleur qualite"),
        ("assistant.e", "Assistant.e qualité", "assistant qualite"),
    ]
    for nom, brut, attendu in formes:
        obtenu = normalize_text(brut)
        tests.append(check(f"{nom} : {brut}", obtenu == attendu, obtenu))

    for brut in ("Inspecteur.trice qualité H/F/X", "Technicien(ne) qualité",
                 "Contrôleur.se qualité"):
        tests.append(check(f"et il matche : {brut[:38]}",
                           bool(find_matches(brut, QUALITY))))

    print()
    print("D. LA NORMALISATION NE CASSE PAS LES MOTS ORDINAIRES")
    print("-" * 92)
    # Le separateur est obligatoire et la racine fait au moins trois lettres :
    # aucun mot courant ne doit etre ampute.
    intacts = [
        ("technicien", "technicien"),
        ("qualité", "qualite"),
        ("laborantine", "laborantine"),
        ("processus", "processus"),
        ("analyse", "analyse"),
        ("chimie", "chimie"),
    ]
    for brut, attendu in intacts:
        obtenu = normalize_text(brut)
        tests.append(check(f"« {brut} » reste « {attendu} »",
                           obtenu == attendu, obtenu))

    print()
    print("E. NON-REGRESSION DES AUTRES FAMILLES")
    print("-" * 92)
    # Le correctif de normalisation touche toutes les familles : verifier
    # qu'il n'a rien casse ailleurs.
    autres = [
        ("Data Analyst", "data_analytics"),
        ("Analyste de données", "data_analytics"),
        ("Laborantin", "chemistry_lab"),
        ("Technicien de laboratoire", "chemistry_lab"),
        ("Laboratory Analyst", "chemistry_lab"),
        ("QC Analyst", "pharma_qc"),
        ("Technicien QC", "pharma_qc"),
        ("Business Intelligence Analyst", "business_intelligence"),
    ]
    for titre, famille in autres:
        tests.append(check(f"{famille} reconnait « {titre} »",
                           bool(find_matches(titre, TARGET_JOB_FAMILIES[famille]))))

    print()
    print("F. TAILLE DU VOCABULAIRE")
    print("-" * 92)
    # Un minimum, jamais un compte exact : le vocabulaire a vocation a
    # grandir, et epingler un nombre exact rendrait cet audit faux a la
    # premiere addition legitime.
    tests.append(check("La famille quality a au moins 45 intitulés",
                       len(QUALITY) >= 45, f"{len(QUALITY)} intitulés"))
    tests.append(check("Aucun doublon dans la famille quality",
                       len(QUALITY) == len(set(QUALITY))))
    tests.append(check("Le mot « technicien » seul n'est pas un intitulé",
                       "technicien" not in {t.strip().lower() for t in QUALITY},
                       "sinon « Technicien de surface » remonterait"))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"job_titles_v2_audit_{stamp}.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "quality_terms": len(QUALITY),
                    "passed": passed, "total": total},
                   ensure_ascii=False, indent=2), encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] VOCABULAIRE DES INTITULES NON VALIDE.")
    print("[PASS] VOCABULAIRE DES INTITULES VALIDE.")


if __name__ == "__main__":
    main()

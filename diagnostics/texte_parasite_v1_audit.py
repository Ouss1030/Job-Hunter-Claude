"""
JOB HUNTER BELGIUM
DETECTION DES TEXTES PARASITES - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.texte_parasite_v1_audit

Un detecteur qui se trompe efface du vrai texte. L'audit teste donc autant
les faux positifs que les vrais : la moitie des cas ci-dessous sont des
annonces legitimes qui doivent survivre intactes.

Aucun reseau, aucune base.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from diagnostics.version_support import at_least
from matching.texte_parasite import (
    TEXTE_PARASITE_VERSION,
    est_texte_parasite,
    raison_parasite,
)


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


# Reconstitution fidele d'un bloc « offres similaires » Jobat.
BLOC_LISTE = (
    "Senior Data analist Liantis Bruges Duree indeterminee Avantages "
    "extra-legaux Assurance groupe Cheques-repas Depuis 5 jours "
    "Bachelor Elektriciteit APRAGAZ Plusieurs regions Duree indeterminee "
    "Depuis 1 jour "
    "Stralingsbeschermingsagent Equans Plusieurs regions Depuis 3 jours "
    "Technieker Weekend Accent Puurs Sint-Amands Interim option contrat "
    "fixe Depuis 2 jours"
)

FIL_D_ARIANE = ("Offres d'emploi Technique, ingenierie & production › "
                "Technicien de fabrication & de controle › Technicien "
                "(electro)mecanique - Brabant wallon : 28 jobs")

# Vraie annonce, avec UNE mention d'anciennete : elle doit survivre.
VRAIE_ANNONCE = (
    "Technicien de laboratoire en controle qualite. Publiee depuis 3 jours. "
    "Vous realisez les analyses physico-chimiques des matieres premieres et "
    "des produits finis selon les procedures GMP. Vous maitrisez la HPLC et "
    "la chromatographie gazeuse. Vous documentez vos resultats dans le LIMS "
    "et participez aux investigations en cas de hors-specification. Contrat "
    "a duree indeterminee, avantages extra-legaux, cheques-repas."
)


def main():
    print("=" * 92)
    print(f"TEXTES PARASITES V{TEXTE_PARASITE_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    print("A. CE QUI DOIT ETRE REJETE")
    print("-" * 92)
    tests.append(check("Bloc « offres similaires » reconnu",
                       est_texte_parasite(BLOC_LISTE),
                       raison_parasite(BLOC_LISTE)))
    tests.append(check("Fil d'Ariane reconnu",
                       est_texte_parasite(FIL_D_ARIANE),
                       raison_parasite(FIL_D_ARIANE)))
    tests.append(check("Le motif est nomme, pas juste booleen",
                       "BLOC_" in raison_parasite(BLOC_LISTE)))
    tests.append(check("Le motif compte les occurrences trouvees",
                       any(c.isdigit() for c in raison_parasite(BLOC_LISTE)),
                       raison_parasite(BLOC_LISTE)))
    tests.append(check(
        "Trois etiquettes de contrat de liste suffisent",
        est_texte_parasite(
            "Operateur Accent Interim option contrat fixe. "
            "Technicien Accent Interim option contrat fixe. "
            "Magasinier Accent Interim option contrat fixe.")))

    print()
    print("B. CE QUI DOIT SURVIVRE — LES FAUX POSITIFS")
    print("-" * 92)
    tests.append(check("Une vraie annonce n'est pas touchee",
                       not est_texte_parasite(VRAIE_ANNONCE),
                       raison_parasite(VRAIE_ANNONCE) or "propre"))
    tests.append(check(
        "Une seule mention d'anciennete ne suffit pas",
        not est_texte_parasite(
            "Poste publie depuis 2 jours. Vous rejoignez le laboratoire "
            "de controle qualite d'un site pharmaceutique.")))
    tests.append(check(
        "Deux mentions ne suffisent pas non plus",
        not est_texte_parasite(
            "Publiee depuis 2 jours, mise a jour depuis 1 jour. Analyste "
            "en laboratoire, analyses HPLC et documentation LIMS.")))
    # Le signal « Duree indeterminee » a ete ecarte parce qu'il frappait
    # 28 annonces legitimes. Cette regression le prouve.
    tests.append(check(
        "« Duree indeterminee » repete n'est PAS un signal",
        not est_texte_parasite(
            "Contrat a duree indeterminee. Il s'agit bien d'une duree "
            "indeterminee, et non d'un remplacement. La duree indeterminee "
            "est confirmee apres la periode d'essai au laboratoire.")))
    tests.append(check(
        "Une annonce citant « offres d'emploi » sans compte survit",
        not est_texte_parasite(
            "Consultez nos offres d'emploi en laboratoire. Nous recherchons "
            "un technicien QC pour analyses physico-chimiques sur HPLC.")))

    print()
    print("C. ROBUSTESSE")
    print("-" * 92)
    for valeur, etiquette in ((None, "None"), ("", "chaine vide"),
                              ("   \n  ", "espaces seuls")):
        tests.append(check(f"{etiquette} : propre, sans exception",
                           raison_parasite(valeur) == ""))
    tests.append(check("est_texte_parasite renvoie bien un booleen",
                       isinstance(est_texte_parasite(BLOC_LISTE), bool)))
    tests.append(check("Version au moins 1.0",
                       at_least(TEXTE_PARASITE_VERSION, "1.0"),
                       TEXTE_PARASITE_VERSION))

    print()
    print("D. LE GARDE-FOU EST BRANCHE DANS LA CHAINE")
    print("-" * 92)
    import inspect
    import main as pipeline
    source = inspect.getsource(pipeline.apply_detail_description)
    tests.append(check("apply_detail_description consulte le detecteur",
                       "raison_parasite" in source))
    tests.append(check("Le refus marque l'enrichissement en echec",
                       "detail_enrichment_success = False" in source))
    tests.append(check("Le refus nomme la raison",
                       "detail_enrichment_error" in source))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] DETECTION DES TEXTES PARASITES VALIDEE."
              if passed == total
              else "[FAIL] DETECTION DES TEXTES PARASITES NON VALIDEE.")

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"texte_parasite_v1_audit_{stamp}.txt").write_text(
        "\n".join([f"TEXTES PARASITES V{TEXTE_PARASITE_VERSION}",
                   "=" * 92, f"Tests : {passed}/{total}", statut]),
        encoding="utf-8")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

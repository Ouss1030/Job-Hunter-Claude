"""
JOB HUNTER BELGIUM
GARDE-FOU DU VERDICT SUR LE FINAL POOL - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.verdict_gate_v1_audit

Pourquoi ce diagnostic
----------------------
Le score et le verdict repondent a deux questions differentes. Le score dit
« a quel point cette offre vous correspond », le verdict dit « y a-t-il une
barriere prouvee ». Rien n'obligeait les deux a s'accorder, et le 9 septembre
2026 ils ne s'accordaient pas : cinq offres classees FERMEE atteignaient
APPLY_NOW dans le pool reel.

Quatre de ces cinq etaient des erreurs du verdict lui-meme, corrigees en
V1.1 et figees dans verdict_v1_audit. Reste le probleme de structure : rien
n'empechait une offre dont la barriere est prouvee d'etre presentee comme
« a postuler maintenant ».

Ce que la regle fait, et ne fait pas
-----------------------------------
Elle retrograde, elle ne supprime pas. Une offre FERMEE passe en
REVIEW_FIRST avec la phrase de l'annonce qui la ferme, et reste visible.
C'est deliberement doux : un juge qui vient de se tromper cinq fois n'a pas
gagne le droit d'ecarter seul, seulement celui de faire lever les yeux.

Aucun reseau, aucune collecte, aucune base : uniquement recompute_item.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from applications.final_application_pool import (
    FINAL_POOL_VERSION,
    recompute_item,
)
from diagnostics.version_support import at_least
from matching.verdict import ACCESSIBLE, FERMEE


VERDICT_GATE_AUDIT_VERSION = "1.0"

LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"

# Le moteur refuse de se prononcer sous 300 caracteres : les cas doivent
# depasser ce seuil pour etre juges.
BOURRAGE = (" Nous offrons un environnement de travail agreable, une equipe "
            "soudee et de reelles possibilites de developpement. Le poste "
            "est a pourvoir immediatement sur notre site belge. " * 3)


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def offre(titre: str, description: str, action: str = "APPLY_NOW") -> dict:
    """Element de pool minimal, tel que recompute_item le recoit."""
    return {
        "stable_item_key": "ITEM_TEST",
        "title": titre,
        "company": "Societe de test",
        "location": "1000 Bruxelles",
        "url": "https://example.invalid/offre",
        "source": "TEST",
        "cv_track": "LAB_QC",
        "pool_origin": "READY_DOCUMENTS",
        "recheck_status": "READY_DOCUMENTS",
        "queue_score": 120.0,
        "match_score": 100.0,
        "final_score": 120.0,
        "recommended_action": action,
        "warnings": [],
        "reasons": [],
        "description": description + BOURRAGE,
    }


def main():
    print("=" * 92)
    print(f"GARDE-FOU DU VERDICT V{VERDICT_GATE_AUDIT_VERSION} - "
          f"FINAL POOL V{FINAL_POOL_VERSION}")
    print("=" * 92)
    print()

    tests = []

    print("A. LE VERDICT EST CALCULE ET TRANSPORTE")
    print("-" * 92)
    ouverte = recompute_item(offre(
        "Technicien de laboratoire",
        "Vous realisez les analyses de routine en controle qualite au "
        "laboratoire, sur HPLC et GC."))
    tests.append(check("Le champ verdict existe",
                       "verdict" in ouverte, ouverte.get("verdict")))
    tests.append(check("Une offre ouverte reste ACCESSIBLE",
                       ouverte.get("verdict") == ACCESSIBLE))
    tests.append(check("Aucun obstacle affiche sur une offre ouverte",
                       ouverte.get("verdict_obstacle") == ""))
    tests.append(check("La version du moteur est transportee",
                       at_least(str(ouverte.get("verdict_version") or "0"),
                                "1.1"),
                       str(ouverte.get("verdict_version"))))

    print()
    print("B. UNE OFFRE FERMEE N'ATTEINT NI APPLY_NOW NI APPLY_NEXT")
    print("-" * 92)
    for action_initiale in ("APPLY_NOW", "APPLY_NEXT"):
        ferme = recompute_item(offre(
            "Ingenieur systemes",
            "Vous etes titulaire d'un master en informatique de gestion et "
            "maitrisez les architectures distribuees.",
            action=action_initiale))
        tests.append(check(
            f"{action_initiale} : verdict FERMEE reconnu",
            ferme.get("verdict") == FERMEE, ferme.get("verdict_obstacle")))
        tests.append(check(
            f"{action_initiale} -> REVIEW_FIRST",
            ferme.get("recommended_action_v11") == "REVIEW_FIRST",
            str(ferme.get("recommended_action_v11"))))
        tests.append(check(
            f"{action_initiale} : la retrogradation est tracee",
            ferme.get("verdict_gate") == "RETROGRADE_PAR_VERDICT"))
        tests.append(check(
            f"{action_initiale} : la raison est lisible dans reasons",
            any("FERMEE" in str(r) for r in (ferme.get("reasons") or [])),
            str((ferme.get("reasons") or [""])[-1])[:60]))
        tests.append(check(
            f"{action_initiale} : la phrase de l'annonce est conservee",
            bool(ferme.get("verdict_preuve"))))

    print()
    print("C. CE QUE LA REGLE NE FAIT PAS")
    print("-" * 92)
    # Retrograder n'est pas supprimer : l'offre doit rester dans le pool.
    tests.append(check(
        "Une offre FERMEE reste dans le pool, pas ecartee",
        recompute_item(offre(
            "Ingenieur systemes",
            "Vous etes titulaire d'un master en informatique.")
        ).get("recommended_action_v11") != "DO_NOT_APPLY"))

    # La regle ne doit pas relever une offre deja ecartee par le guard.
    deja_ecartee = recompute_item(offre(
        "Technicien de laboratoire",
        "Vous realisez les analyses de routine au laboratoire.",
        action="APPLY_NOW"))
    deja_ecartee_source = dict(deja_ecartee)
    tests.append(check(
        "Une offre ACCESSIBLE n'est jamais retrogradee",
        "verdict_gate" not in deja_ecartee_source,
        str(deja_ecartee_source.get("recommended_action_v11"))))

    # Un stretch reste un stretch : le verdict ne le promeut pas.
    stretch = offre("Analyste QC",
                    "Vous realisez les analyses au laboratoire.")
    stretch["pool_origin"] = "RECHECK_STRETCH"
    tests.append(check(
        "Un RECHECK_STRETCH reste en REVIEW_FIRST",
        recompute_item(stretch).get("recommended_action_v11")
        == "REVIEW_FIRST"))

    print()
    print("D. INDEPENDANCE VIS-A-VIS DU TEXTE")
    print("-" * 92)
    # Un texte trop court donne INCONNU : ne jamais retrograder sur INCONNU,
    # sinon toute offre mal decrite disparaitrait des paniers « postuler ».
    court = recompute_item({**offre("Technicien", "Poste a pourvoir."),
                            "description": "Poste a pourvoir."})
    tests.append(check(
        "Texte insuffisant : INCONNU, aucune retrogradation",
        court.get("verdict") == "INCONNU"
        and court.get("recommended_action_v11") in {"APPLY_NOW", "APPLY_NEXT"},
        f"{court.get('verdict')} / {court.get('recommended_action_v11')}"))

    tests.append(check(
        "Description absente : pas d'exception",
        recompute_item({**offre("Technicien", ""), "description": None}
                       ).get("verdict") == "INCONNU"))

    print()
    print("E. VERSIONS")
    print("-" * 92)
    tests.append(check("Final Pool au moins 1.3",
                       at_least(FINAL_POOL_VERSION, "1.3"),
                       FINAL_POOL_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] GARDE-FOU DU VERDICT VALIDE HORS LIGNE."
              if passed == total
              else "[FAIL] GARDE-FOU DU VERDICT NON VALIDE.")

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"verdict_gate_v1_audit_{stamp}.txt").write_text(
        "\n".join([
            f"GARDE-FOU DU VERDICT V{VERDICT_GATE_AUDIT_VERSION}",
            "=" * 92,
            f"Final Pool : V{FINAL_POOL_VERSION}",
            f"Tests : {passed}/{total}",
            statut,
        ]),
        encoding="utf-8")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

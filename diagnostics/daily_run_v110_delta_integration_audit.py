"""
DAILY RUN V1.1.0 - DELTA INTEGRATION AUDIT

Usage:
    python -m diagnostics.daily_run_v110_delta_integration_audit

Aucun réseau. Aucune collecte. Aucune DB.
"""

import inspect
import fnmatch
from datetime import datetime
from pathlib import Path

import daily_run
from diagnostics.version_support import at_least


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok



def delta_pattern_ok(pattern, extension):
    """
    Le motif doit accepter un vrai artefact horodaté et refuser
    les rapports d'audit qui partagent le même préfixe.
    """
    real_name = f"delta_tracker_v1_20260819_012626.{extension}"
    audit_names = [
        f"delta_tracker_v1_audit_20260819_012626.{extension}",
        f"delta_tracker_v1_current_batch_audit_20260819_012621.{extension}",
    ]
    return (
        bool(pattern)
        and fnmatch.fnmatch(real_name, pattern)
        and all(not fnmatch.fnmatch(name, pattern) for name in audit_names)
    )


def main():
    tests = []

    print("=" * 100)
    print("DAILY RUN V1.1.0 - DELTA INTEGRATION AUDIT")
    print("=" * 100)
    print()

    tests.append(check(
        "Version Daily Run >= 1.1.0",
        at_least(daily_run.DAILY_RUN_VERSION, "1.1.0"),
        daily_run.DAILY_RUN_VERSION,
    ))

    tests.append(check(
        "Delta version attendue 1.1",
        daily_run.EXPECTED_VERSIONS.get(
            "applications.delta_tracker:DELTA_TRACKER_VERSION"
        ) == "1.1",
    ))

    tests.append(check(
        "Ordre Final Pool -> Delta -> Handoff",
        daily_run.STEP_ORDER.index("final_pool")
        < daily_run.STEP_ORDER.index("delta")
        < daily_run.STEP_ORDER.index("handoff"),
        str(daily_run.STEP_ORDER),
    ))

    tests.append(check(
        "Fonction step_delta enregistrée",
        daily_run.STEP_FUNCTIONS.get("delta") is daily_run.step_delta,
    ))

    src_delta = inspect.getsource(daily_run.step_delta)
    tests.append(check(
        "Protection latest Final Pool",
        "require_latest_exact" in src_delta,
    ))
    tests.append(check(
        "Validation current_pool exact",
        "expected_current_pool=final_pool_path" in src_delta,
    ))
    tests.append(check(
        "Validation current_total exact",
        "expected_current_count=pool_validation" in src_delta
        or 'expected_current_count=pool_validation["count"]' in src_delta,
    ))

    src_handoff = inspect.getsource(daily_run.step_handoff)
    tests.append(check(
        "Handoff exige Delta DONE",
        'require_completed(manifest, "delta")' in src_handoff,
    ))

    tests.append(check(
        "Motif Delta JSON comportemental",
        delta_pattern_ok(
            daily_run.ARTIFACT_PATTERNS.get("delta_json"),
            "json",
        ),
        str(daily_run.ARTIFACT_PATTERNS.get("delta_json")),
    ))
    tests.append(check(
        "Motif Delta TXT comportemental",
        delta_pattern_ok(
            daily_run.ARTIFACT_PATTERNS.get("delta_txt"),
            "txt",
        ),
        str(daily_run.ARTIFACT_PATTERNS.get("delta_txt")),
    ))
    tests.append(check(
        "Motif Delta CSV comportemental",
        delta_pattern_ok(
            daily_run.ARTIFACT_PATTERNS.get("delta_csv"),
            "csv",
        ),
        str(daily_run.ARTIFACT_PATTERNS.get("delta_csv")),
    ))

    src_resume = inspect.getsource(daily_run.normalize_manifest_for_resume)
    tests.append(check(
        "Resume V1.0.2 compatible",
        '"1.0.2"' in src_resume,
    ))
    # Test de comportement, pas de forme.
    #
    # Cette verification cherchait la chaine '"delta" not in steps' dans le
    # code source. Elle validait donc une facon d'ecrire la migration, pas
    # son resultat : remplacer les blocs ecrits a la main par une boucle sur
    # STEP_ORDER — strictement meilleur, puisque toute etape future est
    # couverte — faisait echouer l'audit sans qu'aucun comportement ne change.
    #
    # On exerce maintenant la migration pour de vrai.
    manifeste_ancien = {
        "daily_run_version": "1.0.2",
        "run_id": "TEST_MIGRATION",
        "status": "FAILED",
        "resume_count": 0,
        "steps": {
            "main": {"status": "DONE", "artifacts": {}, "validation": {}},
        },
    }
    # normalize_manifest_for_resume() ecrit le manifeste sur disque.
    #
    # Sans neutraliser cette ecriture, l'audit deposait
    # daily_run_v1_TEST_MIGRATION.json dans exports/logs/daily_runs, ou
    # --resume-latest le prenait ensuite pour le manifeste le plus recent
    # et interrompait le run suivant sur un KeyError. Un diagnostic ne doit
    # jamais laisser de trace dans l'etat qu'il observe.
    sauvegarde_reelle = daily_run.save_manifest
    daily_run.save_manifest = lambda *a, **k: None
    try:
        migre = daily_run.normalize_manifest_for_resume(manifeste_ancien)
    except Exception:
        migre = None
    finally:
        daily_run.save_manifest = sauvegarde_reelle

    etapes_migrees = (migre or {}).get("steps", {})
    tests.append(check(
        "La migration ajoute Delta a un manifest qui ne l'a pas",
        "delta" in etapes_migrees
        and etapes_migrees["delta"].get("status") == "PENDING",
        str(sorted(etapes_migrees)[:6]),
    ))
    tests.append(check(
        "La migration ajoute TOUTES les etapes manquantes",
        all(nom in etapes_migrees for nom in daily_run.STEP_ORDER),
        f"{len(etapes_migrees)}/{len(daily_run.STEP_ORDER)} etapes",
    ))
    tests.append(check(
        "Une etape deja DONE n'est pas invalidee",
        etapes_migrees.get("main", {}).get("status") == "DONE",
    ))

    src_summary = inspect.getsource(daily_run.print_final_summary)
    tests.append(check(
        "Résumé final affiche Delta",
        '"Delta Tracker :"' in src_summary,
    ))

    passed = sum(tests)
    total = len(tests)
    status = (
        "✅ DELTA INTEGRATION (>= DAILY RUN V1.1.0) VALIDÉE."
        if all(tests)
        else "❌ DAILY RUN V1.1.0 NON VALIDÉ."
    )

    print()
    print(f"Tests : {passed}/{total}")
    print(status)

    log_dir = Path(__file__).resolve().parents[1] / "exports" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = log_dir / f"daily_run_v110_delta_integration_audit_{stamp}.txt"
    out.write_text(
        "\n".join([
            "DAILY RUN V1.1.0 - DELTA INTEGRATION AUDIT",
            "=" * 100,
            f"Tests : {passed}/{total}",
            status,
        ]),
        encoding="utf-8",
    )
    print("TXT audit :", out)

    if not all(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

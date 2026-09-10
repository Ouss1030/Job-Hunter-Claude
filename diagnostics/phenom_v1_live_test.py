"""
JOB HUNTER BELGIUM
CONNECTEUR PHENOM - TEST LIVE

    python -m diagnostics.phenom_v1_live_test

⚠️ Ce script appelle l'API publique Phenom. Il est classé en catégorie
RÉSEAU dans diagnostics/run_all.py et n'est donc jamais lancé par défaut.

Aucune écriture en base. Aucune candidature marquée.
"""

from __future__ import annotations

import collections
import json
from datetime import datetime
from pathlib import Path

from config.phenom_sources import enabled_companies
from sources.phenom_ats_v1 import collect_phenom_jobs


LOG_DIR = Path(__file__).resolve().parent.parent / "exports" / "logs"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def main():
    print("=" * 92)
    print("CONNECTEUR PHENOM - TEST LIVE")
    print("=" * 92)

    resultat = collect_phenom_jobs(verbose=True)
    jobs = resultat["jobs"]
    rapport = resultat["report"]

    print()
    tests = []

    tests.append(check(
        "Au moins un employeur répond",
        any(r["sitemap_urls"] > 0 for r in rapport),
        f"{sum(r['sitemap_urls'] for r in rapport)} URL au sitemap",
    ))
    tests.append(check(
        "Aucune erreur fatale",
        not any(r["error"] for r in rapport),
        "; ".join(f"{r['label']}: {r['error']}" for r in rapport if r["error"]),
    ))
    tests.append(check(
        "Aucun échec de conversion",
        sum(r["failures"] for r in rapport) == 0,
        f"{sum(r['failures'] for r in rapport)} échec(s)",
    ))

    statuts = collections.Counter(getattr(j, "belgium_status", "?") for j in jobs)
    tests.append(check(
        "Aucune offre hors Belgique retenue",
        "BE_EXCLUDED" not in statuts,
        str(dict(statuts)),
    ))
    tests.append(check(
        "Toutes les offres ont une URL publique",
        all(str(j.url).startswith("http") for j in jobs),
    ))
    # Phenom n'expose pas de champ corporate séparé (contrairement à
    # SmartRecruiters) : on vérifie plutôt que le HTML doublement échappé
    # a bien été nettoyé, sinon le Matcher scorerait des balises.
    tests.append(check(
        "Aucune balise ni entité HTML dans le texte de matching",
        all("<p>" not in (j.description or "") and "&lt;" not in (j.description or "")
            for j in jobs),
    ))
    # Le signal qui compte pour un connecteur HTML : un taux d'échec élevé
    # trahit un changement de gabarit, pas un simple aléa réseau.
    alertes = [r for r in rapport if r.get("jsonld_warning")]
    tests.append(check(
        "Aucune alerte JSON-LD manquant",
        not alertes,
        ", ".join(r["label"] for r in alertes) or "aucune",
    ))
    tests.append(check(
        "Descriptions substantielles",
        all(len(j.description) >= 300 for j in jobs),
    ))

    configures = {c["host"] for c in enabled_companies()}
    repondus = {r["host"] for r in rapport if not r["error"]}
    tests.append(check(
        "Tous les employeurs configurés sont joignables",
        configures == repondus,
        f"injoignables : {sorted(configures - repondus) or 'aucun'}",
    ))

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}   |   offres retenues : {len(jobs)}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"phenom_v1_live_test_{stamp}.json").write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "passed": passed,
            "total": total,
            "jobs_retained": len(jobs),
            "report": rapport,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8")

    if passed != total:
        raise SystemExit("[FAIL] TEST LIVE PHENOM NON VALIDÉ.")

    print("[PASS] TEST LIVE PHENOM VALIDÉ.")


if __name__ == "__main__":
    main()

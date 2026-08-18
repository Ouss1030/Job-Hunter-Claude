"""
Diagnostic Application Preparation V1.

Usage :
    python -m diagnostics.application_preparation_v1_audit

Le diagnostic :
1. teste les règles synthétiques ;
2. charge le dernier application_queue_v1_*.json ;
3. prépare les 20 meilleurs READY_APPLY sans relancer main.py ;
4. écrit automatiquement un TXT d'audit dans exports/logs/.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from applications.application_preparation import (
    DEFAULT_BATCH_LIMIT,
    PREPARATION_VERSION,
    build_application_preparation,
    load_current_queue,
    preparation_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def qitem(rank, title, company, location, status="READY_APPLY", score=120, match=95, cv="LAB_QC", group=None):
    return {
        "queue_version": "1.1",
        "queue_rank": rank,
        "canonical_job_id": rank,
        "title": title,
        "company": company,
        "location": location,
        "url": f"https://example.test/{rank}",
        "source": "FOREM",
        "origin_source": "FOREM",
        "match_score": match,
        "best_family": "data_analytics" if cv == "DATA" else "chemistry_lab",
        "gate": {"status": "APPLY", "reasons": []},
        "gate_status": "APPLY",
        "queue_status": status,
        "queue_score": score,
        "preferred_location": "Bruxelles" in location,
        "location_anchor": "bruxelles-capitale" if "Bruxelles" in location else "liege",
        "cv_track": cv,
        "cv_track_label": "CV Data / BI" if cv == "DATA" else "CV Lab / QC",
        "stable_item_key": f"ITEM_TEST_{rank}",
        "application_group_id": group or f"GROUP_TEST_{rank}",
        "duplicate_of_item_key": None,
        "possible_duplicate_item_keys": [],
    }


def run_synthetic_tests():
    payload = [
        qitem(1, "Technicien laboratoire", "Pharma A", "Bruxelles, Belgique", score=139, cv="LAB_QC"),
        qitem(2, "Data Analyst", "Data A", "Bruxelles, Belgique", score=135, cv="DATA"),
        qitem(3, "Laborantin", "Lab B", "Liège, Belgique", score=127, cv="LAB_QC"),
        qitem(4, "Doublon secondaire", "Pharma A", "Bruxelles, Belgique", score=130, cv="LAB_QC", group="GROUP_TEST_1"),
        qitem(5, "Stretch", "Other", "Bruxelles, Belgique", status="READY_STRETCH", score=150, cv="DATA"),
        qitem(6, "Hold", "Other", "Bruxelles, Belgique", status="HOLD_DUPLICATE", score=145, cv="LAB_QC"),
    ]

    prepared = build_application_preparation(payload, limit=20)
    tests = []

    def check(name, condition, detail=""):
        tests.append((name, bool(condition), detail))

    check("Seulement READY_APPLY", all(x["stable_item_key"] not in {"ITEM_TEST_5", "ITEM_TEST_6"} for x in prepared), str(len(prepared)))
    check("Un seul item par application_group_id", len(prepared) == 3, str(len(prepared)))
    check("Ordre Queue respecté", prepared[0]["stable_item_key"] == "ITEM_TEST_1", prepared[0]["stable_item_key"])
    check("CV LAB_QC conservé", prepared[0]["cv_track"] == "LAB_QC", prepared[0]["cv_track"])
    check("CV DATA conservé", prepared[1]["cv_track"] == "DATA", prepared[1]["cv_track"])
    check("Priorité A+ Bruxelles", prepared[0]["priority_band"] == "A+", prepared[0]["priority_band"])
    check("Description exigée avant génération", all(not x["safe_to_generate_documents"] for x in prepared), "safe=False")
    check("Statut attente description", all(x["document_generation_status"] == "WAITING_JOB_DESCRIPTION" for x in prepared), prepared[0]["document_generation_status"])
    check("Noms CV prévus", all(x["output_files"]["cv_docx"].endswith("_CV.docx") for x in prepared), prepared[0]["output_files"]["cv_docx"])
    check("Dossier stable prévu", all("ITEM_TEST_" in x["application_folder"] for x in prepared), prepared[0]["application_folder"])

    return tests


def main():
    lines = []
    lines.append("APPLICATION PREPARATION V1 - DIAGNOSTIC")
    lines.append("=" * 76)
    lines.append(f"Version : {PREPARATION_VERSION}")
    lines.append("")

    tests = run_synthetic_tests()
    passed = 0
    for name, ok, detail in tests:
        if ok:
            passed += 1
            lines.append(f"✅ {name}: {detail}")
        else:
            lines.append(f"❌ {name}: {detail}")

    lines.append("")
    lines.append(f"Tests synthétiques : {passed}/{len(tests)}")

    try:
        current = load_current_queue(PROJECT_ROOT)
    except FileNotFoundError:
        current = None

    if current is None:
        lines.append("")
        lines.append("⚠️ Aucun Gate/Queue JSON réel trouvé dans exports/logs/.")
    else:
        prepared = build_application_preparation(current["items"], limit=DEFAULT_BATCH_LIMIT)
        summary = preparation_summary(prepared)

        lines.append("")
        lines.append("AUDIT DE LA QUEUE COURANTE")
        lines.append("=" * 76)
        lines.append(f"Source              : {current['source_type']}")
        lines.append(f"Fichier             : {current['source_path']}")
        lines.append(f"Queue utilisée      : {current['queue_version']}")
        lines.append(f"Lot préparé         : {summary['total']}")
        lines.append(f"Priorité A+         : {summary['priority_A_plus']}")
        lines.append(f"Priorité A          : {summary['priority_A']}")
        lines.append(f"Zone prioritaire    : {summary['preferred_location']}")
        lines.append(f"CV DATA             : {summary['cv_data']}")
        lines.append(f"CV LAB_QC           : {summary['cv_lab_qc']}")
        lines.append(f"CV HYBRID           : {summary['cv_hybrid']}")
        lines.append(f"CV de base trouvé   : {summary['base_cv_found']}/{summary['total']}")
        lines.append(f"Attente description : {summary['waiting_job_description']}/{summary['total']}")
        lines.append("")
        lines.append("TOP 10 À PRÉPARER")
        lines.append("-" * 76)
        for item in prepared[:10]:
            star = "⭐" if item.get("preferred_location") else " "
            lines.append(
                f"{item['batch_position']:>2}. {star} [{item['priority_band']}] "
                f"Q{item['queue_score']:>5.1f} | {item['cv_track']:<6} | "
                f"{item['title']} | {item['location']}"
            )

    lines.append("")
    if passed == len(tests):
        lines.append("✅ APPLICATION PREPARATION V1 VALIDÉE SUR LE DIAGNOSTIC.")
    else:
        lines.append("❌ APPLICATION PREPARATION V1 NON VALIDÉE.")

    text = "\n".join(lines)
    print(text)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = LOG_DIR / f"application_preparation_v1_audit_{timestamp}.txt"
    out.write_text(text, encoding="utf-8")
    print()
    print("TXT automatique :", out)


if __name__ == "__main__":
    main()

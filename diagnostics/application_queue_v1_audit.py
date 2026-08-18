"""
Diagnostic Application Queue V1.1.

Usage :
    python -m diagnostics.application_queue_v1_audit

Le script :
1. exécute des tests synthétiques ;
2. cherche automatiquement le dernier exports/logs/application_gate_v1_*.json ;
3. construit une Queue sur ce JSON sans relancer la collecte ;
4. écrit un TXT d'audit automatique dans exports/logs/.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from matching.application_queue import (
    QUEUE_VERSION,
    build_application_queue_from_gate_payload,
    queue_summary,
    source_reference_from_url,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


def gate(status, priority=90.0, family="chemistry_lab"):
    return {
        "status": status,
        "priority_score": priority,
        "family": family,
        "reasons": [],
        "warnings": [],
        "hard_reasons": [],
    }


def rec(rank, title, company, location, url, status="APPLY", score=90.0, family="chemistry_lab", priority=90.0):
    return {
        "rank": rank,
        "canonical_job_id": rank,
        "title": title,
        "company": company,
        "location": location,
        "url": url,
        "source": "ACTIRIS" if "actiris" in url else "FOREM",
        "origin_source": "ACTIRIS",
        "match_score": score,
        "best_family": family,
        "gate": gate(status, priority=priority, family=family),
    }


def find_item(items, title):
    for item in items:
        if item["title"] == title:
            return item
    raise AssertionError(f"Introuvable: {title}")


def run_synthetic_tests():
    payload = [
        rec(
            1,
            "Technicien Chimiste Laboratoire (H/F/X)",
            "Example Pharma",
            "Bruxelles, 1000, Belgique",
            "https://www.leforem.be/recherche-offres/offre-detail/1111111",
            score=100,
            family="chemistry_lab",
            priority=115,
        ),
        rec(
            2,
            "Business Data Analyst H/F/X",
            "Example Data",
            "Saint-Gilles, 1060, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=2222222&type=Hrxml",
            score=92,
            family="data_analytics",
            priority=107,
        ),
        rec(
            3,
            "Data Engineer H/F/X",
            "Example Tech",
            "Bruxelles, 1000, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=3333333&type=Hrxml",
            status="STRETCH",
            score=88,
            family="data_engineering",
            priority=80,
        ),
        rec(
            4,
            "Student laborant M/V/X",
            "Example Student",
            "Geel, 2440, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=4444444&type=Hrxml",
            status="VERIFY",
            score=70,
            family="chemistry_lab",
            priority=65,
        ),
        rec(
            5,
            "Senior Data Analyst H/F/X",
            "Example Reject",
            "Bruxelles, 1000, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=5555555&type=Hrxml",
            status="REJECT",
            score=55,
            family="data_analytics",
            priority=20,
        ),
        # Doublon fort cross-source volontaire.
        rec(
            6,
            "AQUA VITAL - Technicien contrôle qualité microbiologique (H/F/X)",
            "BETUNED - BETUNED",
            "WAVRE, Province du Brabant Wallon, Belgique",
            "https://www.leforem.be/recherche-offres/offre-detail/6666666",
            score=88,
            family="quality",
            priority=102,
        ),
        rec(
            7,
            "AQUA VITAL - Technicien contrôle qualité microbiologique M/V/X",
            "BETUNED",
            "Wavre, 1300, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=7777777&type=Hrxml",
            score=87,
            family="quality",
            priority=101,
        ),
        # Même titre/entreprise mais autre ville : ne doit pas être HOLD.
        rec(
            8,
            "Laborant M/V/X",
            "RANDSTAD BELGIUM",
            "Ardooie, 8850, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=8888888&type=Hrxml",
            score=90,
            family="chemistry_lab",
            priority=105,
        ),
        rec(
            9,
            "Laborant M/V/X",
            "RANDSTAD BELGIUM",
            "Turnhout, 2300, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=9999999&type=Hrxml",
            score=89,
            family="chemistry_lab",
            priority=104,
        ),
        # V1.1 : Bruxelles-ville et Ixelles doivent être le même bassin
        # pour une offre au titre/entreprise identiques.
        rec(
            10,
            "Technicien Chimiste Laboratoire - Bruxelles H/F/X",
            "MICHAEL PAGE INTERNATIONAL (BELGIUM)",
            "BRUXELLES, Belgique, RÉGION DE BRUXELLES-CAPITALE",
            "https://www.leforem.be/recherche-offres/offre-detail/1010101",
            score=100,
            family="chemistry_lab",
            priority=115,
        ),
        rec(
            11,
            "Technicien Chimiste Laboratoire - Bruxelles H/F/X",
            "MICHAEL PAGE INTERNATIONAL (BELGIUM)",
            "Ixelles, 1050, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=1111112&type=Hrxml",
            score=100,
            family="chemistry_lab",
            priority=115,
        ),
        # V1.1 : préfixe de marque dans le titre ne doit pas masquer un doublon.
        rec(
            12,
            "BI Analyst-Developer H/F/X",
            "SMALS - MVM",
            "Saint-Gilles, 1060, Belgique",
            "https://www.actiris.brussels/fr/citoyens/detail-offre-d-emploi/?reference=1212121&type=Hrxml",
            score=96,
            family="business_intelligence",
            priority=111,
        ),
        rec(
            13,
            "Smals - BI Analyst - Developer H/F/X",
            "SMALS - MVM",
            "1060, Belgique",
            "https://www.leforem.be/recherche-offres/offre-detail/1313131",
            score=95,
            family="business_intelligence",
            priority=110,
        ),
    ]

    items = build_application_queue_from_gate_payload(payload)
    tests = []

    def check(name, condition, detail=""):
        ok = bool(condition)
        tests.append((name, ok, detail))
        return ok

    lab = find_item(items, "Technicien Chimiste Laboratoire (H/F/X)")
    data = find_item(items, "Business Data Analyst H/F/X")
    de = find_item(items, "Data Engineer H/F/X")
    student = find_item(items, "Student laborant M/V/X")
    senior = find_item(items, "Senior Data Analyst H/F/X")
    aqua_f = find_item(items, "AQUA VITAL - Technicien contrôle qualité microbiologique (H/F/X)")
    aqua_a = find_item(items, "AQUA VITAL - Technicien contrôle qualité microbiologique M/V/X")
    ardooie = [x for x in items if x["location"].startswith("Ardooie")][0]
    turnhout = [x for x in items if x["location"].startswith("Turnhout")][0]
    michael = [
        x for x in items
        if x["company"] == "MICHAEL PAGE INTERNATIONAL (BELGIUM)"
    ]
    smals = [
        x for x in items
        if x["company"] == "SMALS - MVM"
        and "BI Analyst" in x["title"]
    ]

    check("LAB APPLY -> READY_APPLY", lab["queue_status"] == "READY_APPLY", lab["queue_status"])
    check("LAB -> CV Lab/QC", lab["cv_track"] == "LAB_QC", lab["cv_track"])
    check("Bruxelles -> zone prioritaire", lab["preferred_location"], str(lab["preferred_location"]))
    check("Data -> CV DATA", data["cv_track"] == "DATA", data["cv_track"])
    check("Data Engineer STRETCH reste STRETCH", de["queue_status"] == "READY_STRETCH", de["queue_status"])
    check("VERIFY -> VERIFY_FIRST", student["queue_status"] == "VERIFY_FIRST", student["queue_status"])
    check("REJECT -> EXCLUDED", senior["queue_status"] == "EXCLUDED", senior["queue_status"])
    check(
        "Aqua cross-source -> un HOLD_DUPLICATE",
        sorted([aqua_f["queue_status"], aqua_a["queue_status"]]).count("HOLD_DUPLICATE") == 1,
        f"{aqua_f['queue_status']} / {aqua_a['queue_status']}",
    )
    check(
        "Doublon HOLD pointe vers un primaire",
        bool(aqua_f["duplicate_of_item_key"] or aqua_a["duplicate_of_item_key"]),
        str(aqua_f["duplicate_of_item_key"] or aqua_a["duplicate_of_item_key"]),
    )
    check(
        "Même emploi autre ville non HOLD",
        ardooie["queue_status"] != "HOLD_DUPLICATE" and turnhout["queue_status"] != "HOLD_DUPLICATE",
        f"{ardooie['queue_status']} / {turnhout['queue_status']}",
    )
    check(
        "Stable key Forem",
        source_reference_from_url(lab["url"]) == "FOREM:1111111",
        source_reference_from_url(lab["url"]),
    )
    check(
        "Stable key Actiris",
        source_reference_from_url(data["url"]) == "ACTIRIS:2222222:Hrxml",
        source_reference_from_url(data["url"]),
    )
    check(
        "Boost localisation visible",
        lab["queue_score"] > 115,
        str(lab["queue_score"]),
    )
    check(
        "Bruxelles + Ixelles même offre -> un HOLD",
        sum(1 for x in michael if x["queue_status"] == "HOLD_DUPLICATE") == 1,
        " / ".join(x["queue_status"] for x in michael),
    )
    check(
        "Préfixe entreprise dans titre SMALS -> un HOLD",
        sum(1 for x in smals if x["queue_status"] == "HOLD_DUPLICATE") == 1,
        " / ".join(x["queue_status"] for x in smals),
    )
    postcode_1060 = [x for x in smals if x["location"].startswith("1060")][0]
    check(
        "Code postal Bruxelles seul -> zone prioritaire",
        postcode_1060["preferred_location"],
        str(postcode_1060["preferred_location"]),
    )

    return tests, items


def latest_gate_json():
    files = sorted(LOG_DIR.glob("application_gate_v1_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


def audit_real_gate():
    path = latest_gate_json()
    if not path:
        return None, None, None

    payload = json.loads(path.read_text(encoding="utf-8"))
    items = build_application_queue_from_gate_payload(payload)
    return path, items, queue_summary(items)


def main():
    tests, _ = run_synthetic_tests()
    passed = sum(1 for _, ok, _ in tests if ok)

    lines = []
    lines.append("APPLICATION QUEUE V1.1 - DIAGNOSTIC")
    lines.append("=" * 76)
    lines.append(f"Version : {QUEUE_VERSION}")
    lines.append("")

    for name, ok, detail in tests:
        status = "✅" if ok else "❌"
        lines.append(f"{status} {name}: {detail}")

    lines.append("")
    lines.append(f"Tests synthétiques : {passed}/{len(tests)}")

    gate_path, real_items, summary = audit_real_gate()
    if gate_path:
        lines.append("")
        lines.append("AUDIT DU DERNIER GATE JSON")
        lines.append("=" * 76)
        lines.append(f"Gate JSON        : {gate_path}")
        lines.append(f"Total            : {summary['total']}")
        lines.append(f"READY_APPLY      : {summary['READY_APPLY']}")
        lines.append(f"READY_STRETCH    : {summary['READY_STRETCH']}")
        lines.append(f"VERIFY_FIRST     : {summary['VERIFY_FIRST']}")
        lines.append(f"HOLD_DUPLICATE   : {summary['HOLD_DUPLICATE']}")
        lines.append(f"EXCLUDED         : {summary['EXCLUDED']}")
        lines.append(f"APPLY zone prior.: {summary['preferred_ready_apply']}")
        lines.append(f"APPLY CV DATA    : {summary['data_ready_apply']}")
        lines.append(f"APPLY CV LAB_QC  : {summary['lab_qc_ready_apply']}")
        lines.append(f"APPLY CV HYBRID  : {summary['hybrid_ready_apply']}")
        lines.append("")
        lines.append("TOP 15 READY_APPLY")
        lines.append("-" * 76)
        ready = [x for x in real_items if x["queue_status"] == "READY_APPLY"]
        for idx, item in enumerate(ready[:15], start=1):
            star = "⭐" if item["preferred_location"] else " "
            lines.append(
                f"{idx:>2}. {star} Q{item['queue_score']:>6.1f} | M{item['match_score']:>5.1f} | "
                f"{item['cv_track']:<6} | {item['title']} | {item['location']}"
            )
    else:
        lines.append("")
        lines.append("Aucun application_gate_v1_*.json trouvé : audit réel ignoré.")

    lines.append("")
    if passed == len(tests):
        lines.append("✅ APPLICATION QUEUE V1.1 VALIDÉE SUR LE DIAGNOSTIC.")
    else:
        lines.append("❌ APPLICATION QUEUE V1.1 À CORRIGER AVANT INTÉGRATION.")

    text = "\n".join(lines)
    print(text)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = LOG_DIR / f"application_queue_v1_audit_{timestamp}.txt"
    out.write_text(text, encoding="utf-8")
    print()
    print("TXT audit automatique :", out)

    if passed != len(tests):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

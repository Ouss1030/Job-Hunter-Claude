"""
Diagnostic synthétique Funnel Recall Audit V1.
Aucun accès DB requis.

Usage :
    python -m diagnostics.funnel_recall_v1_audit
"""

from dataclasses import dataclass

from config.funnel_recall import WATCH_BUCKETS
from diagnostics.funnel_recall_audit import (
    matched_buckets,
    production_context,
    recall_risk,
    stage_for_record,
)


@dataclass
class FakeJob:
    title: str
    company: str = ""
    description: str = ""


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f": {detail}" if detail else ""))
    return ok


def main():
    tests = []

    j = FakeJob("Laborantin QC")
    b = matched_buckets(j)
    tests.append(check("Laborantin -> LAB_CORE", "LAB_CORE" in b, str(b)))
    tests.append(check("Laborantin QC -> QC_QUALITY", "QC_QUALITY" in b, str(b)))

    j = FakeJob("Technicien Chimiste de Laboratoire")
    b = matched_buckets(j)
    tests.append(check("Technicien Chimiste -> CHEMISTRY", "CHEMISTRY" in b, str(b)))

    j = FakeJob(
        "Technicien de production",
        description="Production pharmaceutique sous GMP et contrôle qualité",
    )
    b = matched_buckets(j)
    tests.append(check(
        "Technicien production -> PRODUCTION_ADJACENT",
        "PRODUCTION_ADJACENT" in b,
        str(b),
    ))
    tests.append(check(
        "Production pharma -> contexte scientifique",
        production_context(j) is True,
    ))
    tests.append(check(
        "Production pharma rejetée -> HIGH recall",
        recall_risk(b, False, production_context(j)) == "HIGH",
    ))

    j = FakeJob("Production Operator", description="entrepôt logistique général")
    b = matched_buckets(j)
    tests.append(check(
        "Production générique sans contexte -> pas HIGH",
        recall_risk(b, False, production_context(j)) != "HIGH",
    ))

    j = FakeJob("BI Analyst Developer")
    b = matched_buckets(j)
    tests.append(check("BI Analyst -> DATA_BI", "DATA_BI" in b, str(b)))

    j = FakeJob("Validation Scientist", description="Analyses HPLC UPLC")
    b = matched_buckets(j)
    tests.append(check(
        "HPLC en description -> ANALYTICAL_INSTRUMENTS",
        "ANALYTICAL_INSTRUMENTS" in b,
        str(b),
    ))

    tests.append(check(
        "Sans Gate et core false -> PRESELECT_REJECTED",
        stage_for_record("ACTIRIS", False, None, None, None)
        == "PRESELECT_REJECTED",
    ))

    tests.append(check(
        "Sans Gate mais core true -> PRESELECTED_NOT_GATED",
        stage_for_record("FOREM", True, None, None, None)
        == "PRESELECTED_NOT_GATED",
    ))

    queue = {"queue_status": "READY_APPLY"}
    tests.append(check(
        "Queue READY -> stage exact",
        stage_for_record("ACTIRIS", True, 1, {"gate": {"status": "APPLY"}}, queue)
        == "QUEUE_READY_APPLY",
    ))

    print()
    print(f"Tests synthétiques : {sum(tests)}/{len(tests)}")
    if all(tests):
        print("✅ FUNNEL RECALL AUDIT V1 VALIDÉ SUR LE DIAGNOSTIC.")
    else:
        raise SystemExit("❌ FUNNEL RECALL AUDIT V1 NON VALIDÉ.")


if __name__ == "__main__":
    main()

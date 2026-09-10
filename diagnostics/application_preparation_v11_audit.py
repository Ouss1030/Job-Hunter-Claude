"""
APPLICATION PREPARATION V1.1 - AUDIT OFFLINE

Usage:
python -m diagnostics.application_preparation_v11_audit
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import applications.application_preparation_v11 as prep
from diagnostics.version_support import at_least


def check(label, condition, detail=""):
    ok = bool(condition)
    print(f"{'✅' if ok else '❌'} {label}" + (f" | {detail}" if detail else ""))
    return ok


def fake_gate(version):
    return [{
        "rank": 1,
        "canonical_job_id": 1,
        "title": "QC Laborant",
        "company": "TEST",
        "location": "Beveren-Kruibeke-Zwijndrecht, Belgique",
        "url": "https://example.test/job",
        "source": "FOREM",
        "origin_source": "FOREM",
        "match_score": 90.0,
        "best_family": "chemistry_lab",
        "confidence": "Élevée",
        "gate": {
            "gate_version": version,
            "status": "APPLY",
            "status_label": "APPLY",
            "priority_score": 105.0,
            "match_score": 90.0,
            "family": "chemistry_lab",
            "reasons": [],
            "warnings": [],
            "hard_reasons": [],
            "source_eligibility_status": "ELIGIBLE",
            "source_eligibility_reason": None,
            "provisional": False,
        },
    }]


def main():
    tests = []

    print("=" * 88)
    print("APPLICATION PREPARATION V1.1 - AUDIT OFFLINE")
    print("=" * 88)
    print()

    tests.append(check(
        "Prep version 1.1",
        at_least(prep.PREPARATION_VERSION, "1.1"),
        prep.PREPARATION_VERSION,
    ))
    tests.append(check(
        "Queue version 1.2",
        prep.QUEUE_VERSION == "1.2",
        prep.QUEUE_VERSION,
    ))
    tests.append(check(
        "Gate version 1.3.2",
        prep.GATE_VERSION == "1.3.2",
        prep.GATE_VERSION,
    ))

    # Vérifie le bug concret Beveren/Evere via le builder réellement importé.
    q = prep.build_application_queue_from_gate_payload(
        fake_gate(prep.GATE_VERSION)
    )
    tests.append(check(
        "Beveren non prioritaire",
        q[0].get("preferred_location") is False,
        str(q[0].get("preferred_location")),
    ))
    tests.append(check(
        "Queue stamp 1.2",
        q[0].get("queue_version") == "1.2",
        str(q[0].get("queue_version")),
    ))

    # Validation du garde-fou stale Gate.
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        logs = root / "exports" / "logs"
        logs.mkdir(parents=True)

        stale = logs / "application_gate_v1_20260818_000000.json"
        stale.write_text(
            json.dumps(fake_gate("1.3.1"), ensure_ascii=False),
            encoding="utf-8",
        )

        blocked = False
        try:
            prep.load_current_queue(project_root=root)
        except RuntimeError as exc:
            blocked = "Gate export obsolète" in str(exc)

        tests.append(check(
            "Gate 1.3.1 bloqué si 1.3.2 installé",
            blocked,
        ))

        current = logs / "application_gate_v1_20260818_000001.json"
        current.write_text(
            json.dumps(fake_gate(prep.GATE_VERSION), ensure_ascii=False),
            encoding="utf-8",
        )

        loaded = prep.load_current_queue(project_root=root)
        tests.append(check(
            "Gate courant accepté",
            loaded["gate_version"] == prep.GATE_VERSION,
            loaded["gate_version"],
        ))
        tests.append(check(
            "Rebuild utilise Queue 1.2",
            loaded["queue_version"] == "1.2",
            loaded["queue_version"],
        ))
        tests.append(check(
            "Rebuild garde Beveren non prioritaire",
            loaded["items"][0]["preferred_location"] is False,
        ))

    print()
    print(f"Tests : {sum(tests)}/{len(tests)}")

    if not all(tests):
        raise SystemExit("❌ APPLICATION PREPARATION V1.1 NON VALIDÉE.")

    print("✅ APPLICATION PREPARATION V1.1 VALIDÉE OFFLINE.")


if __name__ == "__main__":
    main()

"""
APPLICATION QUEUE V1.2 - DIAGNOSTIC + REPLAY SANS RECOLLECTE

Usage:
    python -m diagnostics.application_queue_v12_audit
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from matching.application_queue_v12 import (
    QUEUE_VERSION,
    build_application_queue_from_gate_payload,
    location_is_preferred,
    queue_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


LOCATION_TESTS = [
    ("EVERE", "Evere, 1140, Belgique", True),
    ("BEVEREN", "Beveren-Kruibeke-Zwijndrecht, Vlaanderen, Belgique", False),
    ("BEVEREN WAAS", "BEVEREN-WAAS, Belgique", False),
    ("WOLUWE", "Woluwe-Saint-Lambert, 1200, Belgique", True),
    ("DROGENBOS", "Drogenbos, Belgique", True),
    ("BRUXELLES", "Bruxelles, 1000, Belgique", True),
]


def latest_gate_json():
    paths = sorted(
        LOG_DIR.glob("application_gate_v1_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    return paths[0] if paths else None


def main():
    lines = []
    lines.append("APPLICATION QUEUE V1.2 - DIAGNOSTIC")
    lines.append("=" * 84)
    lines.append(f"Version : {QUEUE_VERSION}")
    lines.append("")

    passed = 0

    for name, location, expected in LOCATION_TESTS:
        obtained = location_is_preferred(location)
        ok = obtained == expected
        passed += int(ok)
        lines.append(
            f"{'✅' if ok else '❌'} {name:<16} "
            f"attendu={expected!s:<5} obtenu={obtained!s:<5} | {location}"
        )

    lines.append("")
    lines.append(f"Tests localisation : {passed}/{len(LOCATION_TESTS)}")

    gate_path = latest_gate_json()
    if gate_path:
        payload = json.loads(gate_path.read_text(encoding="utf-8"))
        items = build_application_queue_from_gate_payload(payload)
        summary = queue_summary(items)

        beveren_preferred = [
            item for item in items
            if item.get("preferred_location")
            and "beveren" in (item.get("location") or "").lower()
        ]

        lines.append("")
        lines.append("REPLAY DU DERNIER GATE - AUCUNE RECOLLECTE")
        lines.append("=" * 84)
        lines.append(f"Gate JSON        : {gate_path}")
        lines.append(f"Total            : {summary['total']}")
        lines.append(f"READY_APPLY      : {summary['READY_APPLY']}")
        lines.append(f"READY_STRETCH    : {summary['READY_STRETCH']}")
        lines.append(f"VERIFY_FIRST     : {summary['VERIFY_FIRST']}")
        lines.append(f"HOLD_DUPLICATE   : {summary['HOLD_DUPLICATE']}")
        lines.append(f"EXCLUDED         : {summary['EXCLUDED']}")
        lines.append(f"APPLY zone prior.: {summary['preferred_ready_apply']}")
        lines.append(f"Beveren prior.   : {len(beveren_preferred)}")

        if beveren_preferred:
            lines.append("")
            lines.append("❌ Beveren est encore marqué prioritaire :")
            for item in beveren_preferred[:10]:
                lines.append(
                    f" - {item.get('title')} | {item.get('location')}"
                )
        else:
            lines.append("")
            lines.append("✅ Aucun Beveren n'est marqué comme Evere / zone prioritaire.")

        out_json = (
            LOG_DIR
            / f"application_queue_v12_replay_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        )
        out_json.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        lines.append(f"JSON replay       : {out_json}")
    else:
        lines.append("")
        lines.append("⚠️ Aucun application_gate_v1_*.json trouvé.")

    lines.append("")
    if passed == len(LOCATION_TESTS):
        lines.append("✅ APPLICATION QUEUE V1.2 VALIDÉE SUR LES TESTS DE LOCALISATION.")
    else:
        lines.append("❌ APPLICATION QUEUE V1.2 NON VALIDÉE.")

    text = "\n".join(lines)
    print(text)

    out = (
        LOG_DIR
        / f"application_queue_v12_audit_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    )
    out.write_text(text, encoding="utf-8")
    print()
    print("TXT audit automatique :", out)

    if passed != len(LOCATION_TESTS):
        raise SystemExit(1)


if __name__ == "__main__":
    main()

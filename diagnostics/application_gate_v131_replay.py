"""
APPLICATION GATE V1.3.1 - REPLAY SANS RECOLLECTE

But
===
Corriger le faux positif V.I.E du shadow V1.3 en réutilisant les exports
déjà générés. AUCUN appel réseau, AUCUNE recollecte Forem/Actiris.

Le script cherche automatiquement :
- le dernier export Gate V1.2 ;
- le dernier export Gate V1.3-shadow.

Puis :
- conserve les vrais V.I.E explicites ;
- retire les faux V.I.E issus du mot français "vie" ;
- conserve les rejets Master et Real Estate V1.3 ;
- reconstruit la Queue avec le module Queue actuel.

Usage :
    python -m diagnostics.application_gate_v131_replay

Options :
    --base-v12 PATH
    --shadow-v13 PATH
"""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from matching.application_queue import (
    build_application_queue_from_gate_payload,
    partition_application_queue,
    queue_summary,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)


VIE_REASON_PREFIX = "Offre V.I.E"


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def payload_gate_version(payload):
    versions = Counter()
    for row in payload[:100]:
        version = str((row.get("gate") or {}).get("gate_version") or "")
        if version:
            versions[version] += 1
    return versions.most_common(1)[0][0] if versions else ""


def find_latest_gate(version_prefix):
    candidates = sorted(
        LOG_DIR.glob("application_gate_v1_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for path in candidates:
        try:
            payload = load_json(path)
            if not isinstance(payload, list) or not payload:
                continue
            version = payload_gate_version(payload)
            if version.startswith(version_prefix):
                return path
        except Exception:
            continue

    return None


def explicit_vie_title(title):
    raw = str(title or "").strip()
    lower = raw.lower()

    if re.search(
        r"\bV\s*\.\s*I\s*\.\s*E\s*\.?(?=\s|$|\W)",
        raw,
        flags=re.IGNORECASE,
    ):
        return True

    if re.search(
        r"\bV\s*-\s*I\s*-\s*E\b",
        raw,
        flags=re.IGNORECASE,
    ):
        return True

    if re.search(r"\bVIE\b", raw):
        return True

    if re.search(r"\bvie\s+(?:programme|program)\b", lower):
        return True

    return False


def record_key(row):
    return (
        str(row.get("source") or ""),
        str(row.get("url") or ""),
    )


def correct_payload(base_v12, shadow_v13):
    base_index = {
        record_key(row): row
        for row in base_v12
    }

    if set(base_index) != {record_key(row) for row in shadow_v13}:
        raise RuntimeError(
            "Les exports V1.2 et V1.3 ne contiennent pas exactement "
            "le même ensemble d'offres. Utilise les deux exports du même shadow test."
        )

    corrected = []
    stats = Counter()

    for shadow_row in shadow_v13:
        row = copy.deepcopy(shadow_row)
        key = record_key(row)
        gate = row.get("gate") or {}
        overlay = gate.get("v13_overlay") or {}

        vie_flag = bool(overlay.get("vie_ineligible"))
        true_vie = explicit_vie_title(row.get("title"))

        if vie_flag and not true_vie:
            stats["false_vie_removed"] += 1

            has_other_v13_reason = bool(
                overlay.get("real_estate_domain_mismatch")
                or overlay.get("structured_master_requirement")
            )

            if not has_other_v13_reason:
                # Le seul motif nouveau était le faux V.I.E :
                # retour EXACT à la décision Gate V1.2.
                restored = copy.deepcopy(base_index[key]["gate"])
                restored["gate_version"] = "1.3.1-replay"
                restored["v13_overlay"] = {
                    "real_estate_domain_mismatch": None,
                    "vie_ineligible": None,
                    "structured_master_requirement": False,
                }
                row["gate"] = restored
                stats["restored_from_v12"] += 1
            else:
                # Master/Real Estate reste un vrai hard reject.
                gate["hard_reasons"] = [
                    reason
                    for reason in (gate.get("hard_reasons") or [])
                    if not str(reason).startswith(VIE_REASON_PREFIX)
                ]
                overlay["vie_ineligible"] = None
                gate["v13_overlay"] = overlay
                gate["gate_version"] = "1.3.1-replay"
                row["gate"] = gate
                stats["kept_reject_other_v13_reason"] += 1

        else:
            gate["gate_version"] = "1.3.1-replay"
            row["gate"] = gate

            if vie_flag and true_vie:
                stats["true_vie_kept"] += 1

        corrected.append(row)

    return corrected, stats


def gate_summary(payload):
    counts = Counter(
        (row.get("gate") or {}).get("status")
        for row in payload
    )
    return {
        "total": len(payload),
        "APPLY": counts.get("APPLY", 0),
        "STRETCH": counts.get("STRETCH", 0),
        "VERIFY": counts.get("VERIFY", 0),
        "REJECT": counts.get("REJECT", 0),
    }


def source_breakdown_gate(payload, source):
    counts = Counter(
        (row.get("gate") or {}).get("status")
        for row in payload
        if str(row.get("source") or "").upper() == source.upper()
    )
    return dict(counts)


def source_breakdown_queue(payload, source):
    counts = Counter(
        row.get("queue_status")
        for row in payload
        if str(row.get("source") or "").upper() == source.upper()
    )
    return dict(counts)


def find_record(payload, title):
    title_lower = title.lower()
    for row in payload:
        if str(row.get("title") or "").lower() == title_lower:
            return row
    return None


def export_replay(corrected_gate, queue, stats, base_path, shadow_path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    gate_json = LOG_DIR / f"application_gate_v131_replay_{stamp}.json"
    gate_txt = LOG_DIR / f"application_gate_v131_replay_{stamp}.txt"
    queue_json = LOG_DIR / f"application_queue_v131_replay_{stamp}.json"
    queue_txt = LOG_DIR / f"application_queue_v131_replay_{stamp}.txt"

    gate_json.write_text(
        json.dumps(corrected_gate, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    queue_json.write_text(
        json.dumps(queue, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    gs = gate_summary(corrected_gate)
    qs = queue_summary(queue)
    sr_g = source_breakdown_gate(corrected_gate, "SMARTRECRUITERS")
    sr_q = source_breakdown_queue(queue, "SMARTRECRUITERS")

    targets = [
        "Real Estate Portfolio Manager",
        "Performance Analyst - V.I.E Programme",
        "Scientist biochimie",
        "Scientist",
        "Laborant",
        "QC Laborant",
        "Lab Technician Environmental Monitoring",
        "Laborant Biopharma Product Testing",
        "Analyste - Chemistry Mono",
    ]

    lines = [
        "APPLICATION GATE V1.3.1 - REPLAY SANS RECOLLECTE",
        "=" * 96,
        f"Base V1.2   : {base_path}",
        f"Shadow V1.3 : {shadow_path}",
        "",
        f"Faux V.I.E retirés               : {stats.get('false_vie_removed', 0)}",
        f"Restaurés exactement depuis V1.2 : {stats.get('restored_from_v12', 0)}",
        f"Vrais V.I.E conservés             : {stats.get('true_vie_kept', 0)}",
        f"REJECT maintenu via Master/RE     : {stats.get('kept_reject_other_v13_reason', 0)}",
        "",
        "GATE CORRIGÉ",
        f"Total   : {gs['total']}",
        f"APPLY   : {gs['APPLY']}",
        f"STRETCH : {gs['STRETCH']}",
        f"VERIFY  : {gs['VERIFY']}",
        f"REJECT  : {gs['REJECT']}",
        "",
        "QUEUE CORRIGÉE",
        f"READY_APPLY    : {qs['READY_APPLY']}",
        f"READY_STRETCH  : {qs['READY_STRETCH']}",
        f"VERIFY_FIRST   : {qs['VERIFY_FIRST']}",
        f"HOLD_DUPLICATE : {qs['HOLD_DUPLICATE']}",
        f"EXCLUDED       : {qs['EXCLUDED']}",
        "",
        f"SMARTRECRUITERS GATE  : {sr_g}",
        f"SMARTRECRUITERS QUEUE : {sr_q}",
        "",
        "POSTES DE CONTRÔLE",
        "-" * 96,
    ]

    for title in targets:
        row = find_record(corrected_gate, title)
        if not row:
            lines.append(f"ABSENT | {title}")
            continue
        gate = row.get("gate") or {}
        lines.append(
            f"{gate.get('status','?'):<7} | "
            f"{row.get('source',''):<16} | "
            f"{row.get('company',''):<20} | "
            f"{row.get('title','')}"
        )
        for reason in gate.get("hard_reasons") or []:
            lines.append(f"         ↳ {reason}")

    gate_txt.write_text("\n".join(lines), encoding="utf-8")

    qlines = [
        "APPLICATION QUEUE V1.3.1 - REPLAY SANS RECOLLECTE",
        "=" * 96,
        f"Total              : {qs['total']}",
        f"READY_APPLY        : {qs['READY_APPLY']}",
        f"READY_STRETCH      : {qs['READY_STRETCH']}",
        f"VERIFY_FIRST       : {qs['VERIFY_FIRST']}",
        f"HOLD_DUPLICATE     : {qs['HOLD_DUPLICATE']}",
        f"EXCLUDED           : {qs['EXCLUDED']}",
        "",
        "SMARTRECRUITERS READY_APPLY",
        "-" * 96,
    ]

    for item in queue:
        if (
            str(item.get("source") or "").upper() == "SMARTRECRUITERS"
            and item.get("queue_status") == "READY_APPLY"
        ):
            qlines.append(
                f"{item.get('queue_rank', 0):>3}. "
                f"{float(item.get('queue_score') or 0):>6.1f} | "
                f"{item.get('company','')} | {item.get('title','')}"
            )

    queue_txt.write_text("\n".join(qlines), encoding="utf-8")

    return gate_json, gate_txt, queue_json, queue_txt, gs, qs, sr_g, sr_q


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-v12", default=None)
    parser.add_argument("--shadow-v13", default=None)
    args = parser.parse_args()

    base_path = (
        Path(args.base_v12)
        if args.base_v12
        else find_latest_gate("1.2")
    )
    shadow_path = (
        Path(args.shadow_v13)
        if args.shadow_v13
        else find_latest_gate("1.3-shadow")
    )

    if not base_path:
        raise SystemExit("❌ Aucun export Gate V1.2 trouvé.")
    if not shadow_path:
        raise SystemExit("❌ Aucun export Gate V1.3-shadow trouvé.")

    print("Base V1.2   :", base_path)
    print("Shadow V1.3 :", shadow_path)
    print()

    base = load_json(base_path)
    shadow = load_json(shadow_path)

    corrected, stats = correct_payload(base, shadow)
    queue = build_application_queue_from_gate_payload(corrected)

    (
        gate_json,
        gate_txt,
        queue_json,
        queue_txt,
        gs,
        qs,
        sr_g,
        sr_q,
    ) = export_replay(
        corrected,
        queue,
        stats,
        base_path,
        shadow_path,
    )

    print("=" * 84)
    print("GATE V1.3.1 - REPLAY TERMINÉ")
    print("=" * 84)
    print("Faux V.I.E retirés :", stats.get("false_vie_removed", 0))
    print("Vrais V.I.E gardés :", stats.get("true_vie_kept", 0))
    print()
    print(
        "Gate :",
        f"APPLY={gs['APPLY']}",
        f"STRETCH={gs['STRETCH']}",
        f"VERIFY={gs['VERIFY']}",
        f"REJECT={gs['REJECT']}",
    )
    print(
        "Queue:",
        f"READY_APPLY={qs['READY_APPLY']}",
        f"READY_STRETCH={qs['READY_STRETCH']}",
        f"VERIFY_FIRST={qs['VERIFY_FIRST']}",
        f"HOLD_DUPLICATE={qs['HOLD_DUPLICATE']}",
        f"EXCLUDED={qs['EXCLUDED']}",
    )
    print()
    print("SmartRecruiters Gate :", sr_g)
    print("SmartRecruiters Queue:", sr_q)
    print()
    print("TXT Gate  :", gate_txt)
    print("JSON Gate :", gate_json)
    print("TXT Queue :", queue_txt)
    print("JSON Queue:", queue_json)


if __name__ == "__main__":
    main()

"""
DAILY RUN V1.0 - CURRENT INSTALLATION PREFLIGHT

Usage:
    python -m diagnostics.daily_run_v1_current_installation_audit

Aucun réseau.
Aucune collecte.
Aucune écriture DB.
"""

from datetime import datetime
import json
import daily_run


def main():
    result = daily_run.run_preflight()
    daily_run.print_preflight(result)

    print()
    print("=" * 100)
    print("ARTEFACTS ACTUELS (INFORMATIF)")
    print("=" * 100)

    artifacts = {}
    for name, pattern in daily_run.ARTIFACT_PATTERNS.items():
        path = daily_run.latest_path(daily_run.LOG_DIR, pattern)
        artifacts[name] = str(path) if path else None
        print(f"{name:<20}: {path}")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = daily_run.LOG_DIR / (
        f"daily_run_v1_current_installation_audit_{stamp}.json"
    )
    txt_path = daily_run.LOG_DIR / (
        f"daily_run_v1_current_installation_audit_{stamp}.txt"
    )

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "preflight": result,
        "artifacts": artifacts,
    }

    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "DAILY RUN V1.0 - CURRENT INSTALLATION AUDIT",
        "=" * 100,
        f"OK : {result['ok']}",
        "",
        "VERSIONS",
        "-" * 100,
    ]
    for spec, expected in result["expected_versions"].items():
        actual = result["installed_versions"].get(spec)
        lines.append(f"{spec}: {actual} (attendu {expected})")

    lines.extend(["", "ARTEFACTS", "-" * 100])
    for name, value in artifacts.items():
        lines.append(f"{name}: {value}")

    if result["errors"]:
        lines.extend(["", "ERRORS", "-" * 100])
        lines.extend(result["errors"])

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    print()
    print("JSON audit :", json_path)
    print("TXT audit  :", txt_path)

    if not result["ok"]:
        raise SystemExit(
            "❌ INSTALLATION ACTUELLE NON COMPATIBLE DAILY RUN V1.0."
        )

    print()
    print("✅ INSTALLATION ACTUELLE COMPATIBLE AVEC DAILY RUN V1.0.")


if __name__ == "__main__":
    main()

"""
APPLICATION GATE V1.3.3 - REPLAY SANS RECOLLECTE

Rejoue le Gate sur les offres d'un export de production et compare
la version en place (V1.3.2) à la version candidate (V1.3.3).

Aucun appel réseau. Base ouverte en lecture seule (mode=ro).

Usage :
    python -m diagnostics.application_gate_v133_replay
    python -m diagnostics.application_gate_v133_replay --export CHEMIN --db CHEMIN

Note méthodologique
-------------------
Les offres sont reconstruites depuis raw_jobs. Les deux versions sont
évaluées sur EXACTEMENT le même objet reconstruit, donc un éventuel écart
de reconstruction affecte les deux côtés de façon identique : la
différence V1.3.2 / V1.3.3 reste interprétable même si la reconstruction
n'est pas parfaitement identique à ce que main.py avait fourni.

Sortie :
    exports/logs/application_gate_v133_replay_*.txt
    exports/logs/application_gate_v133_replay_*.json
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from matching.application_gate_v13 import (
    evaluate_application_gate as evaluate_v132,
)
from matching.application_gate_v133 import (
    evaluate_application_gate as evaluate_v133,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
ORDRE = ["APPLY", "STRETCH", "VERIFY", "REJECT"]


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--export", default=None,
                   help="export application_gate_v1_*.json de référence")
    p.add_argument("--db", default=None, help="chemin de jobs.db")
    return p.parse_args()


def latest_export(explicit):
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"❌ Export introuvable : {path}")
        return path

    exports = sorted(LOG_DIR.glob("application_gate_v1_*.json"))
    if not exports:
        raise SystemExit(
            "❌ Aucun export application_gate_v1_*.json dans exports/logs.\n"
            "   Utilise --export pour en désigner un."
        )
    return exports[-1]


def load_rows(db_path, urls):
    if not db_path.exists():
        raise SystemExit(f"❌ Base introuvable : {db_path}")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row

    found = {}
    for i in range(0, len(urls), 400):
        part = urls[i:i + 400]
        query = ("SELECT * FROM raw_jobs WHERE url IN (%s)"
                 % ",".join("?" * len(part)))
        for row in con.execute(query, part):
            found.setdefault(row["url"], dict(row))

    con.close()
    return found


def build_job(row):
    job = SimpleNamespace(**row)
    if not hasattr(job, "restriction"):
        job.restriction = row.get("restriction_text")
    return job


def build_match(entry):
    return {
        "score": float(entry.get("match_score") or 0),
        "best_family": entry.get("best_family"),
        "provisional": False,
        "confidence_label": entry.get("confidence") or "Élevée",
    }


def main():
    args = parse_args()
    export_path = latest_export(args.export)
    db_path = Path(args.db) if args.db else (PROJECT_ROOT / "database" / "jobs.db")

    entries = json.loads(export_path.read_text(encoding="utf-8"))

    print("=" * 84)
    print("APPLICATION GATE V1.3.3 - REPLAY SANS RECOLLECTE")
    print("=" * 84)
    print()
    print("Export de référence :", export_path.name)
    print("Base (lecture seule):", db_path)
    print("Offres dans l'export:", len(entries))
    print()

    rows = load_rows(db_path, [e["url"] for e in entries])

    couples = []
    for entry in entries:
        row = rows.get(entry["url"])
        if row is not None:
            couples.append((entry, build_job(row), build_match(entry)))

    absentes = len(entries) - len(couples)
    print(f"Offres reconstruites : {len(couples)}"
          + (f"   ({absentes} non retrouvées en base)" if absentes else ""))
    print()

    avant, apres, changements = Counter(), Counter(), []

    for entry, job, match_result in couples:
        g2 = evaluate_v132(job, match_result)
        g3 = evaluate_v133(job, match_result)

        avant[g2["status"]] += 1
        apres[g3["status"]] += 1

        if g2["status"] != g3["status"]:
            changements.append({
                "title": entry.get("title"),
                "company": entry.get("company"),
                "source": entry.get("source"),
                "url": entry.get("url"),
                "match_score": entry.get("match_score"),
                "avant": g2["status"],
                "apres": g3["status"],
                "hard_reasons_avant": g2.get("hard_reasons") or [],
                "hard_reasons_apres": g3.get("hard_reasons") or [],
            })

    print("-" * 84)
    print("COMPARAISON GATE")
    print("-" * 84)
    print(f"{'STATUT':<10} {'V1.3.2':>8} {'V1.3.3':>8} {'DELTA':>8}")
    for statut in ORDRE:
        a, b = avant.get(statut, 0), apres.get(statut, 0)
        print(f"{statut:<10} {a:>8} {b:>8} {b - a:>+8}")
    print()

    recuperees = [c for c in changements if c["avant"] == "REJECT"]
    durcies = [c for c in changements if c["apres"] == "REJECT"]
    autres = [c for c in changements
              if c["avant"] != "REJECT" and c["apres"] != "REJECT"]

    print("-" * 84)
    print(f"OFFRES DONT LE STATUT CHANGE : {len(changements)}")
    print("-" * 84)

    if recuperees:
        print()
        print(f"RÉCUPÉRÉES (REJECT -> autre) : {len(recuperees)}")
        for c in sorted(recuperees, key=lambda x: -(x["match_score"] or 0)):
            print(f"  {c['match_score']:>5.1f} | REJECT -> {c['apres']:<8} "
                  f"| {(c['title'] or '')[:50]}")
            for r in c["hard_reasons_avant"]:
                print(f"          motif levé : {r[:86]}")

    if durcies:
        print()
        print(f"DURCIES (-> REJECT) : {len(durcies)}")
        for c in sorted(durcies, key=lambda x: -(x["match_score"] or 0)):
            print(f"  {c['match_score']:>5.1f} | {c['avant']} -> REJECT   "
                  f"| {(c['title'] or '')[:50]}")
            for r in c["hard_reasons_apres"]:
                print(f"          nouveau motif : {r[:86]}")

    if autres:
        print()
        print(f"AUTRES MOUVEMENTS : {len(autres)}")
        for c in autres:
            print(f"  {c['match_score']:>5.1f} | {c['avant']} -> {c['apres']:<8} "
                  f"| {(c['title'] or '')[:50]}")

    if not changements:
        print("Aucun changement de statut.")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "reference_export": export_path.name,
        "offers_replayed": len(couples),
        "offers_missing": absentes,
        "gate_v132": {s: avant.get(s, 0) for s in ORDRE},
        "gate_v133": {s: apres.get(s, 0) for s in ORDRE},
        "recovered": len(recuperees),
        "hardened": len(durcies),
        "changed": changements,
    }

    json_path = LOG_DIR / f"application_gate_v133_replay_{stamp}.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                         encoding="utf-8")

    lignes = [
        "APPLICATION GATE V1.3.3 - REPLAY SANS RECOLLECTE",
        f"Généré le           : {payload['generated_at']}",
        f"Export de référence : {export_path.name}",
        f"Offres rejouées     : {len(couples)}",
        "",
        f"{'STATUT':<10} {'V1.3.2':>8} {'V1.3.3':>8} {'DELTA':>8}",
    ]
    for statut in ORDRE:
        a, b = avant.get(statut, 0), apres.get(statut, 0)
        lignes.append(f"{statut:<10} {a:>8} {b:>8} {b - a:>+8}")
    lignes += ["", f"Statuts modifiés : {len(changements)}",
               f"  récupérées : {len(recuperees)}",
               f"  durcies    : {len(durcies)}", ""]
    for c in changements:
        lignes.append(f"{c['match_score']:>5.1f} | {c['avant']} -> {c['apres']:<8} "
                      f"| {c['source']} | {c['title']}")
        for r in c["hard_reasons_avant"]:
            lignes.append(f"        avant : {r}")
        for r in c["hard_reasons_apres"]:
            lignes.append(f"        après : {r}")
        lignes.append(f"        {c['url']}")
        lignes.append("")

    txt_path = LOG_DIR / f"application_gate_v133_replay_{stamp}.txt"
    txt_path.write_text("\n".join(lignes), encoding="utf-8")

    print()
    print("=" * 84)
    print("Fichiers écrits :")
    print("  ", txt_path)
    print("  ", json_path)
    print("=" * 84)


if __name__ == "__main__":
    main()

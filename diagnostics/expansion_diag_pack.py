"""
JOB HUNTER BELGIUM
PAQUET DE DIAGNOSTIC - EXPANSION DES SOURCES - OUTIL V1.0

    python -m diagnostics.expansion_diag_pack

Rassemble dans un ZIP pret a transmettre :

    REPORT.txt              etat des sources, lisible
    DIAGNOSTIC.json         compteurs (specs, base, registre, decouverte)
    SOURCE_RESULTS.jsonl    dernier resultat de decouverte, ligne par candidat
    SOURCE_COVERAGE_MATRIX.csv
    CONFIG_SNAPSHOT.json    reglages d'absorption, employeurs decouverts,
                            signatures ATS, sources actives
    RUN_METADATA.json       dernier run complet en base
    ERRORS.log              erreurs de validation/decouverte

Sortie : exports/logs/EXPANSION_DIAG_<horodatage>.zip. Ne modifie rien.
"""

from __future__ import annotations

import glob
import json
import sqlite3
import zipfile
from collections import Counter
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "exports" / "logs"


def _lire_json(p: Path, defaut=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return defaut


def main() -> Path:
    from sources.registry import SOURCE_SPECS, load_source_settings
    from sources.ats_employers_v2 import charger, resume
    from sources.registry_absorption_v1 import charger_reglages

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dossier = LOG_DIR / f"EXPANSION_DIAG_{stamp}"
    dossier.mkdir(parents=True, exist_ok=True)

    settings = load_source_settings()
    actives = [s.key for s in SOURCE_SPECS if settings.get(s.key, s.enabled_default)]

    run_meta = {}
    par_source = {}
    db = ROOT / "database" / "jobs.db"
    if db.exists():
        c = sqlite3.connect(db)
        r = c.execute("select run_id, started_at, finished_at, status, total_collected, inserted_count, error_count "
                      "from collection_runs where status='COMPLETED' order by run_id desc limit 1").fetchone()
        if r:
            run_meta = dict(zip(("run_id", "started_at", "finished_at", "status", "total_collected", "inserted_count", "error_count"), r))
            for src, n, act in c.execute("select source, count(*), sum(is_active) from raw_jobs group by source"):
                par_source[src] = {"total": n, "actives": act or 0}
        run_meta["raw_jobs"] = c.execute("select count(*) from raw_jobs").fetchone()[0]
        run_meta["raw_jobs_actives"] = c.execute("select sum(is_active) from raw_jobs").fetchone()[0]

    dossiers_decouverte = sorted(glob.glob(str(LOG_DIR / "discovery_*" / "DIAGNOSTIC.json")))
    dernier_diag = _lire_json(Path(dossiers_decouverte[-1]), {}) if dossiers_decouverte else {}
    resultats = Path(dossiers_decouverte[-1]).parent / "SOURCE_RESULTS.jsonl" if dossiers_decouverte else None

    erreurs = []
    if resultats and resultats.exists():
        # split("\n") et non splitlines() : un JSON peut contenir U+2028, que
        # splitlines() prend pour une fin de ligne.
        for l in resultats.read_text(encoding="utf-8").split("\n"):
            try:
                d = json.loads(l)
            except Exception:
                continue
            v = d.get("validation") or {}
            if d.get("erreur") or v.get("erreur"):
                erreurs.append(f"{d.get('label')} | {d.get('statut')} | {d.get('erreur') or v.get('erreur')}")

    registre = charger()
    diag = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "specs_total": len(SOURCE_SPECS), "specs_actives": len(actives),
        "absorption": charger_reglages(),
        "registre_employeurs": resume(),
        "derniere_decouverte": dernier_diag,
        "base": {"dernier_run": run_meta, "sources_en_base": len(par_source),
                 "top_sources": dict(Counter({k: v["actives"] for k, v in par_source.items()}).most_common(15))},
        "erreurs": len(erreurs),
    }
    (dossier / "DIAGNOSTIC.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (dossier / "RUN_METADATA.json").write_text(json.dumps(run_meta, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (dossier / "CONFIG_SNAPSHOT.json").write_text(json.dumps({
        "absorption_settings": charger_reglages(),
        "sources_actives": actives,
        "ats_employers_v2": registre,
        "ats_signatures": [k for k in (_lire_json(ROOT / "config" / "ats_signatures.json", {}).get("ats") or {})],
    }, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    (dossier / "ERRORS.log").write_text("\n".join(erreurs), encoding="utf-8")
    if resultats and resultats.exists():
        (dossier / "SOURCE_RESULTS.jsonl").write_bytes(resultats.read_bytes())
    matrice = ROOT / "SOURCE_COVERAGE_MATRIX.csv"
    if matrice.exists():
        (dossier / "SOURCE_COVERAGE_MATRIX.csv").write_bytes(matrice.read_bytes())

    lignes = [f"EXPANSION DES SOURCES — DIAGNOSTIC {diag['generated_at']}", "",
              f"Sources declarees : {diag['specs_total']}   actives : {diag['specs_actives']}",
              f"Absorption complete : {diag['absorption']}",
              f"Registre employeurs decouverts : {diag['registre_employeurs']}",
              f"Derniere decouverte : {dernier_diag.get('candidats')} candidats, {dernier_diag.get('enregistres')} enregistres, "
              f"{dernier_diag.get('offres_be_validees')} offres BE validees",
              f"  par statut : {dernier_diag.get('par_statut')}",
              f"  par ATS    : {dernier_diag.get('par_ats')}",
              f"Base : {run_meta.get('raw_jobs')} offres brutes, {run_meta.get('raw_jobs_actives')} actives ; dernier run complet {run_meta.get('run_id')}",
              "", "Top sources en base (actives) :"]
    for k, v in diag["base"]["top_sources"].items():
        lignes.append(f"  {k:<24} {v}")
    lignes += ["", f"Erreurs de validation/decouverte : {len(erreurs)} (voir ERRORS.log)"]
    (dossier / "REPORT.txt").write_text("\n".join(lignes), encoding="utf-8")

    zip_path = LOG_DIR / f"EXPANSION_DIAG_{stamp}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for f in dossier.iterdir():
            z.write(f, f.name)
    print("\n".join(lignes))
    print()
    print(f"ZIP : {zip_path}")
    return zip_path


if __name__ == "__main__":
    main()

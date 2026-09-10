"""
CHATGPT HANDOFF - VERSION 1.0

But
---
Exporter les candidatures finales validées vers des paquets compacts à
envoyer manuellement à ChatGPT Plus.

Aucun appel OpenAI API.
Aucun réseau.
Aucune écriture DB.

Usage principal
---------------
python -m applications.chatgpt_handoff

Par défaut :
- prend le dernier final_application_pool_v12_*.json ;
- exporte APPLY_NOW ;
- crée un ZIP complet ;
- crée des ZIP par lots de 10 offres.

Options
-------
python -m applications.chatgpt_handoff --actions APPLY_NOW
python -m applications.chatgpt_handoff --actions APPLY_NOW APPLY_NEXT
python -m applications.chatgpt_handoff --limit 10
python -m applications.chatgpt_handoff --start 1 --limit 10
python -m applications.chatgpt_handoff --chunk-size 5
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path


HANDOFF_VERSION = "1.0"

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "exports" / "logs"
EXPORT_ROOT = ROOT / "exports" / "chatgpt_handoff"

DEFAULT_ACTIONS = ["APPLY_NOW"]
DEFAULT_CHUNK_SIZE = 10

BASE_CV_PREFERENCE = "CV_Oussama_Aharroud_LabQC.docx"

from config.candidate_truth import (
    DEFAULT_BASE_CV_NAME,
    FORBIDDEN_CANDIDATE_CLAIM_TERMS,
    HARD_TRUTH_RULES,
    build_handoff_candidate_truth,
)

CANDIDATE_TRUTH = build_handoff_candidate_truth()


APPLICATION_INSTRUCTIONS = [
    "Utiliser en priorité le CV LabQC comme base pour LAB_QC / QUALITY / PRODUCTION_SCIENCE.",
    "Pour DATA, adapter fortement le CV vers SQL/Python/Power BI/ETL sans inventer d'expérience professionnelle Data.",
    "Corriger toute ancienne mention 'Business Data Analysis — en cours' : diplôme terminé en juin 2026.",
    "CV professionnel, ATS-friendly, crédible et humain.",
    "Lettre de motivation spécifique au poste, sans flatterie excessive.",
    "Ne jamais inventer de compétence, diplôme, niveau de langue ou durée d'expérience.",
    "Respecter strictement les candidate_truth et les guard_flags/warnings.",
    "Si l'annonce contient une exigence incompatible découverte lors de la rédaction, la signaler avant de générer les documents.",
]


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value, max_len=72):
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].rstrip("-") or "job")


def latest_file(pattern):
    paths = list(LOG_DIR.glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_items(payload, actions, start=1, limit=None):
    pool = list(payload.get("pool") or [])
    wanted = {str(x).upper() for x in actions}

    selected = [
        item
        for item in pool
        if str(
            item.get("recommended_action_v12")
            or item.get("recommended_action")
            or ""
        ).upper() in wanted
    ]

    selected.sort(
        key=lambda x: (
            int(x.get("pool_rank_v12") or 999999),
            -float(x.get("final_score_v12") or 0),
        )
    )

    start_index = max(0, int(start) - 1)
    selected = selected[start_index:]

    if limit is not None:
        selected = selected[: max(0, int(limit))]

    return selected


def compact_job(item):
    return {
        "handoff_version": HANDOFF_VERSION,
        "stable_item_key": item.get("stable_item_key"),
        "pool_rank": item.get("pool_rank_v12"),
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "source": item.get("source"),
        "origin_source": item.get("origin_source"),
        "url": item.get("url"),
        "track": item.get("track"),
        "priority": item.get("priority_v12"),
        "final_score": item.get("final_score_v12"),
        "recommended_action": item.get("recommended_action_v12"),
        "preferred_location": bool(item.get("preferred_location")),
        "recheck_status": item.get("recheck_status"),
        "recheck_version": item.get("recheck_version"),
        "warnings": list(item.get("warnings") or []),
        "guard_level": item.get("guard_level"),
        "guard_flags": list(item.get("guard_flags") or []),
        "reasons": list(item.get("reasons") or []),
        "live_description": clean_text(item.get("description")),
        "application_folder": item.get("application_folder"),
        "planned_output_files": item.get("output_files") or {},
        "base_cv_preference": BASE_CV_PREFERENCE,
        "candidate_truth": CANDIDATE_TRUTH,
        "application_instructions": APPLICATION_INSTRUCTIONS,
    }


def prompt_text(job):
    warnings = job.get("warnings") or []
    guards = job.get("guard_flags") or []

    caution_lines = []
    for value in warnings:
        caution_lines.append(f"- Recheck : {value}")
    for value in guards:
        caution_lines.append(f"- Guard : {value}")

    if not caution_lines:
        caution_lines = ["- Aucun avertissement bloquant détecté dans le pipeline."]

    return f"""CANDIDATURE JOB HUNTER BELGIUM

POSTE
-----
Rang : {job.get('pool_rank')}
Titre : {job.get('title')}
Entreprise : {job.get('company')}
Lieu : {job.get('location')}
Source : {job.get('source')}
URL : {job.get('url')}
Track : {job.get('track')}
Priorité : {job.get('priority')}
Action : {job.get('recommended_action')}

MISSION POUR CHATGPT
--------------------
À partir de l'offre et de la vérité candidat contenues dans job.json :

1. Vérifie une dernière fois l'éligibilité et l'adéquation.
2. Utilise prioritairement {BASE_CV_PREFERENCE} comme base si le track est
   LAB_QC / QUALITY / PRODUCTION_SCIENCE.
3. Pour DATA, repositionne honnêtement le CV vers SQL, Python, Power BI,
   ETL et analyse de données, sans inventer d'expérience professionnelle Data.
4. Produis un CV Word ATS-friendly personnalisé.
5. Produis une lettre de motivation Word adaptée au poste.
6. Si utile, produis aussi un court email de candidature.
7. Ne fabrique aucune compétence, aucun diplôme et aucune durée d'expérience.
8. Le Bachelier de spécialisation Business Data Analysis est TERMINÉ
   depuis juin 2026.
9. Les sciences pharmaceutiques correspondent à un niveau Master 1 validé,
   PAS à un Master obtenu.

POINTS DE VIGILANCE
-------------------
{chr(10).join(caution_lines)}

FICHIERS ATTENDUS
-----------------
CV :
{(job.get('planned_output_files') or {}).get('cv_docx', 'CV.docx')}

Lettre :
{(job.get('planned_output_files') or {}).get('cover_letter_docx', 'Lettre_Motivation.docx')}

Email :
{(job.get('planned_output_files') or {}).get('email_txt', 'Email.txt')}
"""


def write_job_folder(parent, job):
    rank = int(job.get("pool_rank") or 999)
    folder = parent / (
        f"{rank:02d}_{slugify(job.get('company'), 32)}_"
        f"{slugify(job.get('title'), 48)}"
    )
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (folder / "PROMPT_CHATGPT.txt").write_text(
        prompt_text(job),
        encoding="utf-8",
    )

    return folder


def zip_tree(source_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in source_dir.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(source_dir)))


def export_handoff(actions, start=1, limit=None, chunk_size=DEFAULT_CHUNK_SIZE):
    source = latest_file("final_application_pool_v12_*.json")
    if source is None:
        raise RuntimeError(
            "Aucun final_application_pool_v12_*.json trouvé dans exports/logs."
        )

    payload = load_json(source)

    if str(payload.get("pool_version")) != "1.2":
        raise RuntimeError(
            f"Pool inattendu : {payload.get('pool_version')!r}. V1.2 requis."
        )

    selected = select_items(
        payload,
        actions=actions,
        start=start,
        limit=limit,
    )

    if not selected:
        raise RuntimeError("Aucune candidature ne correspond aux filtres.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = EXPORT_ROOT / f"handoff_v1_{stamp}"
    jobs_dir = export_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    compact_jobs = [compact_job(item) for item in selected]

    for job in compact_jobs:
        write_job_folder(jobs_dir, job)

    candidate_path = export_dir / "candidate_truth.json"
    candidate_path.write_text(
        json.dumps(CANDIDATE_TRUTH, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    manifest = {
        "handoff_version": HANDOFF_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_final_pool": str(source),
        "source_pool_version": payload.get("pool_version"),
        "actions": list(actions),
        "start": int(start),
        "limit": limit,
        "selected_count": len(compact_jobs),
        "chunk_size": int(chunk_size),
        "base_cv_preference": BASE_CV_PREFERENCE,
        "jobs": [
            {
                "pool_rank": job.get("pool_rank"),
                "stable_item_key": job.get("stable_item_key"),
                "title": job.get("title"),
                "company": job.get("company"),
                "source": job.get("source"),
                "track": job.get("track"),
                "priority": job.get("priority"),
                "recommended_action": job.get("recommended_action"),
            }
            for job in compact_jobs
        ],
    }

    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    readme = f"""CHATGPT HANDOFF V1.0

Source :
{source}

Pool source :
{payload.get('pool_version')}

Actions :
{', '.join(actions)}

Candidatures exportées :
{len(compact_jobs)}

CV de base préféré :
{BASE_CV_PREFERENCE}

UTILISATION
-----------
1. Envoyer à ChatGPT un ZIP de lot.
2. Lui demander de traiter les candidatures une par une.
3. Pour chaque offre, ChatGPT doit d'abord vérifier l'éligibilité sur
   job.json puis générer CV Word + lettre Word sans rien inventer.
4. Ne jamais marquer une offre APPLIED tant que la candidature n'a pas
   réellement été envoyée.
"""
    (export_dir / "README.txt").write_text(readme, encoding="utf-8")

    # ZIP complet
    full_zip = export_dir.parent / f"{export_dir.name}_ALL.zip"
    zip_tree(export_dir, full_zip)

    # ZIP par chunks
    chunk_paths = []
    if chunk_size and int(chunk_size) > 0:
        chunk_size = int(chunk_size)
        for index in range(0, len(compact_jobs), chunk_size):
            chunk_jobs = compact_jobs[index:index + chunk_size]
            chunk_no = index // chunk_size + 1
            chunk_dir = export_dir.parent / (
                f"{export_dir.name}_chunk_{chunk_no:02d}"
            )
            if chunk_dir.exists():
                shutil.rmtree(chunk_dir)
            (chunk_dir / "jobs").mkdir(parents=True)

            shutil.copy2(candidate_path, chunk_dir / "candidate_truth.json")

            chunk_manifest = {
                **manifest,
                "selected_count": len(chunk_jobs),
                "chunk_number": chunk_no,
                "jobs": [
                    row for row in manifest["jobs"]
                    if row["stable_item_key"]
                    in {j["stable_item_key"] for j in chunk_jobs}
                ],
            }
            (chunk_dir / "manifest.json").write_text(
                json.dumps(chunk_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            shutil.copy2(export_dir / "README.txt", chunk_dir / "README.txt")

            for job in chunk_jobs:
                write_job_folder(chunk_dir / "jobs", job)

            chunk_zip = export_dir.parent / (
                f"{export_dir.name}_chunk_{chunk_no:02d}.zip"
            )
            zip_tree(chunk_dir, chunk_zip)
            chunk_paths.append(chunk_zip)
            shutil.rmtree(chunk_dir)

    print("=" * 92)
    print("CHATGPT HANDOFF V1.0")
    print("=" * 92)
    print("Source             :", source)
    print("Actions            :", ", ".join(actions))
    print("Candidatures       :", len(compact_jobs))
    print("Dossier            :", export_dir)
    print("ZIP complet        :", full_zip)
    print("ZIP lots           :", len(chunk_paths))
    for path in chunk_paths:
        print(" -", path)
    print()
    print("✅ HANDOFF CHATGPT CRÉÉ SANS API.")

    return {
        "export_dir": export_dir,
        "full_zip": full_zip,
        "chunk_zips": chunk_paths,
        "manifest": manifest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--actions",
        nargs="+",
        default=DEFAULT_ACTIONS,
        help="Ex. APPLY_NOW APPLY_NEXT",
    )
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
    )
    args = parser.parse_args()

    export_handoff(
        actions=args.actions,
        start=args.start,
        limit=args.limit,
        chunk_size=args.chunk_size,
    )


if __name__ == "__main__":
    main()

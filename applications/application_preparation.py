"""
JOB HUNTER BELGIUM
APPLICATION PREPARATION - VERSION 1.1

Objectif
========
Transformer Application Queue V1.1 en une liste de dossiers de candidature
prêts à être alimentés par la future génération de documents.

Cette couche NE décide PAS si l'utilisateur doit postuler :
- Matcher = pertinence métier
- Gate    = admissibilité raisonnable
- Queue   = priorité + anti-double-candidature
- Prep    = organisation concrète des candidatures

Principes
=========
- ne modifie ni RAW, ni Canonical, ni Matcher, ni Gate, ni Queue ;
- ne génère aucun contenu CV/lettre sans description complète du poste ;
- conserve l'identité stable de la Queue ;
- une seule préparation active par application_group_id ;
- choisit la piste documentaire DATA / LAB_QC / HYBRID ;
- produit automatiquement TXT + JSON + un manifest par candidature ;
- prépare par défaut les 20 meilleurs READY_APPLY.

Usage
=====
    python -m applications.application_preparation

Optionnel :
    python -m applications.application_preparation --limit 30
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from matching.application_queue_v12 import (
    QUEUE_VERSION,
    build_application_queue_from_gate_payload,
)
from matching.application_gate_v133 import GATE_VERSION  # 18/09/2026 : couche V1.3.3


PREPARATION_VERSION = "1.2"
DEFAULT_BATCH_LIMIT = 20

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
APPLICATION_EXPORT_DIR = PROJECT_ROOT / "exports" / "applications"


CV_TRACK_CONFIG = {
    "LAB_QC": {
        "label": "CV Lab / QC",
        "base_cv_filename": "CV_Oussama_Aharroud_LabQC.docx",
        "strategy": "Mettre en avant chimie, laboratoire, QC, GMP, LIMS et expérience pharma.",
    },
    "DATA": {
        "label": "CV Data / BI",
        # Le CV LabQC reste l'editable de référence si aucun master Data dédié n'existe.
        "base_cv_filename": "CV_Oussama_Aharroud_LabQC.docx",
        "strategy": "Repositionner fortement vers Data/BI : Python, SQL, Power BI, statistiques, ETL et projet BDA.",
    },
    "HYBRID": {
        "label": "CV Hybride Data + Pharma/Qualité",
        "base_cv_filename": "CV_Oussama_Aharroud_LabQC.docx",
        "strategy": "Combiner expérience QC/pharma et compétences Data sans sur-vendre l'expérience professionnelle Data.",
    },
}


CV_SEARCH_DIRS = (
    PROJECT_ROOT,
    PROJECT_ROOT / "cv",
    PROJECT_ROOT / "CV",
    PROJECT_ROOT / "assets",
    PROJECT_ROOT / "assets" / "cv",
    PROJECT_ROOT / "documents",
    PROJECT_ROOT / "documents" / "cv",
)


# ============================================================
# UTILITAIRES
# ============================================================

def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    text = clean_text(value).lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def slugify(value, max_length=70):
    text = normalize(value).replace(" ", "-")
    text = re.sub(r"-+", "-", text).strip("-")
    return (text[:max_length].rstrip("-") or "candidature")


def safe_filename(value, max_length=90):
    text = clean_text(value)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^A-Za-z0-9._ -]+", "", text)
    text = re.sub(r"\s+", "_", text).strip("._-")
    return (text[:max_length].rstrip("._-") or "candidature")


def latest_file(directory, pattern):
    paths = list(Path(directory).glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def find_base_cv(filename):
    for directory in CV_SEARCH_DIRS:
        candidate = directory / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def priority_band(item):
    score = float(item.get("queue_score", 0) or 0)
    preferred = bool(item.get("preferred_location"))

    if preferred and score >= 125:
        return "A+"
    if preferred or score >= 120:
        return "A"
    if score >= 110:
        return "B"
    return "C"


# ============================================================
# VALIDATION DE LA QUEUE
# ============================================================

def validate_queue_payload(items):
    if not isinstance(items, list):
        raise ValueError("Le JSON Queue doit contenir une liste.")

    errors = []
    seen_item_keys = set()

    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            errors.append(f"Élément {index}: format invalide")
            continue

        key = clean_text(item.get("stable_item_key"))
        if not key:
            errors.append(f"Élément {index}: stable_item_key manquant")
        elif key in seen_item_keys:
            errors.append(f"stable_item_key dupliqué: {key}")
        else:
            seen_item_keys.add(key)

        if clean_text(item.get("queue_status")) not in {
            "READY_APPLY", "READY_STRETCH", "VERIFY_FIRST", "HOLD_DUPLICATE", "EXCLUDED"
        }:
            errors.append(f"{key or index}: queue_status inconnu")

    if errors:
        raise ValueError("Queue invalide:\n- " + "\n- ".join(errors[:20]))

    return True


# ============================================================
# CONSTRUCTION DU LOT
# ============================================================

def _build_output_names(position, item):
    company = safe_filename(item.get("company"))[:28]
    title = safe_filename(item.get("title"))[:42]
    stem = f"{position:02d}_{company}_{title}".strip("_")

    return {
        "cv_docx": f"{stem}_CV.docx",
        "cover_letter_docx": f"{stem}_Lettre_Motivation.docx",
        "email_txt": f"{stem}_Email.txt",
        "job_snapshot_txt": f"{stem}_Offre.txt",
    }


def _build_preparation_item(item, batch_position):
    cv_track = clean_text(item.get("cv_track")) or "HYBRID"
    cv_cfg = CV_TRACK_CONFIG.get(cv_track, CV_TRACK_CONFIG["HYBRID"])
    base_cv_path = find_base_cv(cv_cfg["base_cv_filename"])

    stable_key = clean_text(item.get("stable_item_key"))
    title = clean_text(item.get("title"))
    company = clean_text(item.get("company"))

    folder_name = f"{batch_position:02d}_{stable_key}_{slugify(company + '-' + title, 55)}"
    folder_rel = Path("exports") / "applications" / folder_name
    output_names = _build_output_names(batch_position, item)

    return {
        "preparation_version": PREPARATION_VERSION,
        "batch_position": batch_position,
        "stable_item_key": stable_key,
        "application_group_id": clean_text(item.get("application_group_id")),
        "canonical_job_id": item.get("canonical_job_id"),
        "queue_rank": item.get("queue_rank"),
        "queue_score": float(item.get("queue_score", 0) or 0),
        "match_score": float(item.get("match_score", 0) or 0),
        "priority_band": priority_band(item),
        "preferred_location": bool(item.get("preferred_location")),
        "title": title,
        "company": company,
        "location": clean_text(item.get("location")),
        "url": clean_text(item.get("url")),
        "source": clean_text(item.get("source")),
        "origin_source": clean_text(item.get("origin_source")),
        "best_family": clean_text(item.get("best_family")),
        "cv_track": cv_track,
        "cv_track_label": cv_cfg["label"],
        "cv_strategy": cv_cfg["strategy"],
        "base_cv_filename": cv_cfg["base_cv_filename"],
        "base_cv_found": bool(base_cv_path),
        "base_cv_path": str(base_cv_path) if base_cv_path else None,
        "application_folder": str(folder_rel),
        "output_files": output_names,
        # Queue V1.1 ne contient volontairement pas la description complète.
        # On interdit donc toute génération automatique de documents à ce stade.
        "job_description_status": "NEEDS_REFRESH_FROM_SOURCE_URL",
        "document_generation_status": "WAITING_JOB_DESCRIPTION",
        "safe_to_generate_documents": False,
        "next_action": "Lire/rafraîchir l'offre depuis l'URL, vérifier qu'elle est encore active, puis générer CV + lettre adaptés.",
        "gate": item.get("gate") or {},
    }


def build_application_preparation(queue_items, limit=DEFAULT_BATCH_LIMIT):
    validate_queue_payload(queue_items)

    ready = [item for item in queue_items if item.get("queue_status") == "READY_APPLY"]
    ready.sort(
        key=lambda x: (
            float(x.get("queue_score", 0) or 0),
            float(x.get("match_score", 0) or 0),
            -int(x.get("queue_rank", 999999) or 999999),
        ),
        reverse=True,
    )

    selected = []
    seen_groups = set()
    ecartees_par_verdict = []

    for item in ready:
        group_id = clean_text(item.get("application_group_id")) or clean_text(item.get("stable_item_key"))
        if group_id in seen_groups:
            continue

        # Un creneau de preparation coute un rafraichissement live. Le
        # depenser sur une offre dont la barriere est prouvee, c'est le
        # retirer a une offre ouverte qui attend juste en dessous.
        #
        # Mesure du 9 septembre 2026 : sur les 150 premieres offres par
        # score, 32 etaient FERMEES — 21 % du budget. Sous la ligne de
        # coupe attendaient 217 titres distincts sans aucune barriere.
        #
        # Le champ absent ne ferme rien : une file construite sans verdict
        # se comporte exactement comme avant.
        if clean_text(item.get("verdict")) == "FERMEE":
            ecartees_par_verdict.append(item)
            continue

        seen_groups.add(group_id)

        selected.append(_build_preparation_item(item, len(selected) + 1))
        if len(selected) >= max(1, int(limit)):
            break

    if ecartees_par_verdict:
        print(f"[PREPARATION] {len(ecartees_par_verdict)} offres FERMEES "
              f"ecartees, autant de creneaux rendus aux offres ouvertes.")
        for item in ecartees_par_verdict[:5]:
            print(f"             - {clean_text(item.get('title'))[:48]:<48} "
                  f"{clean_text(item.get('verdict_obstacle'))[:60]}")

    return selected


# ============================================================
# EXPORT
# ============================================================

def preparation_summary(items):
    return {
        "total": len(items),
        "priority_A_plus": sum(1 for x in items if x.get("priority_band") == "A+"),
        "priority_A": sum(1 for x in items if x.get("priority_band") == "A"),
        "priority_B": sum(1 for x in items if x.get("priority_band") == "B"),
        "priority_C": sum(1 for x in items if x.get("priority_band") == "C"),
        "preferred_location": sum(1 for x in items if x.get("preferred_location")),
        "cv_data": sum(1 for x in items if x.get("cv_track") == "DATA"),
        "cv_lab_qc": sum(1 for x in items if x.get("cv_track") == "LAB_QC"),
        "cv_hybrid": sum(1 for x in items if x.get("cv_track") == "HYBRID"),
        "base_cv_found": sum(1 for x in items if x.get("base_cv_found")),
        "waiting_job_description": sum(
            1 for x in items if x.get("document_generation_status") == "WAITING_JOB_DESCRIPTION"
        ),
    }


def _manifest_text(item):
    lines = [
        "APPLICATION PREPARATION V1",
        "=" * 76,
        f"Position        : {item['batch_position']}",
        f"Priorité        : {item['priority_band']}",
        f"Queue score     : {item['queue_score']}",
        f"Match score     : {item['match_score']}",
        f"Poste           : {item['title']}",
        f"Entreprise      : {item['company']}",
        f"Lieu            : {item['location']}",
        f"URL             : {item['url']}",
        f"CV track        : {item['cv_track_label']}",
        f"CV de base      : {item['base_cv_filename']}",
        f"CV trouvé       : {'OUI' if item['base_cv_found'] else 'NON'}",
        "",
        "ÉTAPE OBLIGATOIRE AVANT GÉNÉRATION",
        "- Ouvrir/rafraîchir la page de l'offre.",
        "- Vérifier que l'offre est encore active.",
        "- Récupérer la description complète et les exigences.",
        "- Seulement ensuite générer le CV ATS et la lettre de motivation.",
        "",
        "FICHIERS PRÉVUS",
        f"- {item['output_files']['cv_docx']}",
        f"- {item['output_files']['cover_letter_docx']}",
        f"- {item['output_files']['email_txt']}",
        f"- {item['output_files']['job_snapshot_txt']}",
    ]
    return "\n".join(lines)


def export_application_preparation(items, project_root=PROJECT_ROOT):
    root = Path(project_root)
    log_dir = root / "exports" / "logs"
    app_root = root / "exports" / "applications"
    log_dir.mkdir(parents=True, exist_ok=True)
    app_root.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = log_dir / f"application_preparation_v1_{timestamp}.json"
    txt_path = log_dir / f"application_preparation_v1_{timestamp}.txt"

    json_path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = preparation_summary(items)
    lines = [
        "APPLICATION PREPARATION V1",
        "=" * 76,
        f"Total préparé       : {summary['total']}",
        f"Priorité A+          : {summary['priority_A_plus']}",
        f"Priorité A           : {summary['priority_A']}",
        f"Priorité B           : {summary['priority_B']}",
        f"Priorité C           : {summary['priority_C']}",
        f"Zone prioritaire     : {summary['preferred_location']}",
        f"CV DATA              : {summary['cv_data']}",
        f"CV LAB_QC            : {summary['cv_lab_qc']}",
        f"CV HYBRID            : {summary['cv_hybrid']}",
        f"CV de base trouvé    : {summary['base_cv_found']}/{summary['total']}",
        f"Attente description  : {summary['waiting_job_description']}/{summary['total']}",
        "",
    ]

    for item in items:
        star = "⭐" if item.get("preferred_location") else " "
        lines.extend([
            f"{item['batch_position']:>2}. {star} [{item['priority_band']}] Q{item['queue_score']:.1f} | M{item['match_score']:.1f}",
            f"    {item['title']}",
            f"    {item['company']}",
            f"    {item['location']}",
            f"    CV : {item['cv_track_label']} -> {item['base_cv_filename']}",
            f"    État documents : {item['document_generation_status']}",
            f"    {item['url']}",
            "",
        ])

        folder = root / item["application_folder"]
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "application_manifest.json").write_text(
            json.dumps(item, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (folder / "README.txt").write_text(_manifest_text(item), encoding="utf-8")

    txt_path.write_text("\n".join(lines), encoding="utf-8")

    return {
        "json_path": json_path,
        "txt_path": txt_path,
        "applications_root": app_root,
        "summary": summary,
    }


# ============================================================
# CLI
# ============================================================


def _payload_gate_version(payload):
    versions = {
        clean_text((row.get("gate") or {}).get("gate_version"))
        for row in (payload or [])
        if isinstance(row, dict)
    }
    versions.discard("")
    if not versions:
        return "UNKNOWN"
    if len(versions) == 1:
        return next(iter(versions))
    return "MIXED:" + ",".join(sorted(versions))


def _payload_queue_version(payload):
    versions = {
        clean_text(row.get("queue_version"))
        for row in (payload or [])
        if isinstance(row, dict)
    }
    versions.discard("")
    if not versions:
        return "UNKNOWN"
    if len(versions) == 1:
        return next(iter(versions))
    return "MIXED:" + ",".join(sorted(versions))


def _assert_current_gate_version(payload, source_path):
    detected = _payload_gate_version(payload)
    if detected != GATE_VERSION:
        raise RuntimeError(
            "Gate export obsolète/incompatible. "
            f"Installé={GATE_VERSION} ; export={detected} ; fichier={source_path}. "
            "Exécuter d'abord : "
            "python -m diagnostics.application_gate_v132_db_replay"
        )
    return detected


def _assert_current_queue_version(payload, source_path):
    detected = _payload_queue_version(payload)
    if detected != QUEUE_VERSION:
        raise RuntimeError(
            "Queue export obsolète/incompatible. "
            f"Installée={QUEUE_VERSION} ; export={detected} ; fichier={source_path}."
        )
    return detected

def load_current_queue(project_root=PROJECT_ROOT):
    """
    V1.1 - cohérence stricte Gate / Queue.

    Règles :
    1. Si un Gate existe, il DOIT avoir la même version que le Gate installé.
    2. La Queue est reconstruite avec matching.application_queue_v12.
    3. Un ancien Gate 1.3.1 n'est plus silencieusement accepté quand 1.3.2
       est installé.
    4. Le fallback Queue n'est accepté que si queue_version correspond à
       la Queue installée ET si le Gate embarqué correspond au Gate installé.

    Cette logique empêche notamment de réintroduire le bug Evere/Beveren
    depuis un export historique.
    """
    root = Path(project_root)
    log_dir = root / "exports" / "logs"

    gate_path = latest_file(log_dir, "application_gate_v1_*.json")
    if gate_path is not None:
        gate_payload = load_json(gate_path)
        detected_gate = _assert_current_gate_version(gate_payload, gate_path)

        queue_items = build_application_queue_from_gate_payload(gate_payload)
        detected_queue = _payload_queue_version(queue_items)

        if detected_queue != QUEUE_VERSION:
            raise RuntimeError(
                "La Queue reconstruite n'utilise pas la version attendue. "
                f"Attendu={QUEUE_VERSION} ; obtenu={detected_queue}."
            )

        return {
            "source_type": "GATE_REBUILT_WITH_CURRENT_GATE_AND_QUEUE",
            "source_path": gate_path,
            "gate_version": detected_gate,
            "queue_version": detected_queue,
            "items": queue_items,
        }

    # Fallback uniquement si aucun Gate n'existe.
    queue_candidates = []
    for pattern in (
        "application_queue_v12_replay_*.json",
        "application_queue_v1_*.json",
    ):
        queue_candidates.extend(log_dir.glob(pattern))

    if queue_candidates:
        queue_path = max(queue_candidates, key=lambda p: p.stat().st_mtime)
        queue_items = load_json(queue_path)

        detected_queue = _assert_current_queue_version(queue_items, queue_path)
        detected_gate = _payload_gate_version(queue_items)

        if detected_gate != GATE_VERSION:
            raise RuntimeError(
                "Queue correcte mais Gate embarqué obsolète/incompatible. "
                f"Gate installé={GATE_VERSION} ; Gate queue={detected_gate}. "
                "Exécuter d'abord : "
                "python -m diagnostics.application_gate_v132_db_replay"
            )

        return {
            "source_type": "QUEUE_JSON_CURRENT_FALLBACK",
            "source_path": queue_path,
            "gate_version": detected_gate,
            "queue_version": detected_queue,
            "items": queue_items,
        }

    raise FileNotFoundError(
        "Aucun export Gate/Queue compatible trouvé dans exports/logs/."
    )

def run_from_latest_queue(limit=DEFAULT_BATCH_LIMIT, project_root=PROJECT_ROOT):
    root = Path(project_root)
    current = load_current_queue(project_root=root)
    prepared = build_application_preparation(current["items"], limit=limit)
    export = export_application_preparation(prepared, project_root=root)
    return current, prepared, export


def main():
    parser = argparse.ArgumentParser(description="Application Preparation V1")
    parser.add_argument("--limit", type=int, default=DEFAULT_BATCH_LIMIT)
    args = parser.parse_args()

    current, prepared, export = run_from_latest_queue(limit=args.limit)
    summary = export["summary"]

    print("APPLICATION PREPARATION V1.1")
    print("=" * 76)
    print("Source              :", current["source_type"])
    print("Fichier source      :", current["source_path"])
    print("Gate utilisé        :", current.get("gate_version"))
    print("Queue utilisée      :", current["queue_version"])
    print("Candidatures lot    :", summary["total"])
    print("Zone prioritaire    :", summary["preferred_location"])
    print("CV DATA             :", summary["cv_data"])
    print("CV LAB_QC           :", summary["cv_lab_qc"])
    print("CV HYBRID           :", summary["cv_hybrid"])
    print("CV de base trouvé   :", f"{summary['base_cv_found']}/{summary['total']}")
    print("TXT                  :", export["txt_path"])
    print("JSON                 :", export["json_path"])
    print("Dossiers             :", export["applications_root"])
    print()
    print("⚠️ Aucun document n'est généré avant lecture de la description complète de l'offre.")


if __name__ == "__main__":
    main()

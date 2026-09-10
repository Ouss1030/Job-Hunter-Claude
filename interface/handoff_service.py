from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any

from applications.chatgpt_handoff import DEFAULT_CHUNK_SIZE, EXPORT_ROOT, export_handoff
from interface.data_access import decorate_scored_jobs, load_latest_final_pool


def load_candidates() -> tuple[list[dict[str, Any]], Path | None]:
    """Retourne le dernier Final Application Pool enrichi avec le suivi Lifecycle."""
    pool, _, source_path = load_latest_final_pool()
    return decorate_scored_jobs(pool, final=True), source_path


def create_manual_handoff(stable_keys: list[str], chunk_size: int = DEFAULT_CHUNK_SIZE) -> dict[str, Any]:
    """Crée un handoff UNIQUEMENT pour les offres explicitement sélectionnées."""
    keys = [str(value).strip() for value in stable_keys if str(value).strip()]
    if not keys:
        raise ValueError("Sélectionne au moins une offre avant de créer les chunks.")

    chunk_size = int(chunk_size)
    if chunk_size < 1 or chunk_size > 50:
        raise ValueError("La taille des chunks doit être comprise entre 1 et 50.")

    result = export_handoff(
        actions=None,
        stable_keys=keys,
        chunk_size=chunk_size,
        create_full_zip=False,
    )

    return {
        "export_dir": Path(result["export_dir"]),
        "chunk_zips": [Path(path) for path in result.get("chunk_zips") or []],
        "manifest": result.get("manifest") or {},
    }


def _read_manifest(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def handoff_history(limit: int = 20) -> list[dict[str, Any]]:
    """Liste les dossiers handoff et leurs chunks, du plus récent au plus ancien."""
    if not EXPORT_ROOT.exists():
        return []

    folders = [path for path in EXPORT_ROOT.glob("handoff_v1_*") if path.is_dir()]
    folders.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    rows: list[dict[str, Any]] = []
    for folder in folders[: max(1, int(limit))]:
        manifest = _read_manifest(folder / "manifest.json")
        chunk_zips = sorted(
            EXPORT_ROOT.glob(f"{folder.name}_chunk_*.zip"),
            key=lambda path: path.name,
        )
        generated_at = manifest.get("generated_at")
        if not generated_at:
            generated_at = datetime.fromtimestamp(folder.stat().st_mtime).isoformat(timespec="seconds")

        rows.append(
            {
                "folder": folder,
                "generated_at": generated_at,
                "selected_count": int(manifest.get("selected_count") or 0),
                "chunk_size": int(manifest.get("chunk_size") or 0),
                "chunk_zips": chunk_zips,
                "manifest": manifest,
            }
        )
    return rows


def latest_handoff() -> dict[str, Any] | None:
    rows = handoff_history(limit=1)
    return rows[0] if rows else None


def open_folder(path: Path | str) -> None:
    """Ouvre un dossier dans l'Explorateur local (Streamlit tourne sur le PC utilisateur)."""
    target = Path(path).resolve()
    if target.is_file():
        target = target.parent
    if not target.exists():
        raise FileNotFoundError(f"Dossier introuvable : {target}")

    if os.name == "nt":
        os.startfile(str(target))  # type: ignore[attr-defined]
        return

    # Fallback utile uniquement pour les tests / autres OS.
    command = ["open", str(target)] if sys_platform_is_macos() else ["xdg-open", str(target)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def sys_platform_is_macos() -> bool:
    import sys

    return sys.platform == "darwin"

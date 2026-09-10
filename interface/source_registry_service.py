from __future__ import annotations

from sources.registry import list_source_status, save_source_settings


def registered_sources() -> list[dict]:
    return list_source_status()


def update_enabled_sources(enabled_keys: list[str]) -> None:
    enabled = {str(key).upper().strip() for key in enabled_keys}
    rows = list_source_status()
    settings = {row["key"]: row["key"] in enabled for row in rows}
    save_source_settings(settings)

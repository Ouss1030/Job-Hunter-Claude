from __future__ import annotations

import re
from typing import Iterable

_VERSION_PREFIX_RE = re.compile(r"^\s*[vV]?(\d+(?:\.\d+)*)")


def version_tuple(value: object) -> tuple[int, ...] | None:
    """Parse un préfixe de version numérique : 1.3.2, v1.3.2, 1.3.2-dev."""
    text = str(value or "").strip()
    match = _VERSION_PREFIX_RE.match(text)
    if not match:
        return None
    try:
        return tuple(int(part) for part in match.group(1).split("."))
    except Exception:
        return None


def _pad_pair(left: tuple[int, ...], right: tuple[int, ...]):
    width = max(len(left), len(right))
    return (
        left + (0,) * (width - len(left)),
        right + (0,) * (width - len(right)),
    )


def version_at_least(current: object, minimum: object) -> bool:
    cur = version_tuple(current)
    minv = version_tuple(minimum)
    if cur is None or minv is None:
        return False
    cur, minv = _pad_pair(cur, minv)
    return cur >= minv


def version_set_at_least(
    values: Iterable[object],
    minimum: object,
    *,
    require_single: bool = True,
    allow_empty: bool = False,
) -> bool:
    normalized = {str(value or "").strip() for value in values if str(value or "").strip()}

    if not normalized:
        return bool(allow_empty)

    if require_single and len(normalized) != 1:
        return False

    return all(version_at_least(value, minimum) for value in normalized)

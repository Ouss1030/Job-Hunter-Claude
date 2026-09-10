"""
Helpers de version pour les diagnostics Job Hunter.

Un audit de fonctionnalité doit exprimer la version MINIMALE dans laquelle
la fonctionnalité existe, et non épingler la version exacte installée.
"""

from __future__ import annotations

import re


_VERSION_RE = re.compile(r"^\s*[vV]?(\d+(?:\.\d+)*)")


def version_tuple(value):
    """
    Convertit une version numérique simple en tuple d'entiers.

    Exemples :
        "1.1.1" -> (1, 1, 1)
        "v2.0"  -> (2, 0)

    Les suffixes éventuels après la partie numérique sont ignorés.
    """
    text = str(value or "").strip()
    match = _VERSION_RE.match(text)
    if not match:
        raise ValueError(f"Version non numérique/invalide : {value!r}")
    return tuple(int(part) for part in match.group(1).split("."))


def _pad(values, size):
    return values + (0,) * (size - len(values))


def at_least(current, minimum):
    """
    True si current >= minimum en comparaison structurelle numérique.

    Important :
        1.10.0 > 1.9.9
    contrairement à une comparaison lexicographique de chaînes.
    """
    cur = version_tuple(current)
    req = version_tuple(minimum)
    size = max(len(cur), len(req))
    return _pad(cur, size) >= _pad(req, size)

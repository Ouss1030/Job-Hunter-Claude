"""
JOB HUNTER BELGIUM
COMPARAISON DE VERSIONS POUR LES DIAGNOSTICS

Pourquoi ce fichier
-------------------
Les audits épinglaient une version littérale exacte :

    daily_run.DAILY_RUN_VERSION == "1.0.1"

Chaque montée de version transformait mécaniquement un audit sain en fausse
alerte, alors que le correctif qu'il protège était toujours présent.

Le repli naïf est pire :

    str(version).startswith("1.0")     # échoue sur 1.1.0
                                       # accepterait "1.05"

C'est la même famille de défaut que le matching par sous-chaîne sans
frontière de mot qui a produit le bug V.I.E : on compare du texte là où il
faut comparer une structure.

Usage
-----
    from diagnostics.version_support import at_least

    at_least(daily_run.DAILY_RUN_VERSION, "1.0.1")   # True pour 1.1.0
    at_least(refresh.REFRESH_VERSION, "1.2")         # True pour 1.2, 1.2.3, 2.0

Un audit doit exprimer la version **minimale** qui contient ce qu'il teste,
pas la version exacte qui existait le jour où il a été écrit.
"""

from __future__ import annotations

import re


_NOMBRE = re.compile(r"\d+")


def parse_version(value) -> tuple[int, ...]:
    """
    "1.0.2" -> (1, 0, 2)

    Tolère les suffixes ("1.3.2-shadow" -> (1, 3, 2)) et les valeurs vides.
    """
    return tuple(int(x) for x in _NOMBRE.findall(str(value or ""))) or (0,)


def _aligner(a: tuple[int, ...], b: tuple[int, ...]):
    taille = max(len(a), len(b))
    return (
        a + (0,) * (taille - len(a)),
        b + (0,) * (taille - len(b)),
    )


def at_least(version, minimum) -> bool:
    """True si `version` est supérieure ou égale à `minimum`."""
    a, b = _aligner(parse_version(version), parse_version(minimum))
    return a >= b


def same_family(version, reference, profondeur: int = 1) -> bool:
    """
    True si les `profondeur` premiers composants coïncident.

    same_family("1.1.0", "1.0.2")      -> True   (famille 1.x)
    same_family("1.1.0", "1.0.2", 2)   -> False  (1.1 != 1.0)
    same_family("2.0.0", "1.0.2")      -> False
    """
    a = parse_version(version)[:profondeur]
    b = parse_version(reference)[:profondeur]
    a, b = _aligner(a, b)
    return a == b

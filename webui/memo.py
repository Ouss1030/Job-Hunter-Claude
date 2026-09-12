"""
JOB HUNTER BELGIUM
INTERFACE WEB - MEMOIRE DES CALCULS - VERSION 1.0

Pourquoi
--------
Mesure du 13 septembre 2026, avant ce module :

    page Offres          1 457 ms
    page Aujourd'hui     1 457 ms   (recalculait tout pour compter)
    page Statistiques   13 446 ms   (1 500 verdicts a chaque visite)

Tout etait recalcule a chaque requete. Or rien de tout cela ne change entre
deux clics : le pool ne bouge qu'a la fin d'un run, le suivi qu'a un triage,
le marche qu'a une collecte. Recalculer un verdict identique cent fois par
minute n'apporte rien — sauf l'impression que l'outil est lent.

Le principe
-----------
Chaque calcul couteux est memorise avec une EMPREINTE de ce dont il depend :
la date de modification de l'artefact de pool, l'identifiant du dernier run
de collecte. Si l'empreinte n'a pas change, le resultat memorise est rendu ;
sinon on recalcule. Pas de duree de vie arbitraire : un cache qui expire au
bout de N minutes rend tantot du perime, tantot du recalcul inutile.

Ce que ce module ne fait pas
----------------------------
Il ne persiste rien sur disque. Au redemarrage du serveur, tout est
recalcule une fois — c'est le prix d'une memoire simple, et il est paye une
seule fois par session.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Hashable


MEMO_VERSION = "1.0"


class Memoire:
    """Memorise un resultat tant que son empreinte ne change pas."""

    def __init__(self) -> None:
        self._resultats: dict[str, tuple[Hashable, Any]] = {}
        self._verrou = threading.Lock()

    def obtenir(self, nom: str, empreinte: Hashable,
                calcul: Callable[[], Any]) -> Any:
        with self._verrou:
            memorise = self._resultats.get(nom)
            if memorise is not None and memorise[0] == empreinte:
                return memorise[1]
        # Le calcul se fait hors verrou : un calcul de treize secondes ne
        # doit pas bloquer les autres pages pendant ce temps.
        resultat = calcul()
        with self._verrou:
            self._resultats[nom] = (empreinte, resultat)
        return resultat

    def oublier(self, nom: str | None = None) -> None:
        with self._verrou:
            if nom is None:
                self._resultats.clear()
            else:
                self._resultats.pop(nom, None)

    def etat(self) -> dict[str, str]:
        with self._verrou:
            return {nom: str(emp)[:60] for nom, (emp, _) in self._resultats.items()}


MEMOIRE = Memoire()

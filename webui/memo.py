"""
JOB HUNTER BELGIUM
INTERFACE WEB - MEMOIRE DES CALCULS - VERSION 1.1

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
Chaque calcul couteux est memorise avec une EMPREINTE de ce dont il depend.
Si l'empreinte n'a pas change, le resultat memorise est rendu ; sinon on
recalcule. Pas de duree de vie arbitraire : un cache qui expire au bout de
N minutes rend tantot du perime, tantot du recalcul inutile.

V1.1 — un seul calcul a la fois par cle
---------------------------------------
La V1.0 calculait hors verrou, pour ne pas bloquer les autres pages. Bien —
sauf quand deux appelants demandaient la MEME cle au meme moment : chacun
lancait le calcul de son cote. Mesure : le prechauffage et une requete
calculaient « marche » ensemble, 13 secondes chacun, ralentis l'un par
l'autre — 24 secondes au total pour un resultat.

Chaque cle a maintenant son propre verrou : le second appelant attend le
premier, puis lit le resultat. Les cles differentes restent independantes.

Persistance
-----------
Un calcul peut etre adosse a un fichier : le resultat est ecrit sur disque
sous son empreinte, et relu au demarrage suivant sans etre recalcule. C'est
le bon choix pour ce qui ne change qu'a une collecte — le marche, les
conseils — et qui coute des dizaines de secondes.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Callable, Hashable


MEMO_VERSION = "1.1"


def _normaliser(valeur):
    """Tuples -> listes, recursivement : la forme qu'un JSON rendra."""
    if isinstance(valeur, (tuple, list)):
        return [_normaliser(v) for v in valeur]
    return valeur


class Memoire:
    """Memorise un resultat tant que son empreinte ne change pas."""

    def __init__(self) -> None:
        self._resultats: dict[str, tuple[Hashable, Any]] = {}
        self._global = threading.Lock()
        self._par_cle: dict[str, threading.Lock] = {}

    def _verrou(self, nom: str) -> threading.Lock:
        with self._global:
            if nom not in self._par_cle:
                self._par_cle[nom] = threading.Lock()
            return self._par_cle[nom]

    def obtenir(self, nom: str, empreinte: Hashable,
                calcul: Callable[[], Any],
                fichier: Path | None = None) -> Any:
        with self._global:
            memorise = self._resultats.get(nom)
            if memorise is not None and memorise[0] == empreinte:
                return memorise[1]

        # Un seul calcul par cle : le deuxieme appelant attend le premier.
        with self._verrou(nom):
            with self._global:
                memorise = self._resultats.get(nom)
                if memorise is not None and memorise[0] == empreinte:
                    return memorise[1]

            # L'empreinte passe par JSON pour etre comparee a celle du
            # fichier : les tuples y deviennent des listes, a tous les
            # niveaux. On normalise des deux cotes.
            attendu = _normaliser(empreinte)
            resultat = None
            if fichier is not None and fichier.exists():
                try:
                    charge = json.loads(fichier.read_text(encoding="utf-8"))
                    if charge.get("_empreinte") == attendu:
                        resultat = charge.get("_resultat")
                except Exception:
                    resultat = None

            if resultat is None:
                resultat = calcul()
                if fichier is not None:
                    try:
                        fichier.parent.mkdir(parents=True, exist_ok=True)
                        fichier.write_text(json.dumps(
                            {"_empreinte": attendu, "_resultat": resultat},
                            ensure_ascii=False), encoding="utf-8")
                    except Exception:
                        # Ne pas pouvoir ecrire l'artefact n'est pas une
                        # erreur : le resultat reste en memoire.
                        pass

            with self._global:
                self._resultats[nom] = (empreinte, resultat)
            return resultat

    def oublier(self, nom: str | None = None) -> None:
        with self._global:
            if nom is None:
                self._resultats.clear()
            else:
                self._resultats.pop(nom, None)

    def etat(self) -> dict[str, str]:
        with self._global:
            return {nom: str(emp)[:60] for nom, (emp, _) in self._resultats.items()}


MEMOIRE = Memoire()

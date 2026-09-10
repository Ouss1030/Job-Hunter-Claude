"""
JOB HUNTER BELGIUM
DIAGNOSTIC DU SILENCE DES SOURCES - VERSION 1.0

    python -m diagnostics.source_silence_probe --pilote
    python -m diagnostics.source_silence_probe --toutes
    python -m diagnostics.source_silence_probe --sources GSK,PFIZER

Le probleme
-----------
130 sources sur 174 n'ont jamais ecrit une ligne en base. On ne sait pas
pourquoi, et « 130 sources cassees » n'est pas la meme chose que « 5 a
reparer et 125 qui n'ont simplement aucune offre pour ce profil aujourd'hui ».

Sans cette distinction, on repare a l'aveugle.

Ce que fait cet outil
---------------------
Il appelle chaque collecteur isolement, avec un delai maximum, capture ce
qu'il rend et ce qu'il publie comme metriques, puis classe le resultat :

    PRODUIT          des offres sont revenues
    RESEAU           exception, timeout, blocage HTTP
    FILTRE           des annonces vues, aucune retenue
    AUCUNE_CIBLE     rien vu, mais aucune erreur : la source va bien,
                     elle n'a simplement rien pour ce profil
    MUETTE           ni offres, ni metriques, ni erreur : instrumentation
                     absente, on ne peut rien conclure

Cette derniere categorie est la plus importante : elle liste les sources qu'il
faut instrumenter avant de pouvoir les juger.

AUCUNE ECRITURE EN BASE
-----------------------
Les collecteurs renvoient des objets en memoire ; c'est main.py qui persiste.
Cet outil n'appelle jamais la sauvegarde. La base et l'historique des
candidatures ne sont pas touches.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import datetime
from pathlib import Path


PROBE_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# 75 s etait trop court : les connecteurs ATS qui parcourent un sitemap
# complet mettent 110 a 250 s et etaient classes RESEAU a tort. Un delai trop
# court ne produit pas une absence de resultat, il produit un mauvais
# diagnostic — le pire des deux.
TIMEOUT_PAR_SOURCE = 300
TAILLE_PILOTE = 10


def sources_muettes() -> list:
    """Sources actives n'ayant jamais rien ecrit en base."""
    from sources.registry import SOURCE_SPECS, load_source_settings

    settings = load_source_settings()
    con = sqlite3.connect(f"file:{DB_PATH.resolve().as_uri()[8:]}?mode=ro", uri=True) \
        if False else sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    connues = {s for (s,) in con.execute("SELECT DISTINCT source FROM raw_jobs")}
    con.close()

    return [s for s in SOURCE_SPECS
            if settings.get(s.key, s.enabled_default) and s.key not in connues]


def _metriques(cle: str) -> dict:
    """Metriques publiees par la source, si elle en publie."""
    try:
        from sources import source_metrics
        store = getattr(source_metrics, "_STORE", None)
        if isinstance(store, dict):
            return dict(store.get(str(cle).upper(), {}) or {})
    except Exception:
        pass
    return {}


def _classer(offres, erreur, metriques) -> tuple[str, str]:
    if erreur:
        bas = erreur.lower()
        if "timeout" in bas:
            # Un timeout ne prouve pas une panne : la source peut etre
            # simplement lente. On le dit plutot que de conclure.
            return "TROP_LENTE", erreur[:110]
        if any(x in bas for x in ("connection", "ssl", "resolve",
                                  "http", "403", "429", "503")):
            return "RESEAU", erreur[:110]
        return "ERREUR", erreur[:110]

    if offres:
        return "PRODUIT", f"{len(offres)} offres"

    if not metriques:
        # Aucune metrique publiee : la source n'est pas instrumentee, donc
        # son silence est ininterpretable. C'est un defaut a corriger, pas un
        # constat sur la source.
        return "MUETTE", "aucune metrique publiee"

    vues = 0
    for cle in ("seen", "listings_seen", "candidates", "total"):
        if isinstance(metriques.get(cle), int):
            vues = max(vues, metriques[cle])
    if vues > 0:
        detail = ", ".join(f"{k}={v}" for k, v in sorted(metriques.items())
                           if isinstance(v, int) and v)
        return "FILTRE", (detail or f"{vues} vues, 0 retenue")[:110]
    return "AUCUNE_CIBLE", "0 annonce vue, aucune erreur"


def sonder(spec, timeout: int = TIMEOUT_PAR_SOURCE) -> dict:
    debut = time.time()
    offres, erreur = [], ""

    with ThreadPoolExecutor(max_workers=1) as pool:
        futur = pool.submit(spec.collector)
        try:
            offres = futur.result(timeout=timeout) or []
        except FuturesTimeout:
            erreur = f"timeout apres {timeout}s"
        except Exception as exc:
            erreur = f"{type(exc).__name__}: {exc}"

    metriques = _metriques(spec.key)
    etat, detail = _classer(offres, erreur, metriques)
    return {
        "key": spec.key,
        "label": spec.label,
        "etat": etat,
        "detail": detail,
        "offres": len(offres) if offres else 0,
        "secondes": round(time.time() - debut, 1),
        "metriques": {k: v for k, v in metriques.items()
                      if isinstance(v, (int, str)) and v not in ("", 0)},
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Diagnostic du silence des sources")
    groupe = parser.add_mutually_exclusive_group()
    groupe.add_argument("--pilote", action="store_true",
                        help=f"Sonde {TAILLE_PILOTE} sources pour valider l'outil")
    groupe.add_argument("--toutes", action="store_true")
    groupe.add_argument("--sources", type=str, help="Liste separee par des virgules")
    parser.add_argument("--timeout", type=int, default=TIMEOUT_PAR_SOURCE)
    args = parser.parse_args(argv)

    from sources.registry import SOURCE_SPECS

    if args.sources:
        voulues = {x.strip().upper() for x in args.sources.split(",") if x.strip()}
        cibles = [s for s in SOURCE_SPECS if s.key in voulues]
    else:
        cibles = sources_muettes()
        if args.pilote:
            cibles = cibles[:TAILLE_PILOTE]

    print("=" * 88)
    print(f"DIAGNOSTIC DU SILENCE DES SOURCES V{PROBE_VERSION}"
          f"{'  (PILOTE)' if args.pilote else ''}")
    print("=" * 88)
    print(f"  sources a sonder : {len(cibles)}")
    print(f"  delai maximum    : {args.timeout}s par source")
    print("  ecriture en base : AUCUNE")
    print()
    print(f"  {'SOURCE':<24}{'ETAT':<14}{'S':>6}  DETAIL")
    print("  " + "-" * 84)

    resultats = []
    t0 = time.time()
    for i, spec in enumerate(cibles, 1):
        r = sonder(spec, args.timeout)
        resultats.append(r)
        print(f"  {r['key']:<24}{r['etat']:<14}{r['secondes']:>6}  {r['detail'][:44]}",
              flush=True)

    duree = time.time() - t0
    par_etat: dict[str, list[str]] = {}
    for r in resultats:
        par_etat.setdefault(r["etat"], []).append(r["key"])

    print()
    print("=" * 88)
    print(f"RESUME — {len(resultats)} sources en {duree/60:.1f} min")
    print("=" * 88)
    for etat in ("PRODUIT", "FILTRE", "AUCUNE_CIBLE", "TROP_LENTE",
                 "RESEAU", "ERREUR", "MUETTE"):
        cles = par_etat.get(etat, [])
        if not cles:
            continue
        print(f"\n{etat} : {len(cles)}")
        print("  " + ", ".join(sorted(cles)))

    print()
    print("LECTURE")
    print("  PRODUIT      -> a reactiver, elle marche")
    print("  FILTRE       -> elle voit des annonces mais n'en garde aucune :")
    print("                  filtre trop strict, ou aucune offre du profil")
    print("  AUCUNE_CIBLE -> la source va bien, elle n'a rien pour ce profil")
    print("  TROP_LENTE   -> delai depasse : relancer avec --timeout plus grand")
    print("  RESEAU       -> URL morte ou blocage")
    print("  MUETTE       -> pas instrumentee : son silence est ininterpretable,")
    print("                  c'est elle qu'il faut equiper de compteurs d'abord")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = LOG_DIR / f"source_silence_probe_{stamp}.json"
    chemin.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "version": PROBE_VERSION, "duree_s": round(duree, 1),
         "resultats": resultats}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nRapport : {chemin.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

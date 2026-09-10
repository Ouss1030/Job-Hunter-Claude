"""
JOB HUNTER BELGIUM
COMPARAISON VERDICT / SCORE - VERSION 1.0

    python -m diagnostics.verdict_vs_score
    python -m diagnostics.verdict_vs_score --limite 800
    python -m diagnostics.verdict_vs_score --desaccords 20

Pourquoi comparer avant de remplacer
------------------------------------
Le scoring historique rend un nombre et une recommandation. Le moteur de
verdict rend un etat lisible avec ses preuves. Remplacer l'un par l'autre
sans les avoir confrontes reviendrait a changer de jugement sans savoir ce
qu'on gagne ni ce qu'on perd.

Cet outil les fait tourner sur les MEMES offres et montre ou ils divergent.
Il n'ecrit rien : ni en base, ni dans le pipeline.

Les deux desaccords qui comptent
--------------------------------
SCORE GARDE / VERDICT FERME
    le score retient une offre que le verdict declare hors de portee.
    Si le verdict a raison, c'est du temps de candidature economise ;
    s'il a tort, c'est une offre perdue. A relire une par une.

SCORE ECARTE / VERDICT OUVRE
    le score a rejete une offre que rien ne ferme reellement. C'est le
    gisement recherche : des offres accessibles que le pipeline actuel
    ne montre jamais.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


COMPARAISON_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "database" / "jobs.db"
LOG_DIR = PROJECT_ROOT / "exports" / "logs"

# En dessous, le verdict repond INCONNU : comparer n'aurait pas de sens.
MIN_TEXTE = 300


def _offres(limite: int | None):
    con = sqlite3.connect(f"{DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    requete = (
        "SELECT * FROM raw_jobs WHERE is_active = 1 "
        f"AND LENGTH(COALESCE(detail_matching_text, description, '')) >= {MIN_TEXTE} "
        "ORDER BY rowid"
    )
    if limite:
        requete += f" LIMIT {int(limite)}"
    lignes = con.execute(requete).fetchall()
    con.close()
    return lignes


def comparer(limite: int | None = None) -> list[dict]:
    from diagnostics.detail_backfill import _reconstruire
    from matching.basic_matcher import score_job
    from matching.verdict import evaluer

    resultats = []
    for ligne in _offres(limite):
        texte = ligne["detail_matching_text"] or ligne["description"] or ""
        job = _reconstruire(ligne)
        setattr(job, "detail_matching_text", ligne["detail_matching_text"])

        try:
            note = score_job(job) or {}
        except Exception as exc:
            note = {"score": 0, "core_relevance": False,
                    "recommendation": f"ERREUR {type(exc).__name__}"}

        v = evaluer(texte)
        resultats.append({
            "titre": ligne["title"],
            "source": ligne["source"],
            "score": round(float(note.get("score") or 0), 1),
            "retenue_par_score": bool(note.get("core_relevance")),
            "famille": note.get("best_family") or "",
            "verdict": v.verdict,
            "barriere": v.barrieres[0].message if v.barrieres else "",
            "preuve": v.barrieres[0].preuve if v.barrieres else "",
            "atouts": v.atouts,
        })
    return resultats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Comparaison verdict / score")
    parser.add_argument("--limite", type=int)
    parser.add_argument("--desaccords", type=int, default=8,
                        help="Nombre d'exemples affiches par type de desaccord")
    args = parser.parse_args(argv)

    print("=" * 92)
    print(f"COMPARAISON VERDICT / SCORE V{COMPARAISON_VERSION}")
    print("=" * 92)
    print("  aucune ecriture : ni en base, ni dans le pipeline")
    print()

    r = comparer(args.limite)
    n = len(r)
    if not n:
        print("  Aucune offre avec assez de texte.")
        return 0

    croise = Counter((x["retenue_par_score"], x["verdict"]) for x in r)

    print(f"  {n} offres comparees")
    print()
    print(f"  {'':<22}{'ACCESSIBLE':>12}{'A_VERIFIER':>12}{'FERMEE':>10}")
    print("  " + "-" * 58)
    for garde, libelle in ((True, "score GARDE"), (False, "score ECARTE")):
        cells = "".join(
            f"{croise[(garde, v)]:>12}" if v != 'FERMEE'
            else f"{croise[(garde, v)]:>10}"
            for v in ("ACCESSIBLE", "A_VERIFIER", "FERMEE"))
        print(f"  {libelle:<22}{cells}")

    garde_ferme = [x for x in r if x["retenue_par_score"] and x["verdict"] == "FERMEE"]
    ecarte_ouvre = [x for x in r
                    if not x["retenue_par_score"] and x["verdict"] == "ACCESSIBLE"]
    ecarte_ouvre_atouts = [x for x in ecarte_ouvre if x["atouts"]]

    print()
    print("  DESACCORDS")
    print("  " + "-" * 58)
    print(f"  score GARDE  / verdict FERME  : {len(garde_ferme)}")
    print(f"  score ECARTE / verdict OUVRE  : {len(ecarte_ouvre)}")
    print(f"     dont avec vos competences  : {len(ecarte_ouvre_atouts)}")

    if garde_ferme:
        print()
        print("=" * 92)
        print("A. LE SCORE LES GARDE, LE VERDICT LES FERME")
        print("   Si le verdict a raison : du temps de candidature economise.")
        print("   S'il a tort : des offres perdues. A relire.")
        print("=" * 92)
        for x in sorted(garde_ferme, key=lambda y: -y["score"])[:args.desaccords]:
            print(f"\n  [{x['score']:>5}] {str(x['titre'])[:56]}  ({x['source']})")
            print(f"     {x['barriere']}")
            if x["preuve"]:
                print(f"     « {x['preuve'][:96]} »")

    if ecarte_ouvre_atouts:
        print()
        print("=" * 92)
        print("B. LE SCORE LES ECARTE, RIEN NE LES FERME")
        print("   Offres accessibles que le pipeline actuel ne montre jamais.")
        print("=" * 92)
        for x in ecarte_ouvre_atouts[:args.desaccords]:
            print(f"\n  [{x['score']:>5}] {str(x['titre'])[:56]}  ({x['source']})")
            print(f"     atouts : {', '.join(x['atouts'][:6])}")

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = LOG_DIR / f"verdict_vs_score_{stamp}.json"
    chemin.write_text(json.dumps(
        {"generated_at": datetime.now().isoformat(timespec="seconds"),
         "version": COMPARAISON_VERSION, "offres": n,
         "croise": {f"{k[0]}|{k[1]}": v for k, v in croise.items()},
         "score_garde_verdict_ferme": len(garde_ferme),
         "score_ecarte_verdict_ouvre": len(ecarte_ouvre),
         "detail": r}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  Rapport complet : {chemin.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

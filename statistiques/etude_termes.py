"""
JOB HUNTER BELGIUM
ETUDE DE TERMES - VERSION 1.0

    python -m statistiques.etude_termes              # toute la base (actives + retirees)
    python -m statistiques.etude_termes --actives    # offres actives seulement

Ce que demandent les offres LAB, DATA et PHARMA de Belgique, mesure sur le
texte de toutes les offres gardees en base (67 000 avec texte le 18/09/2026,
retirees comprises : c'est la raison d'etre de l'historique). Le calcul est
celui de statistiques/conseils.py (vocabulaires curates, frontieres de
mots) ; ce module ne fait que l'ecrire lisiblement, par famille et par
sous-categorie :

    outils, normes, methodes, qualites   ce qui revient, en % des offres
    langues                              exigence, et part qui demande un niveau fort
    diplome, experience, contrats        ce qui est cite
    salaire                              quand l'annonce en donne un
    employeurs, villes, sources          qui, ou, par quel canal
    vous avez / vous manque              croisement avec config/candidate_truth.py

Sorties : exports/logs/etude_termes_<date>.txt et .csv (une ligne par
famille x rubrique x terme, pour Excel). Le JSON complet est aussi ecrit
sous le nom qu'attend l'interface web (conseils_marche_<run>.json), qui le
relit sans recalcul.

Precaution de lecture (voir conseils.py) : des MENTIONS, pas des exigences.
Le classement est fiable, les valeurs absolues surestiment.
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from datetime import datetime
from pathlib import Path

from statistiques import conseils as C


ETUDE_TERMES_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
RUBRIQUES = ("outils", "normes", "methodes", "qualites", "diplomes", "contrats", "employeurs", "villes", "sources")


def _ligne_classement(x: dict) -> str:
    return f"  {x['offres']:>6} offres  {x['part']:>5.1f} %   {x['nom']}"


def _bloc(titre: str, r: dict) -> list[str]:
    n = r["offres"]
    out = [f"{titre}  —  {n} offres", "-" * 78]
    if not n:
        out.append("  (aucune offre)")
        return out
    for rub, lib in (("outils", "OUTILS ET SYSTEMES"), ("normes", "NORMES ET REFERENTIELS"),
                     ("methodes", "METHODES ET SAVOIR-FAIRE"), ("qualites", "QUALITES ATTENDUES")):
        out.append(f"\n  {lib}")
        for x in r.get(rub, [])[:12]:
            out.append("  " + _ligne_classement(x))
    out.append("\n  LANGUES (part des offres qui la citent ; entre parentheses, niveau fort demande)")
    for l in r.get("langues", []):
        out.append(f"    {l['offres']:>6} offres  {l['part']:>5.1f} %   {l['nom']}  (niveau fort : {l['niveau_fort']})")
    out.append("\n  DIPLOME CITE")
    for x in r.get("diplomes", []):
        out.append("  " + _ligne_classement(x))
    e = r.get("experience") or {}
    if e.get("offres_avec_exigence"):
        rep = ", ".join(f"{k} an{'s' if k > 1 else ''}: {v}" for k, v in (e.get("repartition") or {}).items())
        out.append(f"\n  EXPERIENCE : {e['offres_avec_exigence']} offres chiffrent une exigence ; mediane {e['mediane_ans']} ans  [{rep}]")
    out.append("\n  CONTRATS")
    for x in r.get("contrats", []):
        out.append("  " + _ligne_classement(x))
    s = r.get("salaire") or {}
    if s.get("offres_avec_montant"):
        out.append(f"\n  SALAIRE : {s['offres_avec_montant']} offres donnent un montant ; mediane {s['mediane_brut_mensuel']} EUR brut/mois, quartiles {s.get('quartiles')}")
    for rub, lib in (("employeurs", "EMPLOYEURS QUI RECRUTENT LE PLUS"), ("villes", "VILLES"), ("sources", "CANAUX")):
        out.append(f"\n  {lib}")
        for x in r.get(rub, [])[:10]:
            out.append("  " + _ligne_classement(x))
    h = r.get("historique") or {}
    if h:
        out.append(f"\n  HISTORIQUE : {h.get('actives', 0)} actives, {h.get('retirees', 0)} retirees conservees")
    out.append("\n  VOUS AVEZ (demande, et declare dans candidate_truth) :")
    out.append("    " + (", ".join(f"{x['nom']} ({x['part']} %)" for x in r.get("a_valoriser", [])[:15]) or "—"))
    out.append("  VOUS MANQUE (demande, non declare — par frequence) :")
    out.append("    " + (", ".join(f"{x['nom']} ({x['part']} %)" for x in r.get("a_acquerir", [])[:15]) or "—"))
    return out


def rendre_txt(res: dict, actives_seulement: bool) -> str:
    out = ["=" * 78, f"ETUDE DE TERMES V{ETUDE_TERMES_VERSION}  —  {datetime.now():%d/%m/%Y %H:%M}", "=" * 78,
           f"Offres en base : {res['offres_scrapees']}   |   ciblees (LAB / DATA / PHARMA) : {res['offres_cibles']}"
           f"   |   hors cible : {res['hors_cible']}   |   perimetre : {'actives seulement' if actives_seulement else 'actives + retirees'}",
           "Mesure : mentions dans le texte, pas exigences formelles. Classement fiable, valeurs absolues surestimees.", ""]
    out += _bloc("ENSEMBLE DES OFFRES CIBLEES", res["ensemble"]) + [""]
    for f, bf in res["familles"].items():
        out += ["", "#" * 78, f"# {bf['libelle']}", "#" * 78] + _bloc(bf["libelle"], bf) + [""]
        for c, bc in (bf.get("sous_categories") or {}).items():
            out += [""] + _bloc("   > " + bc["libelle"], bc) + [""]
    return "\n".join(out)


def rendre_csv(res: dict, chemin: Path) -> None:
    with chemin.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["famille", "sous_categorie", "rubrique", "terme", "offres", "part_pct"])
        def bloc(fam, sous, r):
            for rub in RUBRIQUES:
                for x in r.get(rub, []):
                    w.writerow([fam, sous, rub, x["nom"], x["offres"], x["part"]])
            for l in r.get("langues", []):
                w.writerow([fam, sous, "langues", l["nom"], l["offres"], l["part"]])
                w.writerow([fam, sous, "langues_niveau_fort", l["nom"], l["niveau_fort"], ""])
            for x in r.get("a_acquerir", []):
                w.writerow([fam, sous, "vous_manque", x["nom"], x["offres"], x["part"]])
            for x in r.get("a_valoriser", []):
                w.writerow([fam, sous, "vous_avez", x["nom"], x["offres"], x["part"]])
        bloc("ENSEMBLE", "", res["ensemble"])
        for fam, bf in res["familles"].items():
            bloc(fam, "", bf)
            for c, bc in (bf.get("sous_categories") or {}).items():
                bloc(fam, c, bc)


def _dernier_run() -> str:
    try:
        con = sqlite3.connect(f"{C.DB_PATH.resolve().as_uri()}?mode=ro", uri=True)
        row = con.execute("SELECT run_id FROM collection_runs ORDER BY rowid DESC LIMIT 1").fetchone()
        con.close()
        return str(row[0] if row else "aucun").replace(":", "-")
    except Exception:
        return "aucun"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--actives", action="store_true", help="offres actives seulement (defaut : toute la base)")
    args = p.parse_args()
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    debut = datetime.now()
    if args.actives:
        charger = C._charger
        C._charger = lambda chemin: [o for o in charger(chemin) if o.get("is_active")]
    res = C.analyser()
    if args.actives:
        C._charger = charger
    if "erreur" in res:
        print("[FAIL]", res["erreur"])
        return 1
    horodatage = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt = LOG_DIR / f"etude_termes_{horodatage}.txt"
    csv_ = LOG_DIR / f"etude_termes_{horodatage}.csv"
    txt.write_text(rendre_txt(res, args.actives), encoding="utf-8")
    rendre_csv(res, csv_)
    if not args.actives:
        js = LOG_DIR / f"conseils_marche_{_dernier_run()}.json"
        js.write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
    print(f"Offres en base {res['offres_scrapees']} | ciblees {res['offres_cibles']} | hors cible {res['hors_cible']} "
          f"| {(datetime.now() - debut).total_seconds():.0f} s")
    print(f"TXT : {txt}\nCSV : {csv_}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

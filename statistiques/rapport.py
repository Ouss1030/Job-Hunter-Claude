"""
JOB HUNTER BELGIUM
RAPPORT STATISTIQUE - VERSION 1.0

    python -m statistiques.rapport
    python -m statistiques.rapport --limite 800     (apercu rapide)

Rassemble les trois mesures en un seul texte lisible. Aucun reseau, aucune
ecriture en base : le rapport est ecrit dans exports/logs.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from statistiques import STATISTIQUES_VERSION
from statistiques.candidatures import analyser_candidatures
from statistiques.marche import analyser_marche
from statistiques.pipeline import (
    entonnoir_par_run,
    evolution,
    rendement_des_sources,
)


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"


def _tableau(lignes: list[dict], titre: str, colonne: str = "nom") -> list[str]:
    sortie = [titre, "-" * 78]
    if not lignes:
        sortie.append("  (rien de significatif)")
        return sortie
    for x in lignes:
        sortie.append(f"  {x['offres']:>5} offres  {x['part']:>5.1f} %   "
                      f"{str(x[colonne])[:50]}")
    return sortie


def construire(limite: int | None = None) -> list[str]:
    out = ["=" * 78,
           f"RAPPORT STATISTIQUE V{STATISTIQUES_VERSION}",
           f"{datetime.now():%Y-%m-%d %H:%M}",
           "=" * 78, ""]

    # ---------------------------------------------------------- marche
    marche = analyser_marche(limite=limite)
    if "erreur" in marche:
        out.append(f"MARCHE : {marche['erreur']}")
    else:
        out += [
            "1. LE MARCHE ACCESSIBLE",
            "=" * 78,
            f"  Offres actives analysees : {marche['offres_actives']}",
            f"  Offres sans barriere     : {marche['offres_ouvertes']}",
            f"  Verdicts                 : {marche['verdicts']}",
            "",
            "  Rappel : ces comptages mesurent des MENTIONS dans le texte,",
            "  pas des exigences formelles. Le classement relatif tient ;",
            "  les valeurs absolues surestiment.",
            "",
        ]
        out += _tableau(marche["a_acquerir"],
                        "  A ACQUERIR — ce qui ouvrirait le plus de portes")
        out.append("")
        out += _tableau(marche["a_valoriser"],
                        "  A VALORISER — ce qui vous sert deja le plus")
        out.append("")
        out += _tableau(marche["employeurs"], "  QUI RECRUTE")
        out.append("")
        out += _tableau(marche["lieux"], "  OU")
        out.append("")

    # -------------------------------------------------------- pipeline
    lignes = entonnoir_par_run()
    out += ["", "2. L'ENTONNOIR, RUN APRES RUN", "=" * 78]
    if not lignes:
        out.append("  (aucun artefact de file disponible)")
    else:
        out.append(f"  {'QUAND':<17}{'FILE':>6}{'PRETES':>8}{'TENSION':>9}"
                   f"{'VERIF':>7}{'ECART':>7}{'POOL':>6}")
        for x in lignes:
            out.append(
                f"  {x['quand']:<17}{x['file']:>6}{x['pretes']:>8}"
                f"{x['a_tension']:>9}{x['a_verifier']:>7}{x['ecartees']:>7}"
                f"{(x['pool'] if x['pool'] is not None else '-'):>6}")
        ecart = evolution(lignes)
        if ecart:
            out += ["", f"  Evolution sur {ecart['runs']} runs "
                        f"({ecart['depuis']} -> {ecart['jusqu_a']})"]
            for champ, v in ecart["ecarts"].items():
                signe = "+" if v["delta"] >= 0 else ""
                out.append(f"    {champ:<12}{v['avant']:>6} -> {v['apres']:<6}"
                           f"  {signe}{v['delta']}")

    sources = rendement_des_sources()
    if sources:
        out += ["", "  RENDEMENT REEL DES SOURCES (dernier run)",
                "  " + "-" * 76,
                f"  {'SOURCE':<24}{'OFFRES':>8}{'PRETES':>8}{'RENDEMENT':>11}"]
        for x in sources[:12]:
            if x["offres"] < 2:
                continue
            out.append(f"  {x['source'][:22]:<24}{x['offres']:>8}"
                       f"{x['pretes']:>8}{x['rendement']:>10.1f} %")

    # ---------------------------------------------------- candidatures
    cand = analyser_candidatures()
    out += ["", "", "3. LES CANDIDATURES", "=" * 78]
    if cand.get("etat") == "AUCUNE_CANDIDATURE_ENVOYEE":
        out += [f"  {cand['message']}",
                f"  Dossiers suivis : {cand['dossiers_suivis']}",
                f"  Evenements      : {cand['evenements']}"]
    elif "erreur" in cand:
        out.append(f"  {cand['erreur']}")
    else:
        out += [f"  Envoyees          : {cand['envoyees']}",
                f"  Avec retour       : {cand['avec_retour']}",
                f"  Taux de reponse   : {cand['taux_de_reponse']} %",
                f"  Delai median      : {cand['delai_median_jours']} jours",
                f"  Par filiere       : {cand['par_filiere']}"]

    out += ["", "=" * 78]
    return out


def main() -> None:
    parseur = argparse.ArgumentParser()
    parseur.add_argument("--limite", type=int, default=None,
                         help="n'analyser que N offres (apercu rapide)")
    args = parseur.parse_args()

    texte = "\n".join(construire(limite=args.limite))
    print(texte)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chemin = LOG_DIR / f"rapport_statistique_{stamp}.txt"
    chemin.write_text(texte, encoding="utf-8")
    print("\nTXT :", chemin)


if __name__ == "__main__":
    main()

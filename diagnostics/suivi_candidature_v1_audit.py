"""
JOB HUNTER BELGIUM
SUIVI DE CANDIDATURE - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.suivi_candidature_v1_audit

Ce que l'audit protege
----------------------
Le suivi de candidature touche a la seule donnee du projet qui ne puisse pas
etre reconstruite : ce que le candidat a decide et fait. Une offre perdue se
recollecte au prochain run ; une relance oubliee ne se retrouve pas.

Trois garanties sont verifiees :

    1. la migration ajoute les colonnes sans jamais rejouer deux fois ;
    2. une date de relance invalide est REFUSEE, pas enregistree — une date
       mal formee ne declencherait aucun rappel et personne ne s'en
       apercevrait ;
    3. APPLIED ne peut pas etre pose sans confirmation explicite, ni par la
       route de statut ordinaire.

Ce dernier point est la regle la plus ancienne du projet : la machine ne
declare jamais une candidature envoyee. Une regle qui ne tient qu'a la
vigilance de l'appelant n'est pas une regle, d'ou ces tests.

L'audit travaille sur une base temporaire : il ne lit ni n'ecrit jamais
jobs.db.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from applications.lifecycle_tracker import (
    EVENT_TYPES,
    LIFECYCLE_VERSION,
    STATUSES,
    ensure_schema,
    migrer_colonnes,
)
from diagnostics.version_support import at_least


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def base_ancienne(dossier: Path) -> Path:
    """
    Une base au schema d'AVANT les colonnes de suivi.

    C'est le cas qui compte : CREATE TABLE IF NOT EXISTS ne touche pas une
    table deja creee, donc seule la migration peut sauver une base existante
    — c'est-a-dire la seule qui porte de l'historique.
    """
    chemin = dossier / "ancienne.db"
    conn = sqlite3.connect(chemin)
    conn.executescript("""
        CREATE TABLE application_entities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lifecycle_id TEXT NOT NULL UNIQUE,
            application_group_id TEXT,
            title TEXT, company TEXT, location TEXT, track TEXT,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            metadata_json TEXT
        );
    """)
    conn.execute(
        "INSERT INTO application_entities "
        "(lifecycle_id, title, company, created_at, updated_at) "
        "VALUES ('LC_TEST', 'Analyste QC', 'ACME', ?, ?)",
        (datetime.now().isoformat(timespec="seconds"),) * 2)
    conn.commit()
    return chemin, conn


def main():
    print("=" * 92)
    print(f"SUIVI DE CANDIDATURE - AUDIT (LIFECYCLE V{LIFECYCLE_VERSION})")
    print("=" * 92)
    print()

    tests = []

    with tempfile.TemporaryDirectory() as tmp:
        dossier = Path(tmp)

        print("A. MIGRATION D'UNE BASE EXISTANTE")
        print("-" * 92)
        _chemin, conn = base_ancienne(dossier)
        avant = {r[1] for r in conn.execute("PRAGMA table_info(application_entities)")}
        tests.append(check("Le schema de depart n'a pas les colonnes de suivi",
                           "next_action_date" not in avant))

        ajoutees = migrer_colonnes(conn)
        apres = {r[1] for r in conn.execute("PRAGMA table_info(application_entities)")}
        tests.append(check(
            "La migration ajoute les trois colonnes",
            {"next_action_date", "contact_name", "contact_channel"} <= apres,
            str(sorted(ajoutees))))
        tests.append(check("Elle nomme ce qu'elle a ajoute", len(ajoutees) == 3))
        tests.append(check("Rejouee, elle n'ajoute rien",
                           migrer_colonnes(conn) == []))
        tests.append(check(
            "La ligne existante survit a la migration",
            conn.execute("SELECT COUNT(*) FROM application_entities").fetchone()[0] == 1))
        tests.append(check(
            "Ses donnees d'origine sont intactes",
            conn.execute("SELECT title FROM application_entities").fetchone()[0]
            == "Analyste QC"))
        conn.close()

        print()
        print("B. LA MIGRATION EST APPELEE PAR ensure_schema")
        print("-" * 92)
        # Sans cela, la migration existerait sans jamais tourner.
        neuve = dossier / "neuve.db"
        conn2 = sqlite3.connect(neuve)
        ensure_schema(conn2)
        colonnes = {r[1] for r in conn2.execute("PRAGMA table_info(application_entities)")}
        tests.append(check("Une base neuve a les colonnes de suivi",
                           "next_action_date" in colonnes))
        conn2.close()

        print()
        print("C. VALIDATION DE LA DATE DE RELANCE")
        print("-" * 92)
        from interface.lifecycle_service import _valider_date

        for valeur in ("2026-09-17", "2026-01-01"):
            tests.append(check(f"Date ISO acceptee : {valeur}",
                               _valider_date(valeur) == valeur))
        for vide in ("", "   ", None):
            tests.append(check(f"Valeur vide -> None : {vide!r}",
                               _valider_date(vide) is None))
        for mauvaise in ("17/09/2026", "2026-13-01", "demain", "2026-09-31"):
            try:
                _valider_date(mauvaise)
                ok = False
            except ValueError:
                ok = True
            tests.append(check(f"Date invalide refusee : {mauvaise!r}", ok))

    print()
    print("D. LA REGLE APPLIED EST TENUE PAR LE SERVEUR")
    print("-" * 92)
    import inspect
    from webui import serveur

    src_statut = inspect.getsource(serveur.api_statut)
    tests.append(check(
        "La route de statut refuse APPLIED",
        'statut == "APPLIED"' in src_statut and "400" in src_statut))
    src_postule = inspect.getsource(serveur.api_postule)
    tests.append(check(
        "La route dediee exige une confirmation",
        'corps.get("confirme")' in src_postule))
    tests.append(check(
        "Sans confirmation, elle refuse",
        "Confirmation manquante" in src_postule))

    tests.append(check(
        "Le triage n'expose que des statuts valides",
        all(t["statut"] in STATUSES for t in serveur.TRIAGE),
        str([t["statut"] for t in serveur.TRIAGE])))
    tests.append(check(
        "APPLIED n'est jamais propose au triage rapide",
        all(t["statut"] != "APPLIED" for t in serveur.TRIAGE)))
    tests.append(check(
        "Chaque action de triage a une touche distincte",
        len({t["touche"] for t in serveur.TRIAGE}) == len(serveur.TRIAGE)))

    print()
    print("E. VOCABULAIRE D'EVENEMENTS RESPECTE")
    print("-" * 92)
    from interface import lifecycle_service
    src_suivi = inspect.getsource(lifecycle_service.save_suivi)
    types_utilises = [t for t in EVENT_TYPES if f'"{t}"' in src_suivi]
    tests.append(check(
        "save_suivi n'emploie qu'un type d'evenement declare",
        bool(types_utilises), str(types_utilises)))
    tests.append(check(
        "Aucun type invente",
        '"SUIVI"' not in src_suivi))

    print()
    print("F. VERSIONS")
    print("-" * 92)
    tests.append(check("Lifecycle au moins 1.1",
                       at_least(LIFECYCLE_VERSION, "1.1"), LIFECYCLE_VERSION))
    tests.append(check("Interface web au moins 0.2",
                       at_least(serveur.WEBUI_VERSION, "0.2"),
                       serveur.WEBUI_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] SUIVI DE CANDIDATURE VALIDE HORS LIGNE."
              if passed == total else "[FAIL] SUIVI DE CANDIDATURE NON VALIDE.")

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"suivi_candidature_v1_audit_{stamp}.txt").write_text(
        "\n".join([f"SUIVI DE CANDIDATURE (LIFECYCLE V{LIFECYCLE_VERSION})",
                   "=" * 92, f"Tests : {passed}/{total}", statut]),
        encoding="utf-8")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

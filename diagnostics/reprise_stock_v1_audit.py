"""
JOB HUNTER BELGIUM
REPRISE DU STOCK ACTIF - AUDIT HORS LIGNE - VERSION 1.0

    python -m diagnostics.reprise_stock_v1_audit

Ce que l'audit protege
----------------------
La reprise du stock fait entrer dans le circuit de notation des offres qui
n'ont pas ete collectees par le run en cours. Trois choses peuvent mal
tourner, et chacune est testee ici :

    1. reprendre une offre morte — on proposerait un poste qui n'existe plus
    2. reprendre une offre deja collectee — on la noterait deux fois, et le
       representant canonique pourrait etre la version perimee
    3. rendre un objet incomplet — le gate lit des attributs que les
       connecteurs posent ; s'ils manquent, le gate juge sur du vide

L'audit construit sa propre base temporaire. Il ne lit pas jobs.db : un test
dont le resultat depend du contenu du jour ne prouve rien.
"""

from __future__ import annotations

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

from database.reprise_stock import (
    REPRISE_STOCK_VERSION,
    charger_stock_actif,
    cles_de_collecte,
)
from diagnostics.version_support import at_least


LOG_DIR = Path(__file__).resolve().parents[1] / "exports" / "logs"

# Attributs que le gate et la file lisent sur un objet offre. Les perdre ne
# provoque pas d'erreur : cela fait juger l'offre sur du vide, ce qui est
# pire, donc on les verifie nommement.
ATTRIBUTS_ATTENDUS = (
    "source", "external_id", "title", "company", "location", "description",
    "url", "collection_channel", "origin_source", "detail_matching_text",
    "detail_enrichment_success", "degree_requirement",
    "experience_requirement", "restriction_text",
    "source_eligibility_status", "contract_type", "language",
)


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def base_de_test(dossier: Path) -> Path:
    """Petite base autonome : trois offres actives, une inactive."""
    chemin = dossier / "stock_test.db"
    connexion = sqlite3.connect(chemin)
    colonnes = ", ".join(f"{nom} TEXT" for nom in (
        "collection_channel", "origin_source", "source", "source_external_id",
        "title", "company", "location", "description", "url",
        "date_published", "contract_type", "language", "salary",
        "date_collected", "first_seen", "last_seen",
        "detail_enrichment_attempted", "detail_enrichment_success",
        "detail_matching_text", "detail_matching_text_length",
        "detail_from_cache", "detail_enrichment_error",
        "degree_requirement", "experience_requirement",
        "application_deadline", "restriction_text",
        "source_eligibility_status", "source_eligibility_reason",
    ))
    connexion.execute(
        f"CREATE TABLE raw_jobs (id INTEGER PRIMARY KEY, is_active INTEGER, "
        f"{colonnes})")

    def inserer(ident, actif, canal, externe, titre, texte=""):
        connexion.execute(
            "INSERT INTO raw_jobs (id, is_active, collection_channel, "
            "origin_source, source, source_external_id, title, company, "
            "location, description, url, detail_matching_text, "
            "source_eligibility_status) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (ident, actif, canal, canal, canal, externe, titre, "Societe",
             "1000 Bruxelles", "Description de test.",
             f"https://example.invalid/{externe}", texte, "ELIGIBLE"))

    inserer(1, 1, "FOREM", "AAA", "Technicien de laboratoire", "Texte long.")
    inserer(2, 1, "ACTIRIS", "BBB", "Analyste QC")
    inserer(3, 1, "FOREM", "CCC", "Laborantin")
    inserer(4, 0, "FOREM", "DDD", "Offre fermee depuis longtemps")
    connexion.commit()
    connexion.close()
    return chemin


def main():
    print("=" * 92)
    print(f"REPRISE DU STOCK ACTIF V{REPRISE_STOCK_VERSION} - AUDIT HORS LIGNE")
    print("=" * 92)
    print()

    tests = []

    with tempfile.TemporaryDirectory() as dossier:
        chemin = base_de_test(Path(dossier))

        print("A. CE QUI EST REPRIS, ET CE QUI NE L'EST PAS")
        print("-" * 92)
        toutes = charger_stock_actif(chemin_base=chemin)
        tests.append(check("Les trois offres actives sont reprises",
                           len(toutes) == 3, str(len(toutes))))
        tests.append(check(
            "L'offre inactive n'est JAMAIS reprise",
            all("fermee" not in (o.title or "").lower() for o in toutes),
            ", ".join(o.title[:22] for o in toutes)))

        print()
        print("B. PAS DE DOUBLE NOTATION AVEC LA RECOLTE")
        print("-" * 92)
        restant = charger_stock_actif({("FOREM", "AAA")}, chemin_base=chemin)
        tests.append(check("Une offre deja collectee est ecartee",
                           len(restant) == 2, str(len(restant))))
        tests.append(check(
            "Et c'est bien la bonne qui est ecartee",
            all(o.external_id != "AAA" for o in restant)))
        tests.append(check(
            "Toutes ecartees : la reprise rend une liste vide",
            charger_stock_actif(
                {("FOREM", "AAA"), ("ACTIRIS", "BBB"), ("FOREM", "CCC")},
                chemin_base=chemin) == []))
        tests.append(check(
            "Une cle inconnue n'ecarte rien",
            len(charger_stock_actif({("FOREM", "ZZZ")},
                                    chemin_base=chemin)) == 3))

        print()
        print("C. L'OBJET RENDU EST COMPLET")
        print("-" * 92)
        offre = [o for o in toutes if o.external_id == "AAA"][0]
        manquants = [a for a in ATTRIBUTS_ATTENDUS if not hasattr(offre, a)]
        tests.append(check("Tous les attributs lus en aval sont presents",
                           not manquants, ", ".join(manquants) or "aucun manque"))
        tests.append(check("external_id vient de source_external_id",
                           offre.external_id == "AAA", offre.external_id))
        tests.append(check("Le texte enrichi est conserve",
                           offre.detail_matching_text == "Texte long."))
        tests.append(check("La provenance est marquee",
                           getattr(offre, "reprise_du_stock", False) is True))

        print()
        print("D. ROBUSTESSE")
        print("-" * 92)
        tests.append(check(
            "Base introuvable : liste vide, pas d'exception",
            charger_stock_actif(chemin_base=Path(dossier) / "absente.db") == []))
        tests.append(check("Aucune cle fournie : rien n'est ecarte",
                           len(charger_stock_actif(None, chemin_base=chemin)) == 3))

    print()
    print("E. CONSTRUCTION DES CLES DE COLLECTE")
    print("-" * 92)

    class _Offre:
        def __init__(self, canal, externe, source="X"):
            self.collection_channel = canal
            self.external_id = externe
            self.source = source

    cles = cles_de_collecte([_Offre("forem", "AAA"), _Offre("ACTIRIS", "BBB")])
    tests.append(check("Le canal est normalise en majuscules",
                       ("FOREM", "AAA") in cles, str(sorted(cles))))
    tests.append(check("Liste vide : ensemble vide, pas d'exception",
                       cles_de_collecte([]) == set()))
    tests.append(check("None accepte sans planter",
                       cles_de_collecte(None) == set()))

    class _Partielle:
        source = "FOREM"
        external_id = "EEE"

    tests.append(check(
        "Sans collection_channel, la source sert de canal",
        ("FOREM", "EEE") in cles_de_collecte([_Partielle()])))

    print()
    print("F. BRANCHEMENT DANS LA CHAINE")
    print("-" * 92)
    import inspect
    import main as chaine
    tests.append(check("main expose l'interrupteur de reprise",
                       hasattr(chaine, "REPRISE_STOCK_ACTIVE")))
    tests.append(check("La reprise est appelee dans le pipeline",
                       "reprendre_le_stock_actif(raw_scored)"
                       in inspect.getsource(chaine)))
    source_reprise = inspect.getsource(chaine.reprendre_le_stock_actif)
    tests.append(check("L'interrupteur coupe reellement la reprise",
                       "if not REPRISE_STOCK_ACTIVE" in source_reprise))
    tests.append(check(
        "Le meme filtre de pertinence que la recolte fraiche",
        "core_relevance" in source_reprise))
    tests.append(check(
        "Une offre du stock ne peut pas casser le run",
        "except Exception" in source_reprise))

    tests.append(check("Version au moins 1.0",
                       at_least(REPRISE_STOCK_VERSION, "1.0"),
                       REPRISE_STOCK_VERSION))

    passed = sum(1 for x in tests if x)
    total = len(tests)
    statut = ("[PASS] REPRISE DU STOCK VALIDEE HORS LIGNE."
              if passed == total else "[FAIL] REPRISE DU STOCK NON VALIDEE.")

    print()
    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)
    print(statut)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"reprise_stock_v1_audit_{stamp}.txt").write_text(
        "\n".join([f"REPRISE DU STOCK V{REPRISE_STOCK_VERSION}", "=" * 92,
                   f"Tests : {passed}/{total}", statut]),
        encoding="utf-8")

    if passed != total:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

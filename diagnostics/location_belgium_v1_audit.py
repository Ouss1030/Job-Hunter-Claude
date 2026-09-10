"""
JOB HUNTER BELGIUM
DÉTECTION DE LOCALISATION BELGE - AUDIT V1.0

    python -m diagnostics.location_belgium_v1_audit

Aucun réseau. Aucune base. Aucun fichier modifié.

Ce diagnostic existe surtout pour les cas pièges. La détection naïve
("be" in texte) produirait Berlin, Bern et Aberdeen comme villes belges :
c'est la même erreur que le regex V.I.E qui lisait le mot français "vie".
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sources.location_belgium import (
    BE_CONFIRMED,
    BE_EXCLUDED,
    BE_LIKELY,
    BE_UNKNOWN,
    LOCATION_DETECTOR_VERSION,
    analyze_location,
    detect_belgium,
    is_belgium_candidate,
)


LOG_DIR = Path(__file__).resolve().parent.parent / "exports" / "logs"


# ------------------------------------------------------------------
# A. Pays belge explicitement nommé
# ------------------------------------------------------------------
CAS_CONFIRMED = [
    ("Brussels, Belgium", "anglais"),
    ("Bruxelles, Belgique", "français"),
    ("Brussel, België", "néerlandais avec accent"),
    ("Gent, Belgie", "néerlandais sans accent"),
    ("Belgium - Remote", "télétravail belge"),
    ("Ghent, BE", "code pays en fin"),
    ("Wavre (BE)", "code pays entre parenthèses"),
    ("Zaventem - BE", "code pays après tiret"),
    ("Antwerp, BE, Europe", "code pays encadré"),
]

# ------------------------------------------------------------------
# B. Ville ou région belge, sans mention du pays
# ------------------------------------------------------------------
CAS_LIKELY = [
    ("Wavre", "ville wallonne"),
    ("Zaventem", "périphérie bruxelloise"),
    ("Anderlecht", "commune bruxelloise"),
    ("Louvain-la-Neuve", "ville composée"),
    ("Gent", "ville flamande"),
    ("Liège", "accent"),
    ("Charleroi", "ville wallonne"),
    ("Braine-l'Alleud", "apostrophe et tirets"),
    ("Brabant Wallon", "province"),
    ("Vlaanderen", "région"),
    ("Province de Luxembourg", "province belge homonyme d'un pays"),
    ("Arlon, Luxembourg", "province levée par une ville belge"),
]

# ------------------------------------------------------------------
# C. Pièges — la raison d'être de ce module
# ------------------------------------------------------------------
CAS_PIEGES = [
    # "be" en sous-chaîne ne doit jamais déclencher la Belgique.
    ("Berlin, Germany", BE_EXCLUDED, "Berlin commence par 'be'"),
    ("Bern, Switzerland", BE_EXCLUDED, "Bern commence par 'be'"),
    ("Aberdeen, United Kingdom", BE_EXCLUDED, "'be' au milieu du mot"),
    ("Beverly Hills, USA", BE_EXCLUDED, "'be' en début de mot"),
    ("Bergamo, Italy", BE_EXCLUDED, "'be' en début de mot"),
    ("Besancon, France", BE_EXCLUDED, "'be' en début de mot"),
    # Luxembourg seul = le pays, pas la province belge.
    ("Luxembourg", BE_EXCLUDED, "pays voisin homonyme"),
    ("Luxembourg City", BE_EXCLUDED, "capitale du Grand-Duché"),
    # Homonymes de villes belges à l'étranger : le pays étranger tranche.
    ("Bruges, France", BE_EXCLUDED, "homonyme français"),
    ("Waterloo, Canada", BE_EXCLUDED, "homonyme canadien"),
    ("Namur, Philippines", BE_EXCLUDED, "homonyme lointain"),
    # Un pays belge nommé l'emporte sur une seconde localisation.
    ("Brussels, Belgium / Paris, France", BE_CONFIRMED,
     "Belgique nommée explicitement"),
]

# ------------------------------------------------------------------
# D. Aucun signal exploitable
# ------------------------------------------------------------------
CAS_UNKNOWN = [
    ("EMEA", "zone continentale"),
    ("Remote", "sans lieu"),
    ("Europe", "continent"),
    ("", "chaîne vide"),
    (None, "valeur nulle"),
    ("   ", "espaces seulement"),
    ("Worldwide", "mondial"),
]


def check(label, condition, detail=""):
    print(f"{'[PASS]' if condition else '[FAIL]'} {label}"
          + (f" | {detail}" if detail else ""))
    return bool(condition)


def bloc(titre, cas, attendu):
    print(titre)
    print("-" * 92)
    resultats = []
    for entree, note in cas:
        obtenu = detect_belgium(entree)
        resultats.append(check(
            f"{str(entree)[:44]:<46} -> {attendu}",
            obtenu == attendu,
            f"obtenu={obtenu} ({note})" if obtenu != attendu else note,
        ))
    print()
    return resultats


def main():
    print("=" * 92)
    print(f"DÉTECTION LOCALISATION BELGE V{LOCATION_DETECTOR_VERSION} - AUDIT")
    print("=" * 92)
    print()

    tests = []
    tests += bloc("A. PAYS BELGE EXPLICITE", CAS_CONFIRMED, BE_CONFIRMED)
    tests += bloc("B. VILLE OU RÉGION BELGE SANS PAYS", CAS_LIKELY, BE_LIKELY)

    print("C. PIÈGES")
    print("-" * 92)
    for entree, attendu, note in CAS_PIEGES:
        obtenu = detect_belgium(entree)
        tests.append(check(
            f"{str(entree)[:44]:<46} -> {attendu}",
            obtenu == attendu,
            f"obtenu={obtenu} ({note})" if obtenu != attendu else note,
        ))
    print()

    tests += bloc("D. AUCUN SIGNAL", CAS_UNKNOWN, BE_UNKNOWN)

    # ------------------------------------------------------------------
    # E. Comportement de conservation
    # ------------------------------------------------------------------
    print("E. RÈGLE DE CONSERVATION")
    print("-" * 92)
    tests.append(check(
        "Une localisation belge est conservée",
        is_belgium_candidate("Brussels, Belgium"),
    ))
    tests.append(check(
        "Une ville belge probable est conservée",
        is_belgium_candidate("Wavre"),
    ))
    tests.append(check(
        "Un pays étranger est écarté",
        not is_belgium_candidate("Berlin, Germany"),
    ))
    tests.append(check(
        "Une localisation inconnue est conservée par défaut",
        is_belgium_candidate("EMEA"),
        "principe conservateur : pas d'exclusion sur un doute",
    ))
    tests.append(check(
        "Une localisation inconnue peut être écartée sur demande",
        not is_belgium_candidate("EMEA", include_unknown=False),
    ))
    print()

    # ------------------------------------------------------------------
    # F. Détail exploitable
    # ------------------------------------------------------------------
    print("F. DÉTAIL D'ANALYSE")
    print("-" * 92)
    detail = analyze_location("Ghent, BE")
    tests.append(check(
        "analyze_location expose le code pays",
        detail["country_code"] is True and detail["status"] == BE_CONFIRMED,
        str({k: detail[k] for k in ("status", "country_code")}),
    ))
    detail = analyze_location("Berlin, Germany")
    tests.append(check(
        "analyze_location nomme le pays étranger",
        detail["foreign_country"] == "germany",
        str(detail["foreign_country"]),
    ))
    detail = analyze_location("3560, Belgique")
    tests.append(check(
        "analyze_location extrait le code postal et la province",
        detail["postal_code"] == "3560" and detail["province"] == "Limbourg",
        f"{detail['postal_code']} / {detail['province']}",
    ))
    detail = analyze_location("Berlin 10115, Germany")
    tests.append(check(
        "Un code postal étranger n'est pas lu comme belge",
        detail["postal_code"] is None and detail["status"] == BE_EXCLUDED,
        str(detail["postal_code"]),
    ))
    # Un code postal seul ne suffit plus depuis la V1.1 : tout nombre à
    # quatre chiffres lui ressemble ("Building 2000", "Room 4500, Basel").
    # Mesuré sur les 5 430 localisations réelles de la base, 4 offres
    # seulement reposaient sur ce seul signal — et les quatre étaient
    # étrangères ("9999, PL", "9999, FR"). La province reste extraite : elle
    # est utile à l'appelant, elle ne décide simplement plus seule.
    detail = analyze_location("1000")
    tests.append(check(
        "Un code postal seul ne suffit pas, mais donne la province",
        detail["status"] == BE_UNKNOWN and detail["province"] == "Bruxelles",
        f"{detail['status']} / {detail['province']}",
    ))
    detail = analyze_location("1000 Bruxelles")
    tests.append(check(
        "Code postal corroboré par la ville : BE_LIKELY",
        detail["status"] == BE_LIKELY and detail["province"] == "Bruxelles",
        f"{detail['status']} / {detail['province']}",
    ))

    detail = analyze_location("Louvain-la-Neuve")
    tests.append(check(
        "analyze_location liste les villes reconnues",
        "louvain-la-neuve" in detail["cities"],
        str(detail["cities"]),
    ))
    print()

    print("G. HOMONYMES ÉTRANGERS ET FAUX CODES POSTAUX")
    print("-" * 92)
    # Neuf villes belges ont un homonyme à l'étranger. Un ATS écrit rarement
    # le pays : "Hoboken, NJ" est le format courant. Sans ces gardes, une
    # offre du New Jersey remonte comme belge — et va jusqu'au CV.
    for texte in ("Hoboken, NJ", "Hoboken, New Jersey", "Charleroi, PA",
                  "Ghent, KY", "Waterloo, ON", "Antwerp, NY",
                  "Brussels, Wisconsin", "Boston, MA", "9999, PL"):
        detail = analyze_location(texte)
        tests.append(check(
            f"Homonyme étranger écarté : {texte}",
            detail["status"] == BE_EXCLUDED,
            detail["foreign_subdivision"] or detail["foreign_country"] or "—",
        ))

    # Un nombre à quatre chiffres n'est pas un code postal.
    for texte in ("Suite 1200, Boston", "Building 2000", "Room 4500, Basel",
                  "Poste ouvert en 2026"):
        tests.append(check(
            f"Nombre à 4 chiffres non concluant : {texte}",
            detect_belgium(texte) not in (BE_CONFIRMED, BE_LIKELY),
            detect_belgium(texte),
        ))

    # Non-régression : les vraies villes belges homonymes restent belges
    # quand rien d'étranger ne les qualifie.
    for texte in ("Hoboken", "Charleroi", "Waterloo", "Gent", "Bruges"):
        tests.append(check(
            f"Ville belge homonyme conservée : {texte}",
            detect_belgium(texte) in (BE_CONFIRMED, BE_LIKELY),
            detect_belgium(texte),
        ))
    print()

    passed = sum(1 for x in tests if x)
    total = len(tests)

    print("=" * 92)
    print(f"Tests : {passed}/{total}")
    print("=" * 92)

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    (LOG_DIR / f"location_belgium_v1_audit_{stamp}.json").write_text(
        json.dumps({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "detector_version": LOCATION_DETECTOR_VERSION,
            "passed": passed,
            "total": total,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    if passed != total:
        raise SystemExit("[FAIL] DÉTECTION LOCALISATION BELGE NON VALIDÉE.")

    print("[PASS] DÉTECTION LOCALISATION BELGE VALIDÉE.")


if __name__ == "__main__":
    main()

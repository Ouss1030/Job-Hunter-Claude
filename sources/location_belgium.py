"""
JOB HUNTER BELGIUM
DÉTECTION DE LOCALISATION BELGE - VERSION 1.0

Brique commune aux connecteurs ATS (Greenhouse, Lever, Recruitee).

Pourquoi ce module
------------------
SmartRecruiters expose une localisation structurée :

    {"location": {"country": "be", "city": "Wavre"}}

Le filtre `country == "be"` y est donc fiable. Greenhouse et Lever renvoient
au contraire une chaîne de texte libre, très variable selon l'employeur :

    "Brussels, Belgium"   "Ghent, BE"   "Wavre"   "EMEA"   "Belgium - Remote"

Filtrer là-dessus est du matching de texte, c'est-à-dire exactement la famille
de défauts qui a déjà coûté cher au projet : le bug V.I.E, "Evere" qui matchait
"Beveren", "pharmA PLUS" qui neutralisait un Master exigé.

Ce module centralise la règle pour qu'elle soit écrite, testée et corrigée à un
seul endroit.

Statuts renvoyés
----------------
BE_CONFIRMED   pays belge explicitement nommé
BE_LIKELY      ville ou région belge reconnue, sans mention de pays
BE_UNKNOWN     aucun signal exploitable ("EMEA", "Remote", chaîne vide)
BE_EXCLUDED    un autre pays est explicitement nommé

Note : le cahier des charges prévoyait trois statuts. BE_EXCLUDED a été ajouté
parce que "Berlin, Germany" et "EMEA" ne demandent pas le même traitement : le
premier peut être écarté sans risque, le second mérite une relecture. Confondre
les deux obligerait à relire manuellement toutes les offres mondiales d'un
employeur international.

Principe conservateur
---------------------
Aucune offre n'est écartée silencieusement sur un doute. Une ville belge seule
ne donne jamais BE_CONFIRMED : il existe un Bruges en France, un Waterloo au
Canada. Le tri fin reste à l'appelant.
"""

from __future__ import annotations

import re
import unicodedata


LOCATION_DETECTOR_VERSION = "1.1"

BE_CONFIRMED = "BE_CONFIRMED"
BE_LIKELY = "BE_LIKELY"
BE_UNKNOWN = "BE_UNKNOWN"
BE_EXCLUDED = "BE_EXCLUDED"


# ============================================================
# NORMALISATION
# ============================================================

def normalize(value) -> str:
    """Minuscules, accents retirés, espaces réduits."""
    text = str(value or "").strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "'")
    return re.sub(r"\s+", " ", text).strip()


def bounded_in(phrase: str, normalized_text: str) -> bool:
    """
    Correspondance à frontières lexicales.

    Même technique que matching/application_gate.phrase_regex() et
    matching/application_queue_v12._bounded_phrase_in_text().

    Le piège concret ici : "be" en sous-chaîne matcherait "berlin", "bern",
    "aberdeen". Les gardes empêchent cela.
    """
    phrase = normalize(phrase)
    if not phrase or not normalized_text:
        return False

    pieces = [re.escape(p) for p in phrase.split()]
    body = r"[\s,;/-]+".join(pieces)
    return re.search(rf"(?<![a-z0-9]){body}(?![a-z0-9])", normalized_text) is not None


# ============================================================
# SIGNAUX PAYS
# ============================================================

BELGIUM_NAMES = (
    "belgium",
    "belgique",
    "belgie",       # "belgië" une fois les accents retirés
    "belgien",
    "koninkrijk belgie",
)

# Pays explicitement étrangers. "luxembourg" est traité à part : c'est à la
# fois un pays voisin et une province belge.
FOREIGN_COUNTRIES = (
    "france", "germany", "deutschland", "allemagne",
    "netherlands", "nederland", "pays-bas", "holland",
    "united kingdom", "royaume-uni", "england", "scotland", "ireland",
    "spain", "espagne", "italy", "italie", "portugal",
    "switzerland", "suisse", "schweiz",
    "austria", "autriche", "poland", "pologne",
    "sweden", "suede", "norway", "norvege", "denmark", "danemark",
    "finland", "finlande", "czech", "tcheque", "romania", "roumanie",
    "hungary", "hongrie", "greece", "grece", "bulgaria", "bulgarie",
    "united states", "usa", "canada", "india", "inde", "china", "chine",
    "japan", "japon", "australia", "australie", "brazil", "bresil",
    "morocco", "maroc", "tunisia", "tunisie", "south africa",
    "singapore", "singapour", "israel", "turkey", "turquie",
    "philippines", "vietnam", "thailand", "thailande", "indonesia",
    "malaysia", "malaisie", "korea", "coree", "taiwan", "hong kong",
    "mexico", "mexique", "argentina", "argentine", "chile", "chili",
    "colombia", "colombie", "peru", "perou", "uruguay",
    "egypt", "egypte", "kenya", "nigeria", "ghana", "senegal",
    "algeria", "algerie", "emirates", "emirats", "qatar", "saudi",
    "new zealand", "nouvelle-zelande", "iceland", "islande",
    "croatia", "croatie", "slovakia", "slovaquie", "slovenia", "slovenie",
    "serbia", "serbie", "ukraine", "russia", "russie", "estonia", "estonie",
    "latvia", "lettonie", "lithuania", "lituanie", "malta", "malte", "cyprus",
    # Abréviations sûres uniquement. "nl", "fr" et "de" sont volontairement
    # absents : ils apparaissent dans les mentions bilingues belges
    # ("FR/NL", "bilingue FR-NL") et produiraient des exclusions à tort.
    "uk", "u.k.", "u.s.", "u.s.a.",
)

# Cette liste est le facteur limitant du module : un pays absent laisse une
# ville belge homonyme passer en BE_LIKELY. C'est un compromis assumé — le
# statut BE_LIKELY signale précisément une localisation à revérifier, et le
# principe du projet est de ne jamais exclure sur un doute. Ajouter un pays
# ici quand un cas réel se présente est préférable à un filtre plus agressif
# qui écarterait de vraies offres belges.


# ============================================================
# SUBDIVISIONS ÉTRANGÈRES
# ============================================================

# Neuf villes belges ont un homonyme étranger : Hoboken (New Jersey),
# Waterloo (Ontario, Iowa), Antwerp (Ohio, New York), Brussels (Wisconsin),
# Ghent (Kentucky), Charleroi (Pennsylvanie), Bruges et Mons (France),
# Hasselt (Pays-Bas).
#
# Quand le pays est écrit en toutes lettres, FOREIGN_COUNTRIES suffit. Mais
# un ATS écrit le plus souvent « Hoboken, NJ » : la ville belge l'emporte
# alors sur un pays absent du texte. C'est un faux positif coûteux — une
# offre américaine acceptée va jusqu'au CV, alors qu'une offre belge perdue
# reste invisible.

FOREIGN_SUBDIVISION_NAMES = (
    # États américains dont le nom ne prête pas à confusion en français.
    "alabama", "alaska", "arizona", "arkansas", "california", "californie",
    "colorado", "connecticut", "delaware", "florida", "floride", "georgia",
    "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas", "kentucky",
    "louisiana", "louisiane", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada",
    "new hampshire", "new jersey", "new mexico", "new york", "north carolina",
    "north dakota", "ohio", "oklahoma", "oregon", "pennsylvania",
    "pennsylvanie", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "virginie",
    "washington", "west virginia", "wisconsin", "wyoming",
    # Provinces canadiennes.
    "ontario", "quebec", "alberta", "manitoba", "saskatchewan",
    "nova scotia", "new brunswick", "newfoundland", "british columbia",
    "colombie-britannique",
)

# Codes à deux lettres : États américains, provinces canadiennes et codes
# pays. Testés uniquement après une virgule et en capitales, faute de quoi
# « ON », « IN », « OR », « DE », « LA », « MA », « ME » et « OK »
# matcheraient des mots ordinaires.
#
# Volontairement absents :
#   BE  — c'est la Belgique.
#   LU  — la province belge de Luxembourg, traitée par _luxembourg_is_belgian.
#   VB, OV, WV, LI, NA, HA, AN, BW, VL — abréviations de provinces belges.
FOREIGN_SUBDIVISION_CODES = (
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DC", "DE", "FL", "GA", "HI",
    "IA", "ID", "IL", "IN", "KS", "KY", "MA", "MD", "ME", "MI", "MN", "MO",
    "MS", "MT", "NC", "ND", "NE", "NH", "NJ", "NM", "NV", "NY", "OH", "OK",
    "OR", "PA", "RI", "SC", "SD", "TN", "TX", "UT", "VA", "VT", "WA", "WI",
    "WV", "WY",
    "AB", "BC", "MB", "NB", "NS", "NT", "NU", "ON", "PE", "QC", "SK", "YT",
    "PL", "CZ", "RO", "HU", "GR", "TR", "JP", "CN", "BR", "AU", "SG", "IL",
    "MX", "ZA", "AE", "IE", "PT", "GB",
)

_RE_SUBDIVISION_CODE = re.compile(
    r",\s*(" + "|".join(FOREIGN_SUBDIVISION_CODES) + r")(?![A-Za-z])"
)


def foreign_subdivision(raw_text: str, normalized_text: str) -> str | None:
    """
    Détecte un État, une province ou un code pays étranger.

    Les noms complets sont cherchés dans le texte normalisé ; les codes à
    deux lettres exigent une virgule et des capitales, ce qui distingue
    « Hoboken, NJ » de « nj » apparaissant dans un mot.
    """
    for nom in FOREIGN_SUBDIVISION_NAMES:
        if bounded_in(nom, normalized_text):
            return nom

    match = _RE_SUBDIVISION_CODE.search(str(raw_text or ""))
    return match.group(1) if match else None


def _country_code_be(raw_text: str) -> bool:
    """
    Reconnaît le code pays BE isolé, sans confondre avec un mot commençant
    par « be ».

    Accepté   : "Ghent, BE"   "Brussels (BE)"   "Wavre - BE"
    Refusé    : "Berlin"      "Bern"            "Aberdeen"   "to be defined"

    Le test se fait sur le texte BRUT : le code pays est en capitales, et
    cette information disparaît à la normalisation. La leçon du bug V.I.E
    s'applique en sens inverse — ici les capitales sont un signal utile,
    mais elles ne suffisent pas seules : on exige aussi un séparateur.
    """
    text = str(raw_text or "")
    motifs = (
        r"[,;(\[\-–]\s*BE\s*[)\]]?\s*$",   # fin de chaîne après séparateur
        r"[,;(\[\-–]\s*BE\s*[,;)\]\-–]",   # encadré par des séparateurs
    )
    return any(re.search(m, text) for m in motifs)


# ============================================================
# CODES POSTAUX
# ============================================================

# Un code postal belge à 4 chiffres est un signal fort et fréquent : dans la
# base actuelle, "3560, Belgique" ou "1000, Belgique" représentent une part
# importante des localisations, souvent sans nom de ville exploitable.
# Il donne en prime la région, utile pour mesurer la couverture.
_PLAGES_CODES_POSTAUX = (
    (1000, 1299, "Bruxelles"),
    (1300, 1499, "Brabant wallon"),
    (1500, 1999, "Brabant flamand"),
    (2000, 2999, "Anvers"),
    (3000, 3499, "Brabant flamand"),
    (3500, 3999, "Limbourg"),
    (4000, 4999, "Liège"),
    (5000, 5999, "Namur"),
    (6000, 6599, "Hainaut"),
    (6600, 6999, "Luxembourg (BE)"),
    (7000, 7999, "Hainaut"),
    (8000, 8999, "Flandre occidentale"),
    (9000, 9999, "Flandre orientale"),
)


def belgian_postal_code(text) -> tuple[str, str] | None:
    """
    Extrait un code postal belge et sa province.

    Un nombre à 4 chiffres n'est pas forcément un code postal : on exige
    qu'il soit isolé et qu'il tombe dans une plage belge réelle. Les codes
    postaux belges commencent à 1000, ce qui écarte déjà les années
    (1999 reste ambigu, mais la présence d'un autre signal tranche).
    """
    for m in re.finditer(r"(?<!\d)([1-9]\d{3})(?!\d)", str(text or "")):
        code = int(m.group(1))
        for debut, fin, province in _PLAGES_CODES_POSTAUX:
            if debut <= code <= fin:
                return m.group(1), province
    return None


# ============================================================
# SIGNAUX VILLES ET RÉGIONS
# ============================================================

# Régions et provinces. "luxembourg" est volontairement absent : voir
# _luxembourg_is_belgian().
BELGIAN_REGIONS = (
    "flanders", "flandre", "vlaanderen", "vlaams gewest",
    "wallonia", "wallonie", "waals gewest", "region wallonne",
    "brussels capital", "bruxelles-capitale", "region de bruxelles-capitale",
    "brussels hoofdstedelijk gewest",
    "brabant wallon", "waals-brabant", "vlaams-brabant", "brabant flamand",
    "hainaut", "henegouwen",
    "west-vlaanderen", "flandre occidentale",
    "oost-vlaanderen", "flandre orientale",
    "antwerpen province", "province de liege", "provincie limburg",
    "namur province", "province de namur",
)

BELGIAN_CITIES = (
    # Bruxelles et ses communes
    "brussels", "bruxelles", "brussel", "bruxelles capitale",
    "anderlecht", "auderghem", "oudergem", "berchem-sainte-agathe",
    "sint-agatha-berchem", "etterbeek", "evere", "forest", "vorst",
    "ganshoren", "ixelles", "elsene", "jette", "koekelberg",
    "molenbeek", "saint-gilles", "sint-gillis", "saint-josse",
    "sint-joost", "schaerbeek", "schaarbeek", "uccle", "ukkel",
    "watermael-boitsfort", "watermaal-bosvoorde", "woluwe",
    "woluwe-saint-lambert", "woluwe-saint-pierre",
    # Périphérie et Brabant
    "zaventem", "diegem", "machelen", "vilvoorde", "wavre", "waver",
    "rixensart", "genval", "braine-l'alleud", "braine l'alleud",
    "waterloo", "ottignies", "louvain-la-neuve", "mont-saint-guibert",
    "drogenbos", "halle", "asse", "dilbeek", "grimbergen", "overijse",
    "tervuren", "wemmel", "nivelles", "tubize", "jodoigne", "perwez",
    # Flandre
    "antwerp", "antwerpen", "anvers", "gent", "ghent", "gand",
    "leuven", "louvain", "mechelen", "malines", "brugge", "bruges",
    "kortrijk", "courtrai", "oostende", "ostende", "hasselt",
    "genk", "turnhout", "sint-niklaas", "aalst", "alost", "roeselare",
    "beveren", "lokeren", "geel", "mol", "lier", "waregem", "izegem",
    "tienen", "tirlemont", "diest", "vilvorde", "zwijndrecht",
    "westerlo", "herentals", "puurs", "temse", "ninove", "deinze",
    # Sites industriels et districts, ajoutés le 22/08/2026 : "Hoboken"
    # (grand site Umicore, district d'Anvers) manquait et faisait perdre
    # de vraies offres au pré-filtrage.
    "hoboken", "olen", "balen", "overpelt", "lommel", "beringen", "tessenderlo",
    "ham", "houthalen", "maasmechelen", "lanaken", "bilzen", "tongeren",
    "sint-truiden", "landen", "wetteren", "lokeren", "zele", "hamme",
    "bornem", "willebroek", "boom", "rumst", "kontich", "mortsel",
    "wilrijk", "deurne", "merksem", "ekeren", "berchem", "borgerhout",
    "schoten", "brasschaat", "kapellen", "stabroek", "zandvliet",
    "hoegaarden", "merelbeke", "evergem", "zelzate", "temse",
    "feluy", "seneffe", "manage", "engis", "amay", "wanze", "hermalle",
    "grace-hollogne", "flemalle", "ans", "herstal", "oupeye", "vise",
    # Wallonie
    "liege", "luik", "charleroi", "namur", "namen", "mons", "bergen",
    "tournai", "doornik", "verviers", "seraing", "herstal", "huy",
    "arlon", "aarlen", "bastogne", "marche-en-famenne", "ciney",
    "dinant", "philippeville", "thuin", "soignies", "ath", "lessines",
    "leuze", "peruwelz", "mouscron", "moeskroen", "comines",
    "eupen", "malmedy", "spa", "stavelot", "vielsalm", "welkenraedt",
    "gembloux", "andenne", "fleurus", "gosselies", "jumet",
    "la louviere", "binche", "chatelet", "farciennes", "sambreville",
    "braine-le-comte", "enghien", "antoing", "estaimpuis",
)


def _luxembourg_is_belgian(normalized_text: str, raw_text: str) -> bool:
    """
    "Luxembourg" désigne à la fois un pays voisin et une province belge.

    On ne le compte comme belge que si un autre signal belge est présent
    dans la même chaîne ("Arlon, Luxembourg", "Province de Luxembourg").
    Seul, il est traité comme le pays — cas de loin le plus fréquent dans
    une annonce d'emploi.
    """
    if not bounded_in("luxembourg", normalized_text):
        return False

    if bounded_in("province de luxembourg", normalized_text):
        return True
    if bounded_in("provincie luxemburg", normalized_text):
        return True

    autres_signaux = any(bounded_in(v, normalized_text) for v in BELGIAN_CITIES)
    return autres_signaux or _country_code_be(raw_text)


# ============================================================
# DÉTECTION
# ============================================================

def analyze_location(location_text) -> dict:
    """
    Analyse détaillée : statut + signaux ayant conduit à la décision.

    Utile pour journaliser pourquoi une offre a été retenue ou écartée,
    plutôt que de constater un compteur sans explication.
    """
    raw = str(location_text or "")
    norm = normalize(raw)

    detail = {
        "input": raw,
        "normalized": norm,
        "status": BE_UNKNOWN,
        "country_name": None,
        "country_code": False,
        "postal_code": None,
        "province": None,
        "cities": [],
        "regions": [],
        "foreign_country": None,
        "foreign_subdivision": None,
        "detector_version": LOCATION_DETECTOR_VERSION,
    }

    if not norm:
        return detail

    # 1. Pays belge explicitement nommé : signal le plus fort.
    for nom in BELGIUM_NAMES:
        if bounded_in(nom, norm):
            detail["country_name"] = nom
            detail["status"] = BE_CONFIRMED
            break

    # 2. Code pays BE isolé, testé sur le texte brut (capitales).
    if _country_code_be(raw):
        detail["country_code"] = True
        detail["status"] = BE_CONFIRMED

    # 3. Code postal belge : signal fort, et donne la province.
    cp = belgian_postal_code(raw)
    if cp:
        detail["postal_code"], detail["province"] = cp

    # 4. Villes et régions belges.
    detail["cities"] = [v for v in BELGIAN_CITIES if bounded_in(v, norm)]
    detail["regions"] = [r for r in BELGIAN_REGIONS if bounded_in(r, norm)]
    if _luxembourg_is_belgian(norm, raw):
        detail["regions"].append("province de luxembourg")

    # 5. Pays étranger explicitement nommé.
    for pays in FOREIGN_COUNTRIES:
        if bounded_in(pays, norm):
            detail["foreign_country"] = pays
            break

    # 6. Subdivision étrangère : « Hoboken, NJ » sans mention du pays.
    detail["foreign_subdivision"] = foreign_subdivision(raw, norm)

    if detail["status"] == BE_CONFIRMED:
        # Un pays belge nommé l'emporte : "Brussels, Belgium - Paris, France"
        # reste une offre qui concerne la Belgique.
        return detail

    if detail["foreign_country"]:
        detail["status"] = BE_EXCLUDED
        return detail

    if detail["foreign_subdivision"]:
        # Une ville belge homonyme ne doit pas l'emporter sur un État
        # étranger nommé : « Charleroi, PA » est en Pennsylvanie.
        detail["status"] = BE_EXCLUDED
        return detail

    # "Luxembourg" seul, sans signal belge : c'est le pays.
    if bounded_in("luxembourg", norm) and not detail["cities"] and not detail["regions"]:
        detail["foreign_country"] = "luxembourg"
        detail["status"] = BE_EXCLUDED
        return detail

    # Un code postal seul ne suffit pas : tout nombre à quatre chiffres lui
    # ressemble. « Building 2000 », « Room 4500, Basel » et « Suite 1200 »
    # passaient pour belges. Mesuré sur les 5 430 localisations réelles de
    # la base, exiger une corroboration ne dégrade aucune offre belge — les
    # 2 437 offres à code postal sans ville portent toutes « Belgique », et
    # les 4 seuls cas reposant sur le code seul étaient « 9999, PL » et
    # « 9999, FR », donc étrangers.
    if detail["cities"] or detail["regions"]:
        detail["status"] = BE_LIKELY

    return detail


def detect_belgium(location_text) -> str:
    """
    Statut de localisation belge.

    >>> detect_belgium("Brussels, Belgium")
    'BE_CONFIRMED'
    >>> detect_belgium("Wavre")
    'BE_LIKELY'
    >>> detect_belgium("Berlin, Germany")
    'BE_EXCLUDED'
    >>> detect_belgium("EMEA")
    'BE_UNKNOWN'
    """
    return analyze_location(location_text)["status"]


_RANG_STATUTS = {
    BE_CONFIRMED: 3,
    BE_LIKELY: 2,
    BE_UNKNOWN: 1,
    BE_EXCLUDED: 0,
}


def detect_belgium_multi(location_text, separateurs=(";", "|")) -> str:
    """
    Localisation multiple, courante chez Greenhouse et Lever :

        "New York, New York, USA; Brussels, Belgium"

    Une offre ouverte sur plusieurs sites dont un belge concerne la Belgique.
    On retient donc le meilleur statut parmi les segments, jamais le pire.
    """
    brut = str(location_text or "")
    if not brut.strip():
        return BE_UNKNOWN

    motif = "[" + "".join(re.escape(s) for s in separateurs) + "]"
    segments = [p.strip() for p in re.split(motif, brut) if p.strip()]
    if len(segments) <= 1:
        return detect_belgium(brut)

    statuts = [detect_belgium(seg) for seg in segments]
    return max(statuts, key=lambda st: _RANG_STATUTS.get(st, 0))


def is_belgium_candidate(location_text, include_unknown: bool = True) -> bool:
    """
    Faut-il conserver cette offre ?

    Par défaut les localisations inexploitables sont conservées : une offre
    "Remote - Europe" chez un employeur belge peut être valable, et le projet
    préfère un doublon à une exclusion à tort.
    """
    statut = detect_belgium(location_text)
    if statut in (BE_CONFIRMED, BE_LIKELY):
        return True
    if statut == BE_UNKNOWN:
        return include_unknown
    return False

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable

BELGIUM = "BELGIUM"
FOREIGN = "FOREIGN"
UNKNOWN = "UNKNOWN"

_VERSION = "1.3"

@dataclass(frozen=True)
class LocationDecision:
    status: str
    reason: str
    normalized: str
    matched: str = ""

    @property
    def state(self) -> str:
        # Backward/forward compatibility for diagnostics/connectors.
        return self.status


def _strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(ch)
    )


def _normalize(value: object) -> str:
    text = _strip_accents(str(value or ""))
    text = text.replace("\u00a0", " ")
    text = re.sub(r"\s+", " ", text).strip().upper()
    return text


_BELGIUM_COUNTRY_PATTERNS = [
    ("BELGIUM", re.compile(r"\bBELGIUM\b")),
    ("BELGIQUE", re.compile(r"\bBELGIQUE\b")),
    ("BELGIE", re.compile(r"\bBELGIE\b")),
]

# Explicit country names only. Do not use bare two-letter codes globally:
# "US", "IN", "BR", ... are too ambiguous in free text.
_FOREIGN_COUNTRIES = [
    "ALBANIA", "ALGERIA", "ARGENTINA", "ARMENIA", "AUSTRALIA", "AUSTRIA",
    "BAHRAIN", "BANGLADESH", "BELARUS", "BOSNIA", "BRAZIL", "BULGARIA",
    "CANADA", "CHILE", "CHINA", "COLOMBIA", "COSTA RICA", "CROATIA",
    "CYPRUS", "CZECH REPUBLIC", "CZECHIA", "DENMARK", "ECUADOR", "EGYPT",
    "ESTONIA", "FINLAND", "FRANCE", "GEORGIA", "GERMANY", "GREECE",
    "HONG KONG", "HUNGARY", "ICELAND", "INDIA", "INDONESIA", "IRELAND",
    "ISRAEL", "ITALY", "JAPAN", "JORDAN", "KENYA", "LATVIA", "LEBANON",
    "LITHUANIA", "LUXEMBOURG", "MALAYSIA", "MEXICO", "MOLDOVA", "MOROCCO",
    "NETHERLANDS", "NEW ZEALAND", "NIGERIA", "NORWAY", "PAKISTAN", "PERU",
    "PHILIPPINES", "POLAND", "PORTUGAL", "PUERTO RICO", "QATAR", "ROMANIA",
    "SAUDI ARABIA", "SERBIA", "SINGAPORE", "SLOVAKIA", "SLOVENIA",
    "SOUTH AFRICA", "SOUTH KOREA", "KOREA", "SPAIN", "SWEDEN",
    "SWITZERLAND", "TAIWAN", "THAILAND", "TUNISIA", "TURKEY", "TURKIYE",
    "UKRAINE", "UNITED ARAB EMIRATES", "UAE", "UNITED KINGDOM",
    "UNITED STATES OF AMERICA", "UNITED STATES", "USA", "VIETNAM",
    "DEM. REP. CONGO", "DEMOCRATIC REPUBLIC OF THE CONGO",
]

_FOREIGN_PATTERNS = [
    (country, re.compile(rf"\b{re.escape(country)}\b"))
    for country in sorted(_FOREIGN_COUNTRIES, key=len, reverse=True)
]


# Foreign subdivisions are checked BEFORE Belgian city homonyms.
_FOREIGN_SUBDIVISION_NAMES = [
    "KENTUCKY", "MASSACHUSETTS", "NEW JERSEY", "NEW YORK",
    "PENNSYLVANIA", "WISCONSIN", "ONTARIO", "QUEBEC",
]
_FOREIGN_SUBDIVISION_NAME_PATTERNS = [
    (marker, re.compile(rf"\b{re.escape(marker)}\b"))
    for marker in sorted(_FOREIGN_SUBDIVISION_NAMES, key=len, reverse=True)
]

_FOREIGN_SUBDIVISION_CODE_RE = re.compile(
    r"(?:,\s*|\b(?:HOBOKEN|CHARLEROI|GHENT|GENT|WATERLOO|ANTWERP|ANTWERPEN|"
    r"BRUSSELS|BRUXELLES|BOSTON)\s+)"
    r"(?P<code>NJ|PA|KY|ON|NY|WI|MA)\b"
)

_FOREIGN_POSTAL_COUNTRY_CODE_RE = re.compile(
    r"\b\d{4,6}\s*,?\s*(?P<code>"
    r"PL|FR|DE|NL|CH|GB|UK|US|CA|IE|NO|SE|DK|FI|IT|ES|PT|AT"
    r")\b\s*$"
)

_BELGIAN_REGIONS = [
    "BRUSSELS-CAPITAL", "BRUSSELS CAPITAL", "BRUSSELS",
    "BRUXELLES-CAPITALE", "BRUXELLES",
    "WALLONIA", "WALLONIE", "FLANDERS", "VLAANDEREN",
]

_BELGIAN_PROVINCES = [
    "ANTWERPEN", "ANTWERP", "ANVERS",
    "LIMBURG", "LIMBOURG",
    "OOST-VLAANDEREN", "EAST FLANDERS", "FLANDRE ORIENTALE",
    "WEST-VLAANDEREN", "WEST FLANDERS", "FLANDRE OCCIDENTALE",
    "VLAAMS-BRABANT", "FLEMISH BRABANT", "BRABANT FLAMAND",
    "BRABANT WALLON", "WALLOON BRABANT",
    "HAINAUT", "HENEGOUWEN",
    "LIEGE", "LUIK",
    "NAMUR", "NAMEN",
    "LUXEMBOURG PROVINCE", "PROVINCE DE LUXEMBOURG",
]

# High-value / common Belgian cities and employment hubs.
_BELGIAN_CITIES = [
    "AALST", "AALTER", "ANDERLECHT", "ANTWERPEN", "ANTWERP", "ANVERS",
    "ARLON", "ASSE", "ATH", "AUDERGHEM", "AARSCHOT",
    "BASTOGNE", "BEERSE", "BERINGEN", "BERNISSART", "BINCHE",
    "BOOM", "BORNEM", "BRAINE-L'ALLEUD", "BRAINE L'ALLEUD",
    "BRASSCHAAT", "BRUGGE", "BRUGES", "BRUSSELS", "BRUXELLES",
    "CHARLEROI", "CHATELET", "CHIMAY", "DEERLIJK", "DIEGEM", "DILBEEK", "DINANT",
    "DONSTIENNES",
    "EVERE", "FLEURUS", "GENK", "GENT", "GHENT", "GAND",
    "GOSSELIES",
    "GEEL", "GERAARDSBERGEN", "GRIMBERGEN", "HALLE", "HASSELT",
    "HEIST-OP-DEN-BERG", "HEULTJE", "HOBOKEN", "HOOGSTRATEN",
    "HUIZINGEN", "HUY", "IXELLES", "JODOIGNE", "KALLO", "KALLO-BEVEREN",
    "KORTRIJK", "COURTRAI", "LA LOUVIERE", "LEUVEN", "LOUVAIN",
    "LESSINES", "LEUZE-EN-HAINAUT", "LIEGE", "LUIK", "LIER", "LOKEREN",
    "LOUVAIN-LA-NEUVE", "MALMEDY", "MARCHE-EN-FAMENNE", "MARCHIENNE-AU-PONT",
    "MECHELEN", "MALINES",
    "MOL", "MONS", "BERGEN", "MORTSEL", "MOUSCRON", "MUSKRON",
    "NAMUR", "NAMEN", "NEVELE", "NIVELLES", "OOSTENDE", "OSTENDE",
    "OUDENAARDE", "AUDENARDE", "PUURS", "PUURS-SINT-AMANDS",
    "RIXENSART", "ROESELARE", "ROULERS", "SAINT-GHISLAIN", "SCHAERBEEK",
    "SERAING", "SINT-AGATHA-BERCHEM", "SINT-NIKLAAS", "SAINT-NICOLAS",
    "SOIGNIES", "SPA", "TEMSE", "TESSENDERLO",
    "TIENEN", "TIRLEMONT", "TOURNAI", "DOORNIK", "TURNHOUT",
    "VAUX-SUR-SURE", "VERVIERS", "VIELSALM", "VILVOORDE", "WAREGEM", "WAIMES",
    "WATERLOO", "WAVRE", "WILLEBROEK", "WOLUWE", "ZAVENTEM",
]

_REGION_PATTERNS = [
    (marker, re.compile(rf"\b{re.escape(marker)}\b"))
    for marker in sorted(_BELGIAN_REGIONS + _BELGIAN_PROVINCES, key=len, reverse=True)
]

_CITY_PATTERNS = [
    (city, re.compile(rf"(?<![A-Z0-9]){re.escape(city)}(?![A-Z0-9])"))
    for city in sorted(_BELGIAN_CITIES, key=len, reverse=True)
]

# Explicit Belgian ISO-like code only in structured punctuation context.
# Examples accepted: "Mortsel, BE", "Belgium - Brussels, BE | City".
_BE_CODE_RE = re.compile(r"(?:,\s*BE\b|\bBE\s*(?:$|\||;|/))")

# A Belgian postal code must be a standalone 4-digit token.
# Do NOT match the first four digits of foreign formats such as 9999-999.
_POSTCODE_RE = re.compile(r"(?<![A-Z0-9-])([1-9]\d{3})(?![A-Z0-9-])")


def _first_match(patterns: Iterable[tuple[str, re.Pattern[str]]], text: str) -> str:
    for label, pattern in patterns:
        if pattern.search(text):
            return label
    return ""


def classify_belgium_location(
    location: object,
    trusted_belgium_listing: bool = False,
    extra_belgium_markers: Iterable[str] | None = None,
) -> LocationDecision:
    normalized = _normalize(location)

    if not normalized:
        if trusted_belgium_listing:
            return LocationDecision(
                BELGIUM,
                "trusted_belgium_listing",
                normalized,
                "",
            )
        return LocationDecision(
            UNKNOWN,
            "empty_location",
            normalized,
            "",
        )

    explicit_belgium = _first_match(_BELGIUM_COUNTRY_PATTERNS, normalized)
    explicit_foreign = _first_match(_FOREIGN_PATTERNS, normalized)

    # A multi-location vacancy may legitimately include Belgium plus foreign
    # locations. Belgium eligibility must not be lost merely because another
    # allowed location is foreign.
    if explicit_belgium:
        if explicit_foreign:
            return LocationDecision(
                BELGIUM,
                "multi_location_includes_belgium",
                normalized,
                explicit_belgium,
            )
        return LocationDecision(
            BELGIUM,
            "explicit_belgium_country",
            normalized,
            explicit_belgium,
        )

    # Structured ", BE" is explicit Belgian evidence and must beat ambiguous
    # tokens such as the Belgian province name "Luxembourg".
    if _BE_CODE_RE.search(normalized):
        return LocationDecision(
            BELGIUM,
            "explicit_be_country_code",
            normalized,
            "BE",
        )

    # "Luxembourg" can mean the Belgian province. If a known Belgian city is
    # also present, keep the vacancy eligible for Belgium.
    city_before_foreign = _first_match(_CITY_PATTERNS, normalized)
    if explicit_foreign == "LUXEMBOURG" and city_before_foreign:
        return LocationDecision(
            BELGIUM,
            "belgian_city_with_luxembourg_province",
            normalized,
            city_before_foreign,
        )

    # Explicit foreign country otherwise beats postal-code or city heuristics.
    if explicit_foreign:
        return LocationDecision(
            FOREIGN,
            f"explicit_foreign_country:{explicit_foreign.title()}",
            normalized,
            explicit_foreign,
        )

    foreign_subdivision = _first_match(
        _FOREIGN_SUBDIVISION_NAME_PATTERNS,
        normalized,
    )
    if foreign_subdivision:
        return LocationDecision(
            FOREIGN,
            f"explicit_foreign_subdivision:{foreign_subdivision.title()}",
            normalized,
            foreign_subdivision,
        )

    subdivision_code = _FOREIGN_SUBDIVISION_CODE_RE.search(normalized)
    if subdivision_code:
        code = subdivision_code.group("code")
        return LocationDecision(
            FOREIGN,
            f"explicit_foreign_subdivision_code:{code}",
            normalized,
            code,
        )

    postal_country_code = _FOREIGN_POSTAL_COUNTRY_CODE_RE.search(normalized)
    if postal_country_code:
        code = postal_country_code.group("code")
        return LocationDecision(
            FOREIGN,
            f"explicit_foreign_postal_country_code:{code}",
            normalized,
            code,
        )

    region = _first_match(_REGION_PATTERNS, normalized)
    if region:
        # "Luxembourg" alone is intentionally not a Belgian province marker.
        return LocationDecision(
            BELGIUM,
            "belgian_region_or_province",
            normalized,
            region,
        )

    city = _first_match(_CITY_PATTERNS, normalized)
    if city:
        return LocationDecision(
            BELGIUM,
            "belgian_city",
            normalized,
            city,
        )

    if extra_belgium_markers:
        extras = []
        for marker in extra_belgium_markers:
            value = _normalize(marker)
            if value:
                extras.append(value)
        for marker in sorted(set(extras), key=len, reverse=True):
            if re.search(rf"(?<![A-Z0-9]){re.escape(marker)}(?![A-Z0-9])", normalized):
                return LocationDecision(
                    BELGIUM,
                    "extra_belgium_marker",
                    normalized,
                    marker,
                )

    postcode = _POSTCODE_RE.search(normalized)
    if postcode and not trusted_belgium_listing:
        return LocationDecision(
            UNKNOWN,
            "postal_code_without_belgium_evidence",
            normalized,
            postcode.group(1),
        )

    if trusted_belgium_listing:
        return LocationDecision(
            BELGIUM,
            "trusted_belgium_listing",
            normalized,
            "",
        )

    return LocationDecision(
        UNKNOWN,
        "no_geographic_evidence",
        normalized,
        "",
    )


def is_belgium_location(
    location: object,
    trusted_belgium_listing: bool = False,
    extra_belgium_markers: Iterable[str] | None = None,
) -> bool:
    return (
        classify_belgium_location(
            location,
            trusted_belgium_listing=trusted_belgium_listing,
            extra_belgium_markers=extra_belgium_markers,
        ).status
        == BELGIUM
    )

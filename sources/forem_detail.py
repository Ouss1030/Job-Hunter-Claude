"""
Job Hunter Belgium
Détail des offres Forem - VERSION 4

Cette version utilise directement l'API interne observée
sur les pages publiques du Forem :

/recherche-offres/api/Diffusion/DetailOffre/<NUMERO_OFFRE>

Objectifs :
- récupérer le détail complet ;
- utiliser un cache local ;
- nettoyer le HTML et les entités HTML ;
- exclure les données de contact inutiles ;
- produire un texte propre pour le moteur de matching.
"""

import html
import json
import re

from pathlib import Path
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = (
    "https://www.leforem.be/"
    "recherche-offres"
)

DETAIL_API_URL = (
    BASE_URL
    + "/api/Diffusion/DetailOffre/{offer_id}"
)

TIMEOUT = 30


PROJECT_ROOT = (
    Path(__file__)
    .resolve()
    .parent
    .parent
)

CACHE_DIR = (
    PROJECT_ROOT
    / "logs"
    / "forem_detail_cache"
)

CACHE_DIR.mkdir(
    parents=True,
    exist_ok=True
)


HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 "
        "(Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 "
        "(KHTML, like Gecko) "
        "Chrome/151.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-BE,fr;q=0.9,en;q=0.8,nl;q=0.7",
    "Referer": (
        "https://www.leforem.be/"
        "recherche-offres/"
    ),
}


# ============================================================
# CHAMPS UTILES AU MATCHING
# ============================================================

MATCHING_FIELDS = [
    "titreOffre",
    "secteurActiviteEmployeur",
    "typeContrat",
    "regimeTravail",
    "lieuxTravail",
    "langues",
    "descriptionJob",
    "metier",
    "benefits",
    "travel",
    "softSkills",
    "officeSkills",
    "experience",
    "recentExperience",
    "certifications",
    "etudes",
    "competencies",
    "benefitsComments",
]


# ============================================================
# NETTOYAGE TEXTE
# ============================================================

def normalize_text(value):
    """
    Normalisation légère pour déduplication.
    """

    if value is None:
        return ""

    value = str(value).lower()

    value = re.sub(
        r"\s+",
        " ",
        value
    ).strip()

    return value


def clean_text(value):
    """
    Nettoie :
    - HTML ;
    - entités HTML ;
    - espaces multiples ;
    - retours à la ligne inutiles.
    """

    if value is None:
        return ""

    value = str(value)

    # Decode plusieurs fois au cas où
    # l'encodage soit imbriqué.
    for _ in range(2):
        value = html.unescape(value)

    soup = BeautifulSoup(
        value,
        "html.parser"
    )

    value = soup.get_text(
        "\n",
        strip=True
    )

    value = value.replace(
        "\xa0",
        " "
    )

    lines = []

    for line in value.splitlines():

        line = re.sub(
            r"\s+",
            " ",
            line
        ).strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


# ============================================================
# IDENTIFIANT OFFRE
# ============================================================

def get_offer_id(value):
    """
    Accepte un ID ou une URL Forem.
    """

    if value is None:
        return ""

    value = str(value).strip()

    if value.isdigit():
        return value

    try:

        path = (
            urlparse(value)
            .path
            .rstrip("/")
        )

        last_part = (
            path.split("/")[-1]
        )

        if last_part.isdigit():
            return last_part

    except Exception:
        pass

    match = re.search(
        r"\b\d{5,10}\b",
        value
    )

    if match:
        return match.group(0)

    return ""


# ============================================================
# CACHE
# ============================================================

def get_cache_path(offer_id):
    """
    Chemin du cache JSON d'une offre.
    """

    return (
        CACHE_DIR
        / f"{offer_id}.json"
    )


def load_from_cache(offer_id):
    """
    Charge le JSON depuis le cache.
    """

    cache_path = (
        get_cache_path(
            offer_id
        )
    )

    if not cache_path.exists():
        return None

    try:

        with cache_path.open(
            "r",
            encoding="utf-8"
        ) as file:

            return json.load(file)

    except Exception:
        return None


def save_to_cache(
    offer_id,
    data
):
    """
    Sauvegarde le détail d'une offre.
    """

    cache_path = (
        get_cache_path(
            offer_id
        )
    )

    with cache_path.open(
        "w",
        encoding="utf-8"
    ) as file:

        json.dump(
            data,
            file,
            ensure_ascii=False,
            indent=2
        )


# ============================================================
# APPEL API
# ============================================================

def fetch_forem_detail(
    offer_or_url,
    use_cache=True
):
    """
    Appelle l'API DetailOffre.
    """

    offer_id = (
        get_offer_id(
            offer_or_url
        )
    )

    if not offer_id:

        return {
            "success": False,
            "offer_id": None,
            "data": None,
            "from_cache": False,
            "status_code": None,
            "error": "Numéro d'offre invalide.",
        }


    # ========================================================
    # CACHE
    # ========================================================

    if use_cache:

        cached_data = (
            load_from_cache(
                offer_id
            )
        )

        if cached_data is not None:

            return {
                "success": True,
                "offer_id": offer_id,
                "data": cached_data,
                "from_cache": True,
                "status_code": 200,
                "error": None,
            }


    # ========================================================
    # API
    # ========================================================

    url = DETAIL_API_URL.format(
        offer_id=offer_id
    )

    try:

        response = requests.get(
            url,
            headers=HEADERS,
            timeout=TIMEOUT
        )

        response.raise_for_status()

    except requests.RequestException as error:

        status_code = None

        if error.response is not None:
            status_code = (
                error.response.status_code
            )

        return {
            "success": False,
            "offer_id": offer_id,
            "data": None,
            "from_cache": False,
            "status_code": status_code,
            "error": str(error),
        }


    # ========================================================
    # JSON
    # ========================================================

    try:

        data = response.json()

    except ValueError:

        return {
            "success": False,
            "offer_id": offer_id,
            "data": None,
            "from_cache": False,
            "status_code": response.status_code,
            "error": (
                "La réponse de l'API "
                "n'est pas un JSON valide."
            ),
        }


    # ========================================================
    # SAUVEGARDE CACHE
    # ========================================================

    if use_cache:

        try:

            save_to_cache(
                offer_id,
                data
            )

        except Exception as error:

            print(
                "⚠️ Cache impossible pour",
                offer_id,
                ":",
                error
            )


    return {
        "success": True,
        "offer_id": offer_id,
        "data": data,
        "from_cache": False,
        "status_code": response.status_code,
        "error": None,
    }


# ============================================================
# EXTRACTION RÉCURSIVE
# ============================================================

def extract_strings(value):
    """
    Extrait récursivement les chaînes utiles
    d'une structure JSON.
    """

    strings = []


    if isinstance(value, dict):

        for key, child in value.items():

            key_lower = (
                str(key).lower()
            )

            # On ignore certains champs techniques.
            if key_lower in [
                "id",
                "url",
                "email",
                "mail",
                "telephone",
                "phone",
                "logo",
                "logomimetype",
                "code",
            ]:
                continue

            strings.extend(
                extract_strings(
                    child
                )
            )


    elif isinstance(value, list):

        for child in value:

            strings.extend(
                extract_strings(
                    child
                )
            )


    elif isinstance(value, str):

        text = clean_text(
            value
        )

        if is_useful_text(text):

            strings.append(
                text
            )


    return strings


# ============================================================
# FILTRE BRUIT
# ============================================================

def is_useful_text(text):
    """
    Élimine les éléments clairement inutiles
    pour le matching.
    """

    if not text:
        return False

    text = text.strip()

    if len(text) < 2:
        return False

    # Numéros seuls
    if re.fullmatch(
        r"\d+",
        text
    ):
        return False

    # URLs
    if text.startswith(
        (
            "http://",
            "https://"
        )
    ):
        return False

    # Email
    if re.fullmatch(
        r"[^@\s]+@[^@\s]+\.[^@\s]+",
        text
    ):
        return False


    technical_values = {
        "JobPosting",
        "PropertyValue",
        "Organization",
        "Place",
        "PostalAddress",
        "FULL_TIME",
    }

    if text in technical_values:
        return False

    return True


# ============================================================
# TEXTE POUR MATCHING
# ============================================================

def extract_matching_text(data):
    """
    Produit un texte propre à partir des champs
    réellement utiles d'une offre.
    """

    if not isinstance(
        data,
        dict
    ):
        return ""


    collected = []

    seen = set()


    for field in MATCHING_FIELDS:

        if field not in data:
            continue

        values = extract_strings(
            data[field]
        )

        for text in values:

            normalized = (
                normalize_text(
                    text
                )
            )

            if not normalized:
                continue

            if normalized in seen:
                continue

            seen.add(
                normalized
            )

            collected.append(
                text
            )


    return "\n".join(
        collected
    )


# ============================================================
# DONNÉES STRUCTURÉES
# ============================================================

def extract_structured_info(data):
    """
    Extrait quelques informations particulièrement
    importantes sous une forme simple.
    """

    if not isinstance(
        data,
        dict
    ):
        return {}


    result = {
        "title": clean_text(
            data.get(
                "titreOffre"
            )
        ),

        "sector": clean_text(
            data.get(
                "secteurActiviteEmployeur"
            )
        ),

        "contract_type": clean_text(
            data.get(
                "typeContrat"
            )
        ),

        "work_regime": clean_text(
            data.get(
                "regimeTravail"
            )
        ),

        "job_description": clean_text(
            data.get(
                "descriptionJob"
            )
        ),

        "job_category": clean_text(
            data.get(
                "metier"
            )
        ),
    }


    # ========================================================
    # LANGUES
    # ========================================================

    languages = []

    for language in (
        data.get(
            "langues"
        )
        or []
    ):

        if not isinstance(
            language,
            dict
        ):
            continue

        name = clean_text(
            language.get(
                "libelle"
            )
        )

        level = clean_text(
            language.get(
                "experience"
            )
        )

        if name:

            if level:

                languages.append(
                    f"{name} : {level}"
                )

            else:

                languages.append(
                    name
                )


    result[
        "languages"
    ] = languages


    # ========================================================
    # EXPÉRIENCE
    # ========================================================

    experiences = []

    for experience in (
        data.get(
            "experience"
        )
        or []
    ):

        if not isinstance(
            experience,
            dict
        ):
            continue

        profession = clean_text(
            experience.get(
                "libelle"
            )
        )

        level = clean_text(
            experience.get(
                "experience"
            )
        )

        text_parts = [
            part
            for part in [
                profession,
                level
            ]
            if part
        ]

        if text_parts:

            experiences.append(
                " | ".join(
                    text_parts
                )
            )


    result[
        "experience"
    ] = experiences


    # ========================================================
    # ÉTUDES
    # ========================================================

    studies = []

    for study in (
        data.get(
            "etudes"
        )
        or []
    ):

        if not isinstance(
            study,
            dict
        ):
            continue

        level = clean_text(
            study.get(
                "code"
            )
        )

        field = clean_text(
            study.get(
                "libelle"
            )
        )

        text_parts = [
            part
            for part in [
                level,
                field
            ]
            if part
        ]

        if text_parts:

            studies.append(
                " | ".join(
                    text_parts
                )
            )


    result[
        "studies"
    ] = studies


    return result


# ============================================================
# FONCTION PUBLIQUE PRINCIPALE
# ============================================================

def get_forem_job_detail(
    offer_or_url,
    use_cache=True
):
    """
    Fonction principale utilisée par Job Hunter.
    """

    api_result = (
        fetch_forem_detail(
            offer_or_url,
            use_cache=use_cache
        )
    )


    if not api_result[
        "success"
    ]:

        return {
            **api_result,
            "raw_data": None,
            "matching_text": "",
            "structured": {},
        }


    data = (
        api_result[
            "data"
        ]
    )


    matching_text = (
        extract_matching_text(
            data
        )
    )


    structured = (
        extract_structured_info(
            data
        )
    )


    return {
        "success": True,

        "offer_id":
            api_result[
                "offer_id"
            ],

        "status_code":
            api_result[
                "status_code"
            ],

        "from_cache":
            api_result[
                "from_cache"
            ],

        "raw_data":
            data,

        "matching_text":
            matching_text,

        "matching_text_length":
            len(
                matching_text
            ),

        "structured":
            structured,

        "error":
            None,
    }


# ============================================================
# TEST
# ============================================================

if __name__ == "__main__":

    TEST_OFFER = "2015338"

    print()
    print("=" * 78)
    print("       JOB HUNTER - FOREM DETAIL V4")
    print("=" * 78)


    result = get_forem_job_detail(
        TEST_OFFER,
        use_cache=True
    )


    if not result["success"]:

        print()
        print("❌ ÉCHEC")
        print(
            result["error"]
        )

        raise SystemExit(1)


    print()
    print("✅ Offre récupérée")

    print(
        "ID          :",
        result["offer_id"]
    )

    print(
        "Cache       :",
        result["from_cache"]
    )

    print(
        "Taille texte:",
        result[
            "matching_text_length"
        ]
    )


    print()
    print("=" * 78)
    print("DONNÉES STRUCTURÉES")
    print("=" * 78)

    for key, value in (
        result["structured"].items()
    ):

        print()
        print(
            key,
            ":",
            value
        )


    print()
    print("=" * 78)
    print("TEXTE POUR MATCHING")
    print("=" * 78)
    print()

    print(
        result["matching_text"][:8000]
    )
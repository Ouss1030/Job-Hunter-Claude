from __future__ import annotations

from bs4 import BeautifulSoup

from sources.batch3_wallonia_engine import (
    clean,
    dutch_hard,
    finalize,
    geo_status,
    session,
    title_is_target,
)

HYLORIS_VERSION = "1.1"
URL = "https://hyloris.com/careers/"


def _best_vacancy_text(heading):
    title = clean(heading.get_text(" ", strip=True))

    best = ""
    node = heading

    # Select the smallest useful ancestor containing enough vacancy content.
    for _ in range(6):
        node = getattr(node, "parent", None)
        if node is None:
            break

        text = clean(node.get_text(" ", strip=True))
        if title and title.lower() not in text.lower():
            continue

        if 250 <= len(text) <= 6000:
            best = text
            break

        if len(text) > len(best) and len(text) <= 6000:
            best = text

    return best


def collect_hyloris_jobs():
    s = session()
    response = s.get(URL, timeout=30, allow_redirects=True)
    response.raise_for_status()

    soup = BeautifulSoup(response.text, "html.parser")
    rows = []
    seen = set()

    for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
        title = clean(heading.get_text(" ", strip=True))

        if not title or title.lower() in {
            "latest vacancies",
            "grow with us",
            "why join us",
            "careers",
        }:
            continue

        text = _best_vacancy_text(heading)

        if not text:
            continue

        # Only retain blocks that look like actual vacancy cards/sections.
        if "location:" not in text.lower() and not title_is_target(title):
            continue

        low = text.lower()

        if "liège" in low or "liege" in low:
            location = "Liège, Belgium"
        elif "belgium" in low:
            location = "Belgium"
        else:
            location = ""

        key = (title.lower(), location.lower())

        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "title": title,
                "location": location,
                "geo": geo_status(location or text),
                "hard_dutch": dutch_hard(text),
                "description": text,
                "url": response.url,
            }
        )

    return finalize(
        source="HYLORIS",
        company="Hyloris Pharmaceuticals",
        rows=rows,
    )


def probe_hyloris_blocks():
    s = session()
    response = s.get(URL, timeout=30, allow_redirects=True)
    response.raise_for_status()
    soup = BeautifulSoup(response.text, "html.parser")

    blocks = []

    for heading in soup.find_all(["h2", "h3", "h4", "h5"]):
        title = clean(heading.get_text(" ", strip=True))
        if not title:
            continue
        text = _best_vacancy_text(heading)
        if "location:" in text.lower() or title_is_target(title):
            blocks.append(
                {
                    "title": title,
                    "text_len": len(text),
                    "target": title_is_target(title),
                }
            )

    return {
        "http": response.status_code,
        "blocks": blocks,
    }

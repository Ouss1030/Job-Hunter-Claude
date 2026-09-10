"""
JOB HUNTER - JOBAT BROWSER CONSENT V1.1

Gestion du bandeau cookies Jobat pour Playwright.
Optimisation V1.1 : le consentement n'est vérifié/traité qu'UNE SEULE FOIS
par contexte navigateur. Les appels suivants sont des no-op immédiats.

Flux utilisateur :
1) "Définir mes préférences" / équivalent ;
2) "Tout refuser" / équivalent ;
3) sauvegarde du storage_state pour les runs suivants.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

CONSENT_HELPER_VERSION = "1.1"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STATE_DIR = PROJECT_ROOT / "logs" / "jobat_browser_state"
STATE_FILE = STATE_DIR / "storage_state.json"

# Un même contexte Playwright est réutilisé pendant la collecte Jobat.
# On mémorise donc les contextes déjà contrôlés afin de ne pas rescanner le CMP
# après chaque page.goto(). Le set vit seulement pendant le processus courant.
_SESSION_CHECKED_CONTEXT_IDS: set[int] = set()


def valid_storage_state_path() -> str | None:
    """Retourne le chemin de storage_state uniquement s'il est lisible/valide."""
    if not STATE_FILE.exists():
        return None
    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if not isinstance(payload.get("cookies", []), list):
            return None
        return str(STATE_FILE)
    except Exception:
        return None


def save_storage_state(context) -> bool:
    """Sauvegarde cookies + localStorage Playwright localement."""
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        context.storage_state(path=str(STATE_FILE))
        return True
    except Exception:
        return False


def _context_key(context) -> int:
    return id(context)


def _already_checked(context) -> bool:
    return _context_key(context) in _SESSION_CHECKED_CONTEXT_IDS


def _mark_checked(context) -> None:
    _SESSION_CHECKED_CONTEXT_IDS.add(_context_key(context))


def _click_visible(locator, timeout_ms: int = 1800) -> bool:
    try:
        count = locator.count()
    except Exception:
        return False
    for idx in range(min(count, 6)):
        try:
            item = locator.nth(idx)
            if item.is_visible(timeout=250):
                item.click(timeout=timeout_ms)
                return True
        except Exception:
            continue
    return False


def _targets(page):
    result = [page]
    try:
        for frame in page.frames:
            if frame is not page.main_frame:
                result.append(frame)
    except Exception:
        pass
    return result


def _click_preferences(target) -> bool:
    selectors = [
        "#onetrust-pc-btn-handler",
        "button:has-text('Définir mes préférences')",
        "button:has-text('Définir vos préférences')",
        "button:has-text('Définir les préférences')",
        "button:has-text('Gérer mes préférences')",
        "button:has-text('Gérer les préférences')",
        "a:has-text('Définir mes préférences')",
        "a:has-text('Définir vos préférences')",
        "a:has-text('Préférences cookies')",
    ]
    for selector in selectors:
        try:
            if _click_visible(target.locator(selector)):
                return True
        except Exception:
            pass

    patterns = [
        re.compile(r"définir\s+(?:mes|vos|les|ses)?\s*préférences", re.I),
        re.compile(r"gérer\s+(?:mes|vos|les)?\s*préférences", re.I),
        re.compile(r"paramétrer\s+(?:mes|vos|les)?\s*préférences", re.I),
        re.compile(r"cookie\s+preferences", re.I),
    ]
    for pattern in patterns:
        for role in ("button", "link"):
            try:
                if _click_visible(target.get_by_role(role, name=pattern)):
                    return True
            except Exception:
                pass
    return False


def _click_reject_all(target) -> bool:
    selectors = [
        "#onetrust-reject-all-handler",
        "button:has-text('Tout refuser')",
        "button:has-text('Refuser tout')",
        "button:has-text('Reject all')",
        "button:has-text('Alles weigeren')",
        "[data-testid*='reject-all' i]",
        "[id*='reject-all' i]",
    ]
    for selector in selectors:
        try:
            if _click_visible(target.locator(selector)):
                return True
        except Exception:
            pass

    patterns = [
        re.compile(r"^(?:tout\s+refuser|refuser\s+tout)$", re.I),
        re.compile(r"^reject\s+all$", re.I),
        re.compile(r"^alles\s+weigeren$", re.I),
    ]
    for pattern in patterns:
        try:
            if _click_visible(target.get_by_role("button", name=pattern)):
                return True
        except Exception:
            pass
    return False


def handle_jobat_cookie_consent(page, context, verbose: bool = False) -> dict:
    """Traite le CMP Jobat au maximum une fois par contexte navigateur.

    Le premier appel vérifie le CMP et suit le flux demandé. Qu'un bandeau soit
    présent ou non, le contexte est ensuite marqué comme contrôlé. Les appels
    suivants retournent immédiatement : aucune recherche de sélecteur, aucun
    timeout et aucun clic supplémentaire pendant la même session Playwright.
    """
    result = {
        "preferences_clicked": False,
        "reject_all_clicked": False,
        "state_saved": False,
        "handled": False,
        "session_already_checked": False,
    }

    if _already_checked(context):
        result["session_already_checked"] = True
        return result

    # Marquer avant toute interaction : même en cas de CMP absent ou d'exception
    # tolérée, on ne paie pas à nouveau le coût du scan sur chaque page du run.
    _mark_checked(context)

    # Petit délai uniquement au PREMIER contrôle du contexte pour laisser au CMP
    # asynchrone le temps de s'afficher après domcontentloaded.
    try:
        page.wait_for_timeout(350)
    except Exception:
        pass

    targets = _targets(page)

    # 1) Flux demandé : Définir mes préférences.
    for target in targets:
        if _click_preferences(target):
            result["preferences_clicked"] = True
            break

    if result["preferences_clicked"]:
        try:
            page.wait_for_timeout(350)
        except Exception:
            pass
        targets = _targets(page)

    # 2) Tout refuser.
    for target in targets:
        if _click_reject_all(target):
            result["reject_all_clicked"] = True
            break

    # Fallback si le premier écran propose directement « Tout refuser ».
    if not result["reject_all_clicked"] and not result["preferences_clicked"]:
        try:
            page.wait_for_timeout(150)
        except Exception:
            pass
        for target in _targets(page):
            if _click_reject_all(target):
                result["reject_all_clicked"] = True
                break

    result["handled"] = result["preferences_clicked"] or result["reject_all_clicked"]
    if result["handled"]:
        result["state_saved"] = save_storage_state(context)
        if verbose:
            print(
                "JOBAT COOKIES | once_per_context=1 | preferences="
                f"{int(result['preferences_clicked'])} | reject_all={int(result['reject_all_clicked'])} "
                f"| state_saved={int(result['state_saved'])}"
            )
    elif verbose:
        print("JOBAT COOKIES | once_per_context=1 | banner_absent_or_already_persisted=1")

    return result

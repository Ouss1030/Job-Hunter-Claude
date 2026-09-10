"""
JOB HUNTER BELGIUM
CHATGPT HANDOFF - VERSION 1.0

Produit un bundle compact, prêt à coller dans ChatGPT Plus, à partir du
dernier Final Application Pool.

Objectif : franchir le dernier maillon du pipeline. Tout l'amont
(collecte, matching, Gate, Queue, Recheck, Pool) produit des offres
validées ; ce module les transforme en un dossier exploitable pour
générer CV, lettre et email — sans API OpenAI payante.

Aucun appel réseau.
Aucune écriture en base.
Aucune offre marquée APPLIED : ce module ne fait que préparer.

La vérité candidat n'est PAS redéfinie ici : elle est lue depuis
config/ai_generation.py (CANDIDATE_TRUTH, FORBIDDEN_CANDIDATE_CLAIM_TERMS),
qui reste la source unique.

Usage :
    python -m applications.chatgpt_handoff
    python -m applications.chatgpt_handoff --limit 5
    python -m applications.chatgpt_handoff --actions APPLY_NOW
    python -m applications.chatgpt_handoff --track LAB_QC
    python -m applications.chatgpt_handoff --pool CHEMIN.json

Sorties :
    exports/logs/chatgpt_handoff_v1_<horodatage>.md    <- à coller dans ChatGPT
    exports/logs/chatgpt_handoff_v1_<horodatage>.json  <- même contenu, machine
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from config.ai_generation import (
    CANDIDATE_TRUTH,
    DEFAULT_BASE_CV_NAME,
    FORBIDDEN_CANDIDATE_CLAIM_TERMS,
)


HANDOFF_VERSION = "1.0"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = PROJECT_ROOT / "exports" / "logs"
CV_DIR = PROJECT_ROOT / "assets" / "cv"

DEFAULT_ACTIONS = ("APPLY_NOW", "APPLY_NEXT")
DEFAULT_LIMIT = 8
DEFAULT_MAX_DESCRIPTION = 2200

# CV de base par track. LAB_QC est le défaut du projet.
CV_BY_TRACK = {
    "LAB_QC": DEFAULT_BASE_CV_NAME,
    "QUALITY": DEFAULT_BASE_CV_NAME,
    "PRODUCTION_SCIENCE": DEFAULT_BASE_CV_NAME,
    "DATA": DEFAULT_BASE_CV_NAME,
}


# ============================================================
# LECTURE DU POOL
# ============================================================

def latest_pool(explicit: str | None) -> Path:
    if explicit:
        path = Path(explicit)
        if not path.exists():
            raise SystemExit(f"❌ Pool introuvable : {path}")
        return path

    # Du plus récent schéma au plus ancien : V1.2 construit le pool
    # directement depuis le Recheck live, V1.1 et V1 sont conservés
    # pour pouvoir rejouer d'anciens exports.
    for pattern in ("final_application_pool_v12_*.json",
                    "final_application_pool_v11_*.json",
                    "final_application_pool_v1_*.json"):
        found = sorted(LOG_DIR.glob(pattern))
        if found:
            return found[-1]

    raise SystemExit(
        "❌ Aucun final_application_pool_*.json dans exports/logs.\n"
        "   Lance d'abord : python -m applications.final_application_pool"
    )


def load_pool(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))

    if isinstance(payload, list):
        return payload

    items = payload.get("pool")
    if isinstance(items, list):
        return items

    raise SystemExit(f"❌ Format de pool non reconnu : {path.name}")


def field(item: dict, *names: str, default: Any = None) -> Any:
    """
    Chaque version du pool suffixe ses champs recalculés (_v12, _v11).
    On lit du suffixe le plus récent au nom de base, ce qui permet
    d'exploiter aussi bien un pool V1.2 qu'un ancien export.
    """
    for name in names:
        value = item.get(name)
        if value not in (None, ""):
            return value
    return default


def action_of(item: dict) -> str:
    return str(field(item, "recommended_action_v12", "recommended_action_v11",
                     "recommended_action", default="") or "").upper()


def track_of(item: dict) -> str:
    return str(field(item, "cv_track", "track", default="") or "").upper()


def priority_of(item: dict) -> str:
    return str(field(item, "priority_v12", "priority_v11", "priority",
                     default="") or "")


# ============================================================
# SÉLECTION
# ============================================================

def select_offers(pool, actions, track, limit):
    retenues = []

    for item in pool:
        if action_of(item) not in actions:
            continue
        if track and track_of(item) != track:
            continue
        retenues.append(item)

    retenues.sort(
        key=lambda i: (
            field(i, "pool_rank_v12", "pool_rank_v11", "pool_rank",
                  default=9999),
            -float(field(i, "final_score_v12", "final_score_v11",
                         "final_score", default=0) or 0),
        )
    )
    return retenues[:limit] if limit else retenues


def shorten(text: Any, limit: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= limit:
        return value
    coupe = value[:limit].rsplit(" ", 1)[0]
    return coupe + " […texte tronqué, relire l'annonce en ligne avant envoi…]"


# ============================================================
# RENDU DE LA VÉRITÉ CANDIDAT
# ============================================================

def render_candidate_truth() -> list[str]:
    lignes: list[str] = []
    truth = CANDIDATE_TRUTH

    identity = truth.get("identity") or {}
    lignes.append(f"- **Nom** : {identity.get('name', '?')}")
    lignes.append(f"- **Localisation** : {identity.get('location', '?')}")
    lignes.append("")

    lignes.append("**Diplômes**")
    for entry in truth.get("education") or []:
        ligne = (f"- {entry.get('degree', '?')} — {entry.get('institution', '?')} "
                 f"— {entry.get('status', '?')}")
        lignes.append(ligne)
        if entry.get("important"):
            lignes.append(f"  - ⚠️ {entry['important']}")
    lignes.append("")

    exp = truth.get("professional_experience") or {}
    lignes.append("**Expérience professionnelle**")
    lignes.append(f"- Pharma / QC : {exp.get('pharma_qc_years', '?')} ans")
    lignes.append(f"- Data (professionnelle) : "
                  f"{exp.get('data_professional_years', '?')} an(s)")
    for role in exp.get("roles") or []:
        lignes.append(f"- **{role.get('company', '?')}** "
                      f"({role.get('dates', '?')}) — {role.get('role', '?')}")
        for fact in role.get("facts") or []:
            lignes.append(f"  - {fact}")
    lignes.append("")

    # Toute autre section de CANDIDATE_TRUTH est rendue génériquement,
    # pour ne rien perdre si config/ai_generation.py s'enrichit.
    connues = {"identity", "education", "professional_experience"}
    for cle, valeur in truth.items():
        if cle in connues:
            continue
        lignes.append(f"**{cle.replace('_', ' ').capitalize()}**")
        if isinstance(valeur, dict):
            for k, v in valeur.items():
                lignes.append(f"- {k} : {v}")
        elif isinstance(valeur, (list, tuple, set)):
            for v in valeur:
                lignes.append(f"- {v}")
        else:
            lignes.append(f"- {valeur}")
        lignes.append("")

    return lignes


# ============================================================
# RENDU DU BUNDLE
# ============================================================

def render_markdown(offres, meta) -> str:
    L: list[str] = []

    L.append(f"# BUNDLE DE CANDIDATURE — JOB HUNTER BELGIUM v{HANDOFF_VERSION}")
    L.append("")
    L.append(f"Généré le {meta['generated_at']} · {len(offres)} offre(s) · "
             f"source : `{meta['source_pool']}`")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 1. Ce que je te demande")
    L.append("")
    L.append("Tu es mon assistant de candidature. Pour **chaque offre** de la "
             "section 4, produis les livrables de la section 5.")
    L.append("")
    L.append("Travaille offre par offre. Attends ma validation avant de passer "
             "à la suivante si je te le demande.")
    L.append("")

    L.append("## 2. Règles absolues")
    L.append("")
    L.append("Ces règles priment sur toute autre considération de style :")
    L.append("")
    L.append("1. **Ne jamais inventer** une compétence, un diplôme, un outil ou "
             "une expérience qui ne figure pas en section 3.")
    L.append("2. **Je n'ai PAS de diplôme de Master.** J'ai validé un Master 1 en "
             "Sciences pharmaceutiques. La seule formulation acceptable est "
             "« Master 1 en Sciences Pharmaceutiques (validé) ». "
             "Ne jamais écrire ni laisser entendre « Master en Sciences "
             "Pharmaceutiques ».")
    L.append("3. **Zéro année d'expérience professionnelle Data.** Mes compétences "
             "Data viennent du diplôme et des projets, pas d'un poste.")
    L.append("4. Outils à ne **jamais** revendiquer : "
             + ", ".join(f"`{t}`" for t in sorted(FORBIDDEN_CANDIDATE_CLAIM_TERMS))
             + ".")
    L.append("5. Ton attendu : crédible, humain, professionnel, confiant. "
             "Pas de superlatifs, pas de flatterie, pas de formules creuses.")
    L.append("6. Si une information manque pour écrire honnêtement, **demande-la** "
             "au lieu de combler.")
    L.append("")

    L.append("## 3. Vérité candidat (référence unique)")
    L.append("")
    L.extend(render_candidate_truth())

    L.append("## 4. Offres")
    L.append("")

    for index, item in enumerate(offres, start=1):
        track = track_of(item) or "?"
        L.append(f"### Offre {index} — {field(item, 'title', default='?')}")
        L.append("")
        L.append(f"- **Entreprise** : {field(item, 'company', default='?')}")
        L.append(f"- **Lieu** : {field(item, 'location', default='?')}")
        L.append(f"- **URL** : {field(item, 'url', default='?')}")
        L.append(f"- **Source** : {field(item, 'source', default='?')}")
        L.append(f"- **Track CV** : {track}")
        L.append(f"- **CV de base à adapter** : "
                 f"`{CV_BY_TRACK.get(track, DEFAULT_BASE_CV_NAME)}`")
        L.append(f"- **Priorité** : {priority_of(item)} · "
                 f"action : {action_of(item)} · "
                 f"score métier : {field(item, 'match_score', default='?')}/100")
        L.append(f"- **Clé stable** : `{field(item, 'stable_item_key', default='?')}`")

        warnings = field(item, "warnings", default=[]) or []
        if warnings:
            L.append(f"- ⚠️ **Points de vigilance** : {'; '.join(map(str, warnings))}")

        reasons = field(item, "reasons", default=[]) or []
        if reasons:
            L.append(f"- Notes du pipeline : {'; '.join(map(str, reasons))}")

        L.append("")
        L.append("**Annonce :**")
        L.append("")
        L.append("> " + shorten(field(item, "description", default=""),
                                meta["max_description"]).replace("\n", "\n> "))
        L.append("")

    L.append("## 5. Livrables attendus par offre")
    L.append("")
    L.append("1. **CV adapté** — reprend le CV de base indiqué, réordonne et "
             "reformule pour coller à l'annonce. Aucun ajout factuel.")
    L.append("2. **Lettre de motivation** — 250 à 350 mots, dans la langue de "
             "l'annonce, qui relie explicitement mon expérience réelle aux "
             "exigences citées.")
    L.append("3. **Email de candidature** — objet + corps court (100 à 150 mots).")
    L.append("4. **Signaux d'alerte** — dis-moi si l'annonce exige quelque chose "
             "que je n'ai pas, plutôt que de le masquer.")
    L.append("")
    L.append("---")
    L.append("")
    L.append("⚠️ Les annonces expirent. Relis l'offre en ligne au moment de "
             "postuler : le texte ci-dessus est une capture, pas une source "
             "vivante.")
    L.append("")

    return "\n".join(L)


# ============================================================
# MAIN
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="Bundle de candidature prêt à coller dans ChatGPT Plus."
    )
    p.add_argument("--pool", default=None,
                   help="final_application_pool_*.json à utiliser")
    p.add_argument("--limit", type=int, default=DEFAULT_LIMIT,
                   help=f"nombre d'offres (défaut {DEFAULT_LIMIT}, 0 = toutes)")
    p.add_argument("--actions", default=",".join(DEFAULT_ACTIONS),
                   help=f"actions retenues (défaut {','.join(DEFAULT_ACTIONS)})")
    p.add_argument("--track", default=None,
                   help="filtrer sur un track CV (LAB_QC, QUALITY, DATA...)")
    p.add_argument("--max-description", type=int, default=DEFAULT_MAX_DESCRIPTION,
                   help=f"caractères max par annonce (défaut {DEFAULT_MAX_DESCRIPTION})")
    return p.parse_args()


def main():
    args = parse_args()

    pool_path = latest_pool(args.pool)
    pool = load_pool(pool_path)

    actions = tuple(
        a.strip().upper() for a in args.actions.split(",") if a.strip()
    )
    track = args.track.upper() if args.track else None

    print("=" * 78)
    print(f"CHATGPT HANDOFF V{HANDOFF_VERSION}")
    print("=" * 78)
    print()
    print("Pool source   :", pool_path.name)
    print("Offres au pool:", len(pool))
    print("Actions       :", ", ".join(actions))
    if track:
        print("Track         :", track)
    print()

    offres = select_offers(pool, actions, track, args.limit)

    if not offres:
        print("Aucune offre ne correspond aux critères.")
        print()
        print("  actions disponibles :",
              ", ".join(sorted({action_of(i) for i in pool if action_of(i)})))
        print("  tracks disponibles  :",
              ", ".join(sorted({track_of(i) for i in pool if track_of(i)})))

        if track:
            compatibles = sorted({
                action_of(i) for i in pool
                if track_of(i) == track and action_of(i)
            })
            print()
            print(f"  pour le track {track}, actions présentes : "
                  + (", ".join(compatibles) if compatibles
                     else "aucune offre de ce track"))
        return

    print(f"Offres retenues : {len(offres)}")
    print()
    for index, item in enumerate(offres, start=1):
        print(f"  {index:>2}. [{priority_of(item):<3}] "
              f"{track_of(item):<18} "
              f"{str(field(item, 'match_score', default='?')):>5} | "
              f"{str(field(item, 'title', default='?'))[:48]}")
    print()

    meta = {
        "handoff_version": HANDOFF_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_pool": pool_path.name,
        "actions": list(actions),
        "track": track,
        "max_description": args.max_description,
        "offers_count": len(offres),
    }

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    md_path = LOG_DIR / f"chatgpt_handoff_v1_{stamp}.md"
    md_path.write_text(render_markdown(offres, meta), encoding="utf-8")

    json_path = LOG_DIR / f"chatgpt_handoff_v1_{stamp}.json"
    json_path.write_text(
        json.dumps(
            {
                "meta": meta,
                "candidate_truth": CANDIDATE_TRUTH,
                "forbidden_claims": sorted(FORBIDDEN_CANDIDATE_CLAIM_TERMS),
                "offers": [
                    {
                        "stable_item_key": field(i, "stable_item_key"),
                        "title": field(i, "title"),
                        "company": field(i, "company"),
                        "location": field(i, "location"),
                        "url": field(i, "url"),
                        "source": field(i, "source"),
                        "cv_track": track_of(i),
                        "base_cv": CV_BY_TRACK.get(track_of(i),
                                                   DEFAULT_BASE_CV_NAME),
                        "priority": priority_of(i),
                        "recommended_action": action_of(i),
                        "match_score": field(i, "match_score"),
                        "warnings": field(i, "warnings", default=[]),
                        "reasons": field(i, "reasons", default=[]),
                        "description": shorten(field(i, "description", default=""),
                                               args.max_description),
                    }
                    for i in offres
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    taille = md_path.stat().st_size
    print("=" * 78)
    print("Fichiers écrits :")
    print("  ", md_path)
    print("  ", json_path)
    print()
    print(f"Bundle Markdown : {taille / 1024:.1f} Ko "
          f"(~{taille // 4} tokens estimés)")
    print()
    print("Prochaine étape : ouvrir le .md, tout copier, coller dans ChatGPT Plus.")
    print("Aucune offre n'a été marquée APPLIED.")
    print("=" * 78)


if __name__ == "__main__":
    main()

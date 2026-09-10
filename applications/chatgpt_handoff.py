"""
CHATGPT HANDOFF - VERSION 1.0

But
---
Exporter les candidatures finales validées vers des paquets compacts à
envoyer manuellement à ChatGPT Plus.

Aucun appel OpenAI API.
Aucun réseau.
Aucune écriture DB.

Usage principal
---------------
python -m applications.chatgpt_handoff

Par défaut :
- prend le dernier final_application_pool_v12_*.json ;
- exporte APPLY_NOW ;
- crée un ZIP complet ;
- crée des ZIP par lots de 10 offres.

Options
-------
python -m applications.chatgpt_handoff --actions APPLY_NOW
python -m applications.chatgpt_handoff --actions APPLY_NOW APPLY_NEXT
python -m applications.chatgpt_handoff --limit 10
python -m applications.chatgpt_handoff --start 1 --limit 10
python -m applications.chatgpt_handoff --chunk-size 5
python -m applications.chatgpt_handoff --stable-keys ITEM_xxx ITEM_yyy --chunks-only
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import unicodedata
import zipfile
from datetime import datetime
from pathlib import Path

from config.candidate_truth import DEFAULT_BASE_CV_NAME as CANONICAL_DEFAULT_BASE_CV_NAME


HANDOFF_VERSION = "1.0"
HANDOFF_PROMPT_VERSION = "2.0"
HANDOFF_INCLUDE_CV_PATCH_VERSION = "2.1.7"
HANDOFF_BUNDLE_SCHEMA_VERSION = "1.2"

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "exports" / "logs"
EXPORT_ROOT = ROOT / "exports" / "chatgpt_handoff"

DEFAULT_ACTIONS = ["APPLY_NOW"]
DEFAULT_CHUNK_SIZE = 10

BASE_CV_PREFERENCE = CANONICAL_DEFAULT_BASE_CV_NAME

from config.candidate_truth import (
    DEFAULT_BASE_CV_NAME,
    FORBIDDEN_CANDIDATE_CLAIM_TERMS,
    HARD_TRUTH_RULES,
    build_handoff_candidate_truth,
)
from diagnostics.version_support import at_least

CANDIDATE_TRUTH = build_handoff_candidate_truth()


APPLICATION_INSTRUCTIONS = ['OBJECTIF: produire pour chaque offre une candidature réellement spécifique, jamais un CV ou une lettre générique.', "Analyser d'abord l'offre: intitulé cible, missions, compétences obligatoires, mots-clés récurrents, outils, secteur, niveau d'expérience et contraintes.", "Le CV doit réussir deux lectures: le filtre ATS puis la lecture humaine très rapide d'un recruteur en environ 20 à 30 secondes.", 'Optimiser le CV pour les ATS avec une structure simple: une colonne, titres standards, texte sélectionnable, sans tableaux complexes, zones de texte, icônes, jauges, graphiques ni éléments décoratifs qui gênent le parsing.', "Réutiliser naturellement les mots-clés exacts de l'offre uniquement lorsqu'ils correspondent à des faits réellement démontrés dans candidate_truth.json ou le CV source.", "Il est autorisé d'enrichir le vocabulaire avec des synonymes métier, formulations ATS et terminologie du secteur lorsque le sens reste strictement fidèle aux compétences et expériences réelles.", "Interdiction du keyword stuffing: ne jamais empiler des mots-clés, cacher du texte, inventer un outil, une certification, une responsabilité, un résultat, un diplôme, une langue ou une durée d'expérience.", 'Le titre du CV doit être immédiatement aligné avec le poste visé lorsque cette formulation est honnêtement compatible avec le profil.', "Le haut du CV doit concentrer la proposition de valeur: titre ciblé, résumé de 2 à 3 lignes maximum et compétences les plus décisives pour l'offre.", 'CV court et scannable: viser 1 page lorsque raisonnable, maximum 2 pages; phrases courtes; bullets courts; information utile avant information secondaire.', 'Pour les expériences les plus pertinentes, utiliser 3 à 5 bullets courts orientés action et preuve; pour les expériences secondaires, réduire fortement.', 'Chaque bullet doit idéalement tenir sur une ligne ou environ 12 à 20 mots et commencer par une formulation forte, sans prose longue.', 'Ne jamais inventer de chiffres. Quantifier un résultat uniquement si la source candidat fournit réellement ce chiffre.', "Pour LAB_QC / QUALITY / PRODUCTION_SCIENCE, utiliser en priorité le CV LabQC comme base et mettre en avant Pharma/QC/laboratoire/GMP selon l'offre.", "Pour DATA_BI, repositionner honnêtement le profil vers SQL, Python, Power BI, ETL, statistiques, data quality et analyse sans inventer d'expérience professionnelle Data.", "Pour HYBRID, exploiter explicitement la combinaison Chimie/Pharma-QC + Business Data Analysis quand elle répond aux missions de l'offre.", "Corriger toute ancienne mention 'Business Data Analysis — en cours': diplôme terminé en juin 2026.", "La lettre de motivation doit respecter les conventions professionnelles d'une vraie lettre de candidature et tenir sur une page.", "Lettre: coordonnées candidat, destinataire/entreprise si connu, lieu/date, objet précis, formule d'appel, 3 à 4 paragraphes courts, formule de politesse et signature.", "Si aucun nom de recruteur n'est fourni, utiliser 'Madame, Monsieur,'; ne jamais inventer un nom, une adresse ou une fonction de contact.", 'Le premier paragraphe doit nommer le poste et donner immédiatement la raison de la candidature et la proposition de valeur du candidat.', "Le corps de la lettre doit relier 2 à 4 exigences importantes de l'offre à des preuves concrètes du parcours; ne pas réciter tout le CV.", "Un paragraphe doit expliquer pourquoi CE poste/CE contexte correspond au profil, uniquement à partir d'éléments réellement présents dans l'annonce; ne pas inventer des informations sur l'entreprise.", "La conclusion doit être courte, professionnelle et orientée entretien/disponibilité, suivie d'une formule de politesse adaptée.", "Éviter les banalités comme 'entreprise renommée', 'passionné depuis toujours', 'profil parfaitement adapté' ou toute flatterie générique non démontrée.", 'Respecter strictement candidate_truth.json, les guard_flags et warnings. Si une incompatibilité bloquante apparaît, la signaler avant de créer les documents.', 'Livrables attendus: CV Word .docx optimisé ATS, lettre de motivation Word .docx spécifique au poste et, si utile, email de candidature très court.']


def clean_text(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def slugify(value, max_len=72):
    text = unicodedata.normalize("NFKD", clean_text(value))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return (text[:max_len].rstrip("-") or "job")


def latest_file(pattern):
    paths = list(LOG_DIR.glob(pattern))
    if not paths:
        return None
    return max(paths, key=lambda p: p.stat().st_mtime)


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def select_items(payload, actions=None, start=1, limit=None, stable_keys=None):
    """Sélectionne les offres à exporter.

    - Mode historique : filtrage par actions (APPLY_NOW, APPLY_NEXT, ...).
    - Mode V2 UI : sélection manuelle exacte par stable_item_key.

    En mode manuel, aucune autre offre ne peut entrer dans le handoff.
    """
    pool = list(payload.get("pool") or [])

    if stable_keys is not None:
        requested = [clean_text(value) for value in stable_keys if clean_text(value)]
        if not requested:
            return []

        by_key = {clean_text(item.get("stable_item_key")): item for item in pool if clean_text(item.get("stable_item_key"))}
        missing = [key for key in requested if key not in by_key]
        if missing:
            preview = ", ".join(missing[:5])
            suffix = "..." if len(missing) > 5 else ""
            raise RuntimeError(
                f"{len(missing)} offre(s) sélectionnée(s) ne sont plus dans le dernier Final Pool : {preview}{suffix}"
            )

        # On déduplique les clés tout en conservant l'ordre demandé par l'UI.
        selected = []
        seen = set()
        for key in requested:
            if key in seen:
                continue
            seen.add(key)
            selected.append(by_key[key])
        return selected

    actions = actions or DEFAULT_ACTIONS
    wanted = {str(x).upper() for x in actions}

    selected = [
        item
        for item in pool
        if str(
            item.get("recommended_action_v12")
            or item.get("recommended_action")
            or ""
        ).upper() in wanted
    ]

    selected.sort(
        key=lambda x: (
            int(x.get("pool_rank_v12") or 999999),
            -float(x.get("final_score_v12") or 0),
        )
    )

    start_index = max(0, int(start) - 1)
    selected = selected[start_index:]

    if limit is not None:
        selected = selected[: max(0, int(limit))]

    return selected


def compact_job(item):
    return {
        "handoff_version": HANDOFF_VERSION,
        "stable_item_key": item.get("stable_item_key"),
        "pool_rank": item.get("pool_rank_v12"),
        "title": item.get("title"),
        "company": item.get("company"),
        "location": item.get("location"),
        "source": item.get("source"),
        "origin_source": item.get("origin_source"),
        "url": item.get("url"),
        "track": item.get("track"),
        "priority": item.get("priority_v12"),
        "final_score": item.get("final_score_v12"),
        "recommended_action": item.get("recommended_action_v12"),
        "preferred_location": bool(item.get("preferred_location")),
        "recheck_status": item.get("recheck_status"),
        "recheck_version": item.get("recheck_version"),
        "warnings": list(item.get("warnings") or []),
        "guard_level": item.get("guard_level"),
        "guard_flags": list(item.get("guard_flags") or []),
        "reasons": list(item.get("reasons") or []),
        "live_description": clean_text(item.get("description")),
        "application_folder": item.get("application_folder"),
        "planned_output_files": item.get("output_files") or {},
        "base_cv_preference": BASE_CV_PREFERENCE,
        "base_cv_included": True,
        "base_cv_filename": BASE_CV_PREFERENCE,
        "base_cv_source_path": str(find_base_cv_for_handoff(BASE_CV_PREFERENCE) or ""),
    }


def prompt_text(job):
    warnings = job.get("warnings") or []
    guards = job.get("guard_flags") or []

    caution_lines = []
    for value in warnings:
        caution_lines.append(f"- Recheck : {value}")
    for value in guards:
        caution_lines.append(f"- Guard : {value}")

    if not caution_lines:
        caution_lines = ["- Aucun avertissement bloquant détecté dans le pipeline."]

    return f"""CANDIDATURE JOB HUNTER BELGIUM
HANDOFF PROMPT V{HANDOFF_PROMPT_VERSION}

POSTE
-----
Rang : {job.get('pool_rank')}
Titre : {job.get('title')}
Entreprise : {job.get('company')}
Lieu : {job.get('location')}
Source : {job.get('source')}
URL : {job.get('url')}
Track : {job.get('track')}
Priorité : {job.get('priority')}
Action : {job.get('recommended_action')}

MISSION POUR CHATGPT
--------------------
Lis EN PREMIER :
- job.json
- candidate_truth.json
- application_instructions.json
- le CV source Word inclus dans le bundle : {BASE_CV_PREFERENCE}

Ta mission n'est PAS de produire des documents génériques.
Tu dois construire une candidature spécifique à CETTE offre, capable :
1. d'être correctement comprise et classée par un ATS ;
2. de convaincre un recruteur lors d'une lecture très rapide de 20 à 30 secondes.

ÉTAPE 1 — ANALYSE AVANT RÉDACTION
----------------------------------
Avant de créer les documents, identifie mentalement :
- l'intitulé/famille de poste réellement visé ;
- les 5 à 12 mots-clés ou expressions métier les plus importants ;
- les compétences obligatoires et les compétences souhaitées ;
- les outils, méthodes, normes et environnements cités ;
- les missions prioritaires ;
- les contraintes de diplôme, expérience et langues ;
- les 3 à 5 preuves les plus fortes du candidat pour cette offre.

Ne transforme JAMAIS une exigence de l'annonce en compétence du candidat.

ÉTAPE 2 — CV ATS + IMPACT RECRUTEUR
------------------------------------
Le fichier Word {BASE_CV_PREFERENCE} inclus dans le bundle est le CV source réel. Utilise-le comme document de référence à réorganiser, raccourcir et optimiser ; candidate_truth.json reste prioritaire pour corriger toute information obsolète.
Produis un CV Word PERSONNALISÉ et optimisé pour CETTE offre.

Règles ATS :
- structure simple, une colonne et sections standard ;
- pas de tableau complexe, zone de texte, icône, jauge, graphique ou mise en page susceptible de casser le parsing ATS ;
- utiliser naturellement les termes exacts de l'annonce quand un fait candidat équivalent est réellement démontré ;
- tu peux enrichir le vocabulaire avec des synonymes métier et formulations ATS pour mieux faire correspondre le profil au vocabulaire de l'offre, MAIS sans changer le sens ni inventer une compétence ;
- aucun keyword stuffing, aucun mot-clé caché, aucune liste artificielle ;
- aucun outil, diplôme, certification, langue, responsabilité, résultat ou nombre d'années inventé.

Règles impact humain :
- le recruteur doit comprendre le profil et sa pertinence en quelques secondes ;
- titre du CV immédiatement ciblé sur le poste si cette formulation reste honnête ;
- résumé professionnel : 2 à 3 lignes maximum ;
- compétences : uniquement les plus importantes pour CETTE annonce ;
- placer les éléments décisifs dans le premier tiers du CV ;
- phrases courtes, concrètes et denses ;
- bullets courts, idéalement 12 à 20 mots ;
- commencer les bullets par une action/compétence forte ;
- 3 à 5 bullets maximum pour les expériences les plus pertinentes ;
- réduire fortement les expériences secondaires ;
- supprimer les formulations faibles, répétitives ou sans valeur pour ce poste ;
- quantifier seulement lorsqu'un chiffre réel est disponible dans les sources ;
- viser 1 page lorsque raisonnable ; maximum 2 pages.

Adaptation par track :
- LAB_QC / QUALITY / PRODUCTION_SCIENCE : partir prioritairement de {BASE_CV_PREFERENCE} et concentrer le CV sur les preuves Pharma/QC/laboratoire, GMP/BPF, qualité et techniques réellement démontrées pertinentes pour l'offre.
- DATA_BI / DATA : mettre en avant SQL, Python, Power BI, ETL/SSIS, statistiques, data quality, modélisation et projets réellement démontrés, sans prétendre à une expérience professionnelle Data inexistante.
- HYBRID : montrer clairement la valeur de la combinaison Chimie/Pharma-QC + Business Data Analysis lorsqu'elle est utile au poste.

Le Bachelier de spécialisation Business Data Analysis est TERMINÉ depuis juin 2026.
Les sciences pharmaceutiques correspondent à un niveau Master 1 validé, PAS à un Master obtenu.

ÉTAPE 3 — LETTRE DE MOTIVATION PROFESSIONNELLE
-----------------------------------------------
Produis une vraie lettre de motivation Word spécifique à CETTE offre, pas un texte générique réutilisable ailleurs.

Elle doit respecter les conventions d'une lettre professionnelle :
- coordonnées du candidat ;
- destinataire / entreprise lorsque l'information existe ;
- lieu et date ;
- objet précis : candidature au poste visé, avec référence si disponible ;
- formule d'appel correcte ;
- 3 à 4 paragraphes courts ;
- formule de politesse ;
- signature ;
- une page maximum.

Contenu attendu :
1. Ouverture : citer immédiatement le poste et expliquer en quelques lignes pourquoi la candidature a du sens.
2. Preuves : sélectionner 2 à 4 besoins importants de l'annonce et les relier à des expériences, compétences ou projets RÉELLEMENT démontrés.
3. Motivation ciblée : expliquer pourquoi ce poste/contexte est cohérent avec le parcours à partir des informations de l'annonce uniquement.
4. Conclusion : disponibilité/intérêt pour un entretien, formule courte et professionnelle.

À éviter absolument :
- paraphraser tout le CV ;
- flatteries génériques ;
- clichés du type « entreprise renommée », « passionné depuis toujours », « profil parfaitement adapté » ;
- inventer une information sur l'entreprise ;
- inventer le nom d'un recruteur ou une adresse ;
- masquer un écart important du profil.

Si aucun nom de contact n'est fourni, utilise « Madame, Monsieur, ».

ÉTAPE 4 — CONTRÔLE VÉRITÉ
--------------------------
Avant de finaliser :
- vérifie chaque affirmation contre candidate_truth.json et les informations de job.json ;
- respecte les warnings et guard_flags ci-dessous ;
- si une exigence bloquante est découverte, SIGNALE-LA avant de générer les documents ;
- ne fabrique aucune compétence, aucun diplôme, aucune langue, aucune durée d'expérience, aucun résultat et aucune certification.

POINTS DE VIGILANCE
-------------------
{chr(10).join(caution_lines)}

LIVRABLES
---------
1. CV Word ATS optimisé et ciblé :
{(job.get('planned_output_files') or {}).get('cv_docx', 'CV.docx')}

2. Lettre de motivation Word conventionnelle et spécifique :
{(job.get('planned_output_files') or {}).get('cover_letter_docx', 'Lettre_Motivation.docx')}

3. Email de candidature bref si utile :
{(job.get('planned_output_files') or {}).get('email_txt', 'Email.txt')}

CRITÈRE FINAL
-------------
Le résultat doit être assez fidèle pour être défendable en entretien, assez riche en vocabulaire métier pour maximiser le matching ATS, et assez court/impactant pour donner envie au recruteur de poursuivre sa lecture.
"""


def write_job_folder(parent, job):
    rank = int(job.get("pool_rank") or 999)
    folder = parent / (
        f"{rank:02d}_{slugify(job.get('company'), 32)}_"
        f"{slugify(job.get('title'), 48)}"
    )
    folder.mkdir(parents=True, exist_ok=True)

    (folder / "job.json").write_text(
        json.dumps(job, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (folder / "PROMPT_CHATGPT.txt").write_text(
        prompt_text(job),
        encoding="utf-8",
    )

    return folder


HANDOFF_PROJECT_ROOT = Path(__file__).resolve().parents[1]

CV_SEARCH_DIRS_HANDOFF = (
    HANDOFF_PROJECT_ROOT,
    HANDOFF_PROJECT_ROOT / "cv",
    HANDOFF_PROJECT_ROOT / "CV",
    HANDOFF_PROJECT_ROOT / "assets",
    HANDOFF_PROJECT_ROOT / "assets" / "cv",
    HANDOFF_PROJECT_ROOT / "documents",
    HANDOFF_PROJECT_ROOT / "documents" / "cv",
)


def find_base_cv_for_handoff(filename):
    filename = Path(str(filename)).name
    for directory in CV_SEARCH_DIRS_HANDOFF:
        candidate = directory / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def zip_tree(source_dir, zip_path):
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in source_dir.rglob("*"):
            if path.is_file():
                zf.write(path, arcname=str(path.relative_to(source_dir)))


def export_handoff(actions=None, start=1, limit=None, chunk_size=DEFAULT_CHUNK_SIZE, stable_keys=None, create_full_zip=True):
    source = latest_file("final_application_pool_v12_*.json")
    if source is None:
        raise RuntimeError(
            "Aucun final_application_pool_v12_*.json trouvé dans exports/logs."
        )

    payload = load_json(source)

    if not at_least(str(payload.get("pool_version")), "1.2"):
        raise RuntimeError(
            f"Pool inattendu : {payload.get('pool_version')!r}. V1.2 requis."
        )

    selected = select_items(
        payload,
        actions=actions,
        start=start,
        limit=limit,
        stable_keys=stable_keys,
    )

    if not selected:
        raise RuntimeError("Aucune candidature ne correspond aux filtres.")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_dir = EXPORT_ROOT / f"handoff_v1_{stamp}"
    jobs_dir = export_dir / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)

    compact_jobs = [compact_job(item) for item in selected]

    for job in compact_jobs:
        write_job_folder(jobs_dir, job)

    candidate_path = export_dir / "candidate_truth.json"
    candidate_path.write_text(
        json.dumps(CANDIDATE_TRUTH, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    instructions_path = export_dir / "application_instructions.json"
    instructions_path.write_text(
        json.dumps(APPLICATION_INSTRUCTIONS, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


    base_cv_source = find_base_cv_for_handoff(BASE_CV_PREFERENCE)
    if base_cv_source is None:
        searched = ", ".join(str(p) for p in CV_SEARCH_DIRS_HANDOFF)
        raise RuntimeError(
            f"CV de base introuvable : {BASE_CV_PREFERENCE}. "
            f"Emplacements testés : {searched}"
        )

    base_cv_bundle_path = export_dir / BASE_CV_PREFERENCE
    shutil.copy2(base_cv_source, base_cv_bundle_path)

    selection_mode = "MANUAL_STABLE_KEYS" if stable_keys is not None else "ACTIONS"
    manifest_actions = list(actions or DEFAULT_ACTIONS) if stable_keys is None else []

    manifest = {
        "handoff_version": HANDOFF_VERSION,
        "bundle_schema_version": HANDOFF_BUNDLE_SCHEMA_VERSION,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source_final_pool": str(source),
        "source_pool_version": payload.get("pool_version"),
        "selection_mode": selection_mode,
        "actions": manifest_actions,
        "start": int(start) if stable_keys is None else None,
        "limit": limit if stable_keys is None else None,
        "selected_count": len(compact_jobs),
        "chunk_size": int(chunk_size),
        "base_cv_preference": BASE_CV_PREFERENCE,
        "base_cv_included": True,
        "base_cv_filename": BASE_CV_PREFERENCE,
        "base_cv_source_path": str(find_base_cv_for_handoff(BASE_CV_PREFERENCE) or ""),
        "jobs": [
            {
                "pool_rank": job.get("pool_rank"),
                "stable_item_key": job.get("stable_item_key"),
                "title": job.get("title"),
                "company": job.get("company"),
                "source": job.get("source"),
                "track": job.get("track"),
                "priority": job.get("priority"),
                "recommended_action": job.get("recommended_action"),
            }
            for job in compact_jobs
        ],
    }

    (export_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    readme = f"""CHATGPT HANDOFF V1.0

Source :
{source}

Pool source :
{payload.get('pool_version')}

Actions :
{', '.join(manifest_actions) if manifest_actions else 'SÉLECTION MANUELLE'}

Candidatures exportées :
{len(compact_jobs)}

CV de base préféré :
{BASE_CV_PREFERENCE}

FICHIERS GLOBAUX
----------------
candidate_truth.json
application_instructions.json
{BASE_CV_PREFERENCE}

Chaque job.json contient uniquement les données propres à l'offre.

UTILISATION
-----------
1. Envoyer à ChatGPT un ZIP de lot.
2. Lui demander de traiter les candidatures une par une.
3. Pour chaque offre, ChatGPT doit d'abord vérifier l'éligibilité sur
   job.json puis générer CV Word + lettre Word sans rien inventer.
4. Ne jamais marquer une offre APPLIED tant que la candidature n'a pas
   réellement été envoyée.
"""
    (export_dir / "README.txt").write_text(readme, encoding="utf-8")

    # ZIP complet : conservé pour la compatibilité CLI historique, mais
    # l'interface V2 le désactive afin de ne créer que les chunks demandés.
    full_zip = None
    if create_full_zip:
        full_zip = export_dir.parent / f"{export_dir.name}_ALL.zip"
        zip_tree(export_dir, full_zip)

    # ZIP par chunks
    chunk_paths = []
    if chunk_size and int(chunk_size) > 0:
        chunk_size = int(chunk_size)
        for index in range(0, len(compact_jobs), chunk_size):
            chunk_jobs = compact_jobs[index:index + chunk_size]
            chunk_no = index // chunk_size + 1
            chunk_dir = export_dir.parent / (
                f"{export_dir.name}_chunk_{chunk_no:02d}"
            )
            if chunk_dir.exists():
                shutil.rmtree(chunk_dir)
            (chunk_dir / "jobs").mkdir(parents=True)

            shutil.copy2(candidate_path, chunk_dir / "candidate_truth.json")
            chunk_base_cv_source = find_base_cv_for_handoff(BASE_CV_PREFERENCE)
            if chunk_base_cv_source is None:
                searched = ", ".join(str(p) for p in CV_SEARCH_DIRS_HANDOFF)
                raise RuntimeError(
                    f"CV de base introuvable pour le chunk : {BASE_CV_PREFERENCE}. "
                    f"Emplacements testés : {searched}"
                )
            shutil.copy2(chunk_base_cv_source, chunk_dir / BASE_CV_PREFERENCE)
            shutil.copy2(
                instructions_path,
                chunk_dir / "application_instructions.json",
            )

            chunk_manifest = {
                "base_cv_included": True,
                "base_cv_filename": BASE_CV_PREFERENCE,
                **manifest,
                "selected_count": len(chunk_jobs),
                "chunk_number": chunk_no,
                "jobs": [
                    row for row in manifest["jobs"]
                    if row["stable_item_key"]
                    in {j["stable_item_key"] for j in chunk_jobs}
                ],
            }
            (chunk_dir / "manifest.json").write_text(
                json.dumps(chunk_manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            shutil.copy2(export_dir / "README.txt", chunk_dir / "README.txt")

            for job in chunk_jobs:
                write_job_folder(chunk_dir / "jobs", job)

            chunk_zip = export_dir.parent / (
                f"{export_dir.name}_chunk_{chunk_no:02d}.zip"
            )
            zip_tree(chunk_dir, chunk_zip)
            chunk_paths.append(chunk_zip)
            shutil.rmtree(chunk_dir)

    print("=" * 92)
    print("CHATGPT HANDOFF V1.0")
    print("=" * 92)
    print("Source             :", source)
    print("Sélection          :", "manuelle" if stable_keys is not None else ", ".join(manifest_actions))
    print("Candidatures       :", len(compact_jobs))
    print("Dossier            :", export_dir)
    print("ZIP complet        :", full_zip or "non créé")
    print("ZIP lots           :", len(chunk_paths))
    for path in chunk_paths:
        print(" -", path)
    print()
    print("✅ HANDOFF CHATGPT CRÉÉ SANS API.")

    return {
        "export_dir": export_dir,
        "full_zip": full_zip,
        "chunk_zips": chunk_paths,
        "manifest": manifest,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--actions",
        nargs="+",
        default=DEFAULT_ACTIONS,
        help="Ex. APPLY_NOW APPLY_NEXT",
    )
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
    )
    parser.add_argument(
        "--stable-keys",
        nargs="+",
        default=None,
        help="Sélection manuelle exacte de stable_item_key (V2 UI).",
    )
    parser.add_argument(
        "--chunks-only",
        action="store_true",
        help="Ne pas créer le ZIP ALL, uniquement les chunks.",
    )
    args = parser.parse_args()

    export_handoff(
        actions=args.actions,
        start=args.start,
        limit=args.limit,
        chunk_size=args.chunk_size,
        stable_keys=args.stable_keys,
        create_full_zip=not args.chunks_only,
    )


if __name__ == "__main__":
    main()

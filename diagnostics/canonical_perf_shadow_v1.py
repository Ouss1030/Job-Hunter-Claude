"""
JOB HUNTER BELGIUM
CANONICAL V3.1.2 - SHADOW DE PERFORMANCE - VERSION 1.0

    python -m diagnostics.canonical_perf_shadow_v1            # echantillon de 30 000 paires par passe
    python -m diagnostics.canonical_perf_shadow_v1 --paires 5000

Probleme (run du 16/09/2026) : l'etape « Build canonique » a dure 2 h 18
sur 3 h 43 de run principal. 66 275 offres actives, 626 576 paires
intra-source et 424 088 paires cross-source ; pour chacune,
calculate_raw_pair() calcule la similarite de description
(difflib.SequenceMatcher sur des textes jusqu'a 8 000 caracteres) AVANT
de verifier si le titre, l'entreprise et le lieu permettent encore a la
paire d'aboutir. Or evaluate_intra_pair() rend None des que
company < 0.90 ou location < 0.80, sans regarder la description.

Ce diagnostic NE MODIFIE RIEN : Canonical V3.1.2 est frozen. Il mesure,
sur un echantillon de paires reelles, ce que donnerait un calcul
paresseux de la description :

    intra  : description calculee seulement si titre >= 0.995,
             entreprise >= 0.90 et lieu >= 0.80 (sinon la paire est
             rejetee quelle que soit la description)
    cross  : description calculee seulement si la paire peut atteindre
             pair_score >= 0.63 avec D = 1 (sinon elle ne peut etre ni
             auto, ni review, ni depasser une paire qui le peut)

et verifie que chaque decision (None / AUTO / STRONG / REVIEW, scores,
motifs) est identique a celle de l'algorithme actuel. Si c'est le cas
et que le gain est net, l'integration est un patch de trois fonctions
dans database/canonical.py, a valider avant/apres sur un build complet.
"""

from __future__ import annotations

import argparse
import random
import time

from database import canonical as C
from database.db import get_raw_jobs_for_dedup


SHADOW_VERSION = "1.0"


# ------------------------------------------------------------------
# Variantes paresseuses (memes formules, ordre different)
# ------------------------------------------------------------------

def _raw_pair_partiel(job_a, job_b):
    title_score = C.title_similarity(job_a, job_b)
    company_score = C.company_similarity(job_a, job_b)
    location_score = C.location_similarity(job_a, job_b)
    return title_score, company_score, location_score


def _raw_pair_final(job_a, job_b, title_score, company_score, location_score, description_score):
    hash_a = job_a["_description_hash"]
    hash_b = job_b["_description_hash"]
    exact_description = bool(hash_a and hash_b and hash_a == hash_b)
    date_a = C.clean_text(job_a.get("date_published"))
    date_b = C.clean_text(job_b.get("date_published"))
    same_publication_date = bool(date_a and date_a == date_b)
    pair_score = (title_score * 0.44 + company_score * 0.30 + location_score * 0.18 + description_score * 0.08)
    return {
        "raw_job_id_a": int(job_a["id"]), "raw_job_id_b": int(job_b["id"]),
        "title_score": round(title_score, 6), "company_score": round(company_score, 6),
        "location_score": round(location_score, 6), "description_score": round(description_score, 6),
        "pair_score": round(pair_score, 6), "exact_description": exact_description,
        "same_publication_date": same_publication_date,
    }


def evaluate_intra_pair_lazy(job_a, job_b):
    t, c, l = _raw_pair_partiel(job_a, job_b)
    if t < C.INTRA_TITLE_MIN:
        return None, False
    if c < C.INTRA_REVIEW_COMPANY_MIN or l < C.INTRA_REVIEW_LOCATION_MIN:
        return None, False  # ni auto, ni strong, ni review : la description ne change rien
    d = C.description_similarity(job_a, job_b)
    result = _raw_pair_final(job_a, job_b, t, c, l, d)
    # A partir d'ici : copie exacte d'evaluate_intra_pair
    auto_merge = (result["title_score"] >= C.INTRA_TITLE_MIN and result["company_score"] >= C.INTRA_COMPANY_MIN
                  and result["location_score"] >= C.INTRA_LOCATION_MIN and result["same_publication_date"]
                  and (result["exact_description"] or result["description_score"] >= C.INTRA_DESCRIPTION_AUTO_MIN))
    strong = (not auto_merge and result["company_score"] >= C.INTRA_COMPANY_MIN
              and result["location_score"] >= C.INTRA_LOCATION_MIN
              and result["description_score"] >= C.INTRA_STRONG_DESCRIPTION_MIN)
    review = (not auto_merge and not strong and result["company_score"] >= C.INTRA_REVIEW_COMPANY_MIN
              and result["location_score"] >= C.INTRA_REVIEW_LOCATION_MIN)
    if not auto_merge and not strong and not review:
        return None, True
    level = "AUTO_INTRA_STRICT" if auto_merge else ("STRONG_REVIEW" if strong else "REVIEW")
    reason = (f"{level}; D={result['description_score']:.3f}; "
              + ("même date" if result["same_publication_date"] else "date différente/inconnue"))
    result.update({"scope": "INTRA", "auto_merge": auto_merge, "strong": strong, "review": review, "reason": reason})
    return result, True


def best_raw_pair_lazy(atom_a, atom_b):
    candidates, calcules = [], 0
    for job_a in atom_a["members"]:
        for job_b in atom_b["members"]:
            t, c, l = _raw_pair_partiel(job_a, job_b)
            borne = t * 0.44 + c * 0.30 + l * 0.18 + 0.08
            if borne >= C.CROSS_REVIEW_PAIR_MIN:
                d = C.description_similarity(job_a, job_b)
                calcules += 1
            else:
                d = 0.0  # la paire ne peut ni etre retenue ni depasser une paire retenue
            candidates.append(_raw_pair_final(job_a, job_b, t, c, l, d))
    if not candidates:
        return None, 0
    return max(candidates, key=lambda r: (r["pair_score"], r["description_score"], r["title_score"])), calcules


def evaluate_cross_atoms_lazy(atom_a, atom_b, signature_counts):
    result, calcules = best_raw_pair_lazy(atom_a, atom_b)
    if result is None or result["title_score"] < 0.78:
        return None, calcules
    count_a = signature_counts[(atom_a["channel"], C.atom_signature(atom_a))]
    count_b = signature_counts[(atom_b["channel"], C.atom_signature(atom_b))]
    ambiguous = count_a > 1 or count_b > 1
    exact_unique = (not ambiguous and result["title_score"] >= C.CROSS_EXACT_TITLE_MIN
                    and result["company_score"] >= C.CROSS_EXACT_COMPANY_MIN
                    and result["location_score"] >= C.CROSS_EXACT_LOCATION_MIN)
    evidence_enough = (result["title_score"] >= C.CROSS_TITLE_MIN and result["company_score"] >= C.CROSS_COMPANY_MIN
                       and result["location_score"] >= C.CROSS_LOCATION_MIN
                       and result["description_score"] >= C.CROSS_DESCRIPTION_MIN)
    auto_merge = exact_unique or evidence_enough
    review = (not auto_merge and result["title_score"] >= C.CROSS_REVIEW_TITLE_MIN
              and result["pair_score"] >= C.CROSS_REVIEW_PAIR_MIN)
    reason_parts = [f"signature {'ambiguë' if ambiguous else 'unique'} ({count_a} vs {count_b})"]
    if exact_unique:
        reason_parts.append("cross exact unique")
    if evidence_enough:
        reason_parts.append("cross description forte")
    if ambiguous and not auto_merge:
        reason_parts.append(f"preuve description insuffisante D={result['description_score']:.3f}")
    result.update({"scope": "CROSS", "atom_id_a": atom_a["atom_id"], "atom_id_b": atom_b["atom_id"],
                   "ambiguous_signature": ambiguous, "signature_count_a": count_a, "signature_count_b": count_b,
                   "auto_merge": auto_merge, "strong": False, "review": review, "reason": "; ".join(reason_parts)})
    return result, calcules


# ------------------------------------------------------------------
# Comparaison
# ------------------------------------------------------------------

def _meme_decision_intra(ref, lazy):
    return ref == lazy


def _meme_decision_cross(ref, lazy):
    if (ref is None) != (lazy is None):
        return False
    if ref is None:
        return True
    retenu_ref = ref["auto_merge"] or ref["review"]
    retenu_lazy = lazy["auto_merge"] or lazy["review"]
    if retenu_ref != retenu_lazy:
        return False
    if not retenu_ref:
        return True  # resultat inerte : jamais persiste, jamais utilise
    return ref == lazy


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--paires", type=int, default=30000, help="paires echantillonnees par passe")
    p.add_argument("--graine", type=int, default=16)
    args = p.parse_args()
    rng = random.Random(args.graine)

    print("=" * 78)
    print(f"CANONICAL V3.1.2 - SHADOW DE PERFORMANCE V{SHADOW_VERSION}  (aucune ecriture)")
    print("=" * 78)
    t0 = time.perf_counter()
    jobs = C.prepare_jobs(get_raw_jobs_for_dedup(active_only=True))
    print(f"RAW actifs prepares : {len(jobs)}  ({time.perf_counter() - t0:.1f} s)")

    # ---- PASS 1
    intra_pairs = list(C.build_intra_candidate_pairs(jobs))
    print(f"\nPASS 1 - paires intra-source : {len(intra_pairs)}")
    echantillon = rng.sample(intra_pairs, min(args.paires, len(intra_pairs)))
    t0 = time.perf_counter()
    ref = [C.evaluate_intra_pair(jobs[a], jobs[b]) for a, b in echantillon]
    t_ref = time.perf_counter() - t0
    t0 = time.perf_counter()
    lazy = [evaluate_intra_pair_lazy(jobs[a], jobs[b]) for a, b in echantillon]
    t_lazy = time.perf_counter() - t0
    calcules = sum(1 for _, c in lazy if c)
    ecarts = sum(1 for r, (l, _) in zip(ref, lazy) if not _meme_decision_intra(r, l))
    retenus = sum(1 for r in ref if r)
    print(f"  echantillon        : {len(echantillon)} paires ; retenues (auto/strong/review) : {retenus}")
    print(f"  descriptions calculees : actuel {len(echantillon)} | paresseux {calcules} ({100 * calcules / max(1, len(echantillon)):.1f} %)")
    print(f"  temps              : actuel {t_ref:.1f} s | paresseux {t_lazy:.1f} s | gain x{t_ref / max(t_lazy, 1e-6):.1f}")
    proj_ref = t_ref / len(echantillon) * len(intra_pairs)
    proj_lazy = t_lazy / len(echantillon) * len(intra_pairs)
    print(f"  projection passe 1 : actuel {proj_ref / 60:.0f} min | paresseux {proj_lazy / 60:.0f} min")
    print(f"  decisions differentes : {ecarts}")
    ok1 = ecarts == 0

    # ---- PASS 2 (atoms construits avec la variante paresseuse, identique par construction si ok1)
    print("\nPASS 1 complet (paresseux) pour construire les atoms...")
    t0 = time.perf_counter()
    intra_results = []
    for a, b in intra_pairs:
        r, _ = evaluate_intra_pair_lazy(jobs[a], jobs[b])
        if r:
            intra_results.append(r)
    atoms, accepted = C.build_intra_atoms(jobs, intra_results)
    print(f"  {len(intra_results)} resultats, {len(accepted)} auto acceptees, {len(atoms)} atoms  ({(time.perf_counter() - t0) / 60:.1f} min)")

    cross_pairs = list(C.build_cross_candidate_pairs(atoms))
    counts = C.build_signature_counts(atoms)
    by_id = {a["atom_id"]: a for a in atoms}
    print(f"\nPASS 2 - paires cross-source : {len(cross_pairs)}")
    echantillon = rng.sample(cross_pairs, min(args.paires, len(cross_pairs)))
    t0 = time.perf_counter()
    ref = [C.evaluate_cross_atoms(by_id[a], by_id[b], counts) for a, b in echantillon]
    t_ref = time.perf_counter() - t0
    t0 = time.perf_counter()
    lazy = [evaluate_cross_atoms_lazy(by_id[a], by_id[b], counts) for a, b in echantillon]
    t_lazy = time.perf_counter() - t0
    calcules = sum(c for _, c in lazy)
    total_raw_pairs = sum(len(by_id[a]["members"]) * len(by_id[b]["members"]) for a, b in echantillon)
    ecarts = sum(1 for r, (l, _) in zip(ref, lazy) if not _meme_decision_cross(r, l))
    retenus = sum(1 for r in ref if r and (r["auto_merge"] or r["review"]))
    print(f"  echantillon        : {len(echantillon)} paires d'atoms ({total_raw_pairs} paires RAW) ; retenues (auto/review) : {retenus}")
    print(f"  descriptions calculees : actuel {total_raw_pairs} | paresseux {calcules} ({100 * calcules / max(1, total_raw_pairs):.1f} %)")
    print(f"  temps              : actuel {t_ref:.1f} s | paresseux {t_lazy:.1f} s | gain x{t_ref / max(t_lazy, 1e-6):.1f}")
    proj_ref = t_ref / len(echantillon) * len(cross_pairs)
    proj_lazy = t_lazy / len(echantillon) * len(cross_pairs)
    print(f"  projection passe 2 : actuel {proj_ref / 60:.0f} min | paresseux {proj_lazy / 60:.0f} min")
    print(f"  decisions differentes : {ecarts}")
    ok2 = ecarts == 0

    print("\n" + "=" * 78)
    print("[OK] decisions identiques sur les deux passes" if ok1 and ok2 else "[FAIL] au moins une decision differe : ne pas integrer")
    print("=" * 78)
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    raise SystemExit(main())

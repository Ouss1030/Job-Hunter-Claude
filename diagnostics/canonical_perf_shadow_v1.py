"""
JOB HUNTER BELGIUM
CANONICAL - SHADOW DE PERFORMANCE ET D'EQUIVALENCE - VERSION 1.1

    python -m diagnostics.canonical_perf_shadow_v1            # 30 000 paires par passe
    python -m diagnostics.canonical_perf_shadow_v1 --paires 5000

Probleme (run du 16/09/2026) : l'etape « Build canonique » a dure 2 h 18
sur 3 h 43 de run principal. 66 275 offres actives, 626 576 paires
intra-source et 424 088 paires cross-source ; pour chacune, V3.1.2
calculait la similarite de description (difflib.SequenceMatcher sur des
textes jusqu'a 8 000 caracteres) AVANT de verifier si le titre,
l'entreprise et le lieu permettaient encore a la paire d'aboutir.

V3.1.3 calcule la description paresseusement. Ce diagnostic garde ici,
verbatim, les fonctions de V3.1.2 (reference) et les compare a celles du
module database/canonical.py en place (candidat), sur un echantillon de
paires reelles : chaque decision (None / AUTO / STRONG / REVIEW), chaque
score persiste et chaque motif doivent etre identiques. Il mesure aussi
le temps et le nombre de descriptions calculees.

Ce diagnostic NE MODIFIE RIEN dans la base.

Resultat du 17/09/2026 (V1.0, avant integration) : 0 ecart sur 6 000
paires ; passe 1 99 -> 19 min, passe 2 55 -> 22 min.
"""

from __future__ import annotations

import argparse
import random
import time

from database import canonical as C
from database.db import get_raw_jobs_for_dedup


SHADOW_VERSION = "1.1"


# ------------------------------------------------------------------
# Reference : V3.1.2, copie verbatim (seules les fonctions de similarite,
# inchangees, sont prises dans le module)
# ------------------------------------------------------------------

def _ref_calculate_raw_pair(job_a, job_b):
    title_score = C.title_similarity(job_a, job_b)
    company_score = C.company_similarity(job_a, job_b)
    location_score = C.location_similarity(job_a, job_b)
    description_score = C.description_similarity(job_a, job_b)
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


def _ref_evaluate_intra_pair(job_a, job_b):
    result = _ref_calculate_raw_pair(job_a, job_b)
    if result["title_score"] < C.INTRA_TITLE_MIN:
        return None
    auto_merge = (result["title_score"] >= C.INTRA_TITLE_MIN and result["company_score"] >= C.INTRA_COMPANY_MIN
                  and result["location_score"] >= C.INTRA_LOCATION_MIN and result["same_publication_date"]
                  and (result["exact_description"] or result["description_score"] >= C.INTRA_DESCRIPTION_AUTO_MIN))
    strong = (not auto_merge and result["company_score"] >= C.INTRA_COMPANY_MIN
              and result["location_score"] >= C.INTRA_LOCATION_MIN
              and result["description_score"] >= C.INTRA_STRONG_DESCRIPTION_MIN)
    review = (not auto_merge and not strong and result["company_score"] >= C.INTRA_REVIEW_COMPANY_MIN
              and result["location_score"] >= C.INTRA_REVIEW_LOCATION_MIN)
    if not auto_merge and not strong and not review:
        return None
    level = "AUTO_INTRA_STRICT" if auto_merge else ("STRONG_REVIEW" if strong else "REVIEW")
    reason = (f"{level}; D={result['description_score']:.3f}; "
              + ("même date" if result["same_publication_date"] else "date différente/inconnue"))
    result.update({"scope": "INTRA", "auto_merge": auto_merge, "strong": strong, "review": review, "reason": reason})
    return result


def _ref_best_raw_pair_between_atoms(atom_a, atom_b):
    candidates = [_ref_calculate_raw_pair(a, b) for a in atom_a["members"] for b in atom_b["members"]]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r["pair_score"], r["description_score"], r["title_score"]))


def _ref_evaluate_cross_atoms(atom_a, atom_b, signature_counts):
    result = _ref_best_raw_pair_between_atoms(atom_a, atom_b)
    if result is None or result["title_score"] < 0.78:
        return None
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
    return result


# ------------------------------------------------------------------
# Comparaison
# ------------------------------------------------------------------

class _Compteur:
    """Compte les appels a description_similarity pendant un bloc."""

    def __init__(self):
        self.n = 0
        self._orig = C.description_similarity

    def __enter__(self):
        def compte(a, b):
            self.n += 1
            return self._orig(a, b)
        C.description_similarity = compte
        return self

    def __exit__(self, *exc):
        C.description_similarity = self._orig


def _meme_decision_intra(ref, cand):
    return ref == cand


def _meme_decision_cross(ref, cand):
    if (ref is None) != (cand is None):
        return False
    if ref is None:
        return True
    retenu_ref = ref["auto_merge"] or ref["review"]
    retenu_cand = cand["auto_merge"] or cand["review"]
    if retenu_ref != retenu_cand:
        return False
    if not retenu_ref:
        return True  # resultat inerte : jamais persiste, jamais utilise
    return ref == cand


def _mesurer(nom, echantillon, f_ref, f_cand, total_pairs):
    t0 = time.perf_counter()
    with _Compteur() as c_ref:
        ref = [f_ref(*e) for e in echantillon]
    t_ref = time.perf_counter() - t0
    t0 = time.perf_counter()
    with _Compteur() as c_cand:
        cand = [f_cand(*e) for e in echantillon]
    t_cand = time.perf_counter() - t0
    return ref, cand, t_ref, t_cand, c_ref.n, c_cand.n


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--paires", type=int, default=30000, help="paires echantillonnees par passe")
    p.add_argument("--graine", type=int, default=16)
    args = p.parse_args()
    rng = random.Random(args.graine)

    print("=" * 78)
    print(f"CANONICAL - SHADOW DE PERFORMANCE ET D'EQUIVALENCE V{SHADOW_VERSION}  (aucune ecriture)")
    print(f"reference : V3.1.2 (copie verbatim) | candidat : database/canonical.py V{C.SCHEMA_VERSION}")
    print("=" * 78)
    t0 = time.perf_counter()
    jobs = C.prepare_jobs(get_raw_jobs_for_dedup(active_only=True))
    print(f"RAW actifs prepares : {len(jobs)}  ({time.perf_counter() - t0:.1f} s)")

    # ---- PASS 1
    intra_pairs = list(C.build_intra_candidate_pairs(jobs))
    print(f"\nPASS 1 - paires intra-source : {len(intra_pairs)}")
    echantillon = [(jobs[a], jobs[b]) for a, b in rng.sample(intra_pairs, min(args.paires, len(intra_pairs)))]
    ref, cand, t_ref, t_cand, d_ref, d_cand = _mesurer("intra", echantillon, _ref_evaluate_intra_pair, C.evaluate_intra_pair, len(intra_pairs))
    ecarts = sum(1 for r, c in zip(ref, cand) if not _meme_decision_intra(r, c))
    print(f"  echantillon        : {len(echantillon)} paires ; retenues (auto/strong/review) : {sum(1 for r in ref if r)}")
    print(f"  descriptions calculees : reference {d_ref} | candidat {d_cand} ({100 * d_cand / max(1, d_ref):.1f} %)")
    print(f"  temps              : reference {t_ref:.1f} s | candidat {t_cand:.1f} s | gain x{t_ref / max(t_cand, 1e-6):.1f}")
    print(f"  projection passe 1 : reference {t_ref / len(echantillon) * len(intra_pairs) / 60:.0f} min | candidat {t_cand / len(echantillon) * len(intra_pairs) / 60:.0f} min")
    print(f"  decisions differentes : {ecarts}")
    ok1 = ecarts == 0

    # ---- PASS 2 (atoms construits avec le candidat ; identiques a la reference si ok1)
    print("\nPASS 1 complet (candidat) pour construire les atoms...")
    t0 = time.perf_counter()
    intra_results = [r for a, b in intra_pairs for r in [C.evaluate_intra_pair(jobs[a], jobs[b])] if r]
    atoms, accepted = C.build_intra_atoms(jobs, intra_results)
    print(f"  {len(intra_results)} resultats, {len(accepted)} auto acceptees, {len(atoms)} atoms  ({(time.perf_counter() - t0) / 60:.1f} min)")

    cross_pairs = list(C.build_cross_candidate_pairs(atoms))
    counts = C.build_signature_counts(atoms)
    by_id = {a["atom_id"]: a for a in atoms}
    print(f"\nPASS 2 - paires cross-source : {len(cross_pairs)}")
    echantillon = [(by_id[a], by_id[b], counts) for a, b in rng.sample(cross_pairs, min(args.paires, len(cross_pairs)))]
    ref, cand, t_ref, t_cand, d_ref, d_cand = _mesurer("cross", echantillon, _ref_evaluate_cross_atoms, C.evaluate_cross_atoms, len(cross_pairs))
    ecarts = sum(1 for r, c in zip(ref, cand) if not _meme_decision_cross(r, c))
    print(f"  echantillon        : {len(echantillon)} paires d'atoms ; retenues (auto/review) : {sum(1 for r in ref if r and (r['auto_merge'] or r['review']))}")
    print(f"  descriptions calculees : reference {d_ref} | candidat {d_cand} ({100 * d_cand / max(1, d_ref):.1f} %)")
    print(f"  temps              : reference {t_ref:.1f} s | candidat {t_cand:.1f} s | gain x{t_ref / max(t_cand, 1e-6):.1f}")
    print(f"  projection passe 2 : reference {t_ref / len(echantillon) * len(cross_pairs) / 60:.0f} min | candidat {t_cand / len(echantillon) * len(cross_pairs) / 60:.0f} min")
    print(f"  decisions differentes : {ecarts}")
    ok2 = ecarts == 0

    print("\n" + "=" * 78)
    print("[OK] decisions identiques sur les deux passes" if ok1 and ok2 else "[FAIL] au moins une decision differe : ne pas integrer / revenir a V3.1.2")
    print("=" * 78)
    return 0 if ok1 and ok2 else 1


if __name__ == "__main__":
    raise SystemExit(main())

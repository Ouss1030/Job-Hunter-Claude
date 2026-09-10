from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import pandas as pd
import streamlit as st

from interface.data_access import (
    ROOT,
    collection_history,
    dashboard_metrics,
    decorate_scored_jobs,
    entity_history,
    lifecycle_rows,
    load_latest_final_pool,
    load_latest_queue,
    load_latest_delta,
    query_all_jobs,
    source_metrics,
)
from interface.lifecycle_service import USER_STATUSES, add_note, set_status
from interface.feedback_service import (
    REASONS as FEEDBACK_REASONS,
    VERDICTS as FEEDBACK_VERDICTS,
    VERDICT_LABELS as FEEDBACK_LABELS,
    automatic_score,
    decorate_feedback,
    delete_feedback,
    feedback_rows,
    feedback_summary,
    get_feedback,
    save_feedback,
)
from interface.handoff_service import (
    create_manual_handoff,
    handoff_history,
    latest_handoff,
    load_candidates as load_handoff_candidates,
    open_folder,
)
from interface.pipeline_runner import get_run_state, is_running, latest_ui_log, launch_daily_run
from interface.source_registry_service import registered_sources, update_enabled_sources
# JOBHUNTER_OBSERVABILITY_V1_IMPORT
from interface.run_statistics import (
    pipeline_run_history, latest_main_internal_durations,
    latest_source_runtimes, latest_enrichment_runtimes,
)
from interface.progress_monitor import (
    STEP_ORDER,
    active_step_activity,
    completed_steps,
    format_duration,
    latest_daily_manifest,
    run_elapsed_seconds,
    step_rows,
)


st.set_page_config(
    page_title="JobHunter",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded",
)

STATUS_FR = {
    "NON_SUIVIE": "Non suivie",
    "DISCOVERED": "Découverte",
    "SHORTLISTED": "Présélectionnée",
    "READY": "Prête",
    "DOCUMENTS_READY": "Documents prêts",
    "APPLIED": "✅ Candidature envoyée",
    "INTERVIEW": "🗣️ Entretien",
    "OFFER": "🎉 Offre reçue",
    "REJECTED": "❌ Refus",
    "WITHDRAWN": "Retirée",
    "CLOSED": "Fermée / expirée",
}

STATUS_EMOJI = {
    "NON_SUIVIE": "⚪",
    "DISCOVERED": "🔵",
    "SHORTLISTED": "🟣",
    "READY": "🟢",
    "DOCUMENTS_READY": "📄",
    "APPLIED": "✅",
    "INTERVIEW": "🗣️",
    "OFFER": "🎉",
    "REJECTED": "❌",
    "WITHDRAWN": "↩️",
    "CLOSED": "⚫",
}


def label_status(value: str | None) -> str:
    value = value or "NON_SUIVIE"
    return f"{STATUS_EMOJI.get(value, '•')} {STATUS_FR.get(value, value)}"


def label_feedback(value: str | None) -> str:
    if not value:
        return "⚪ Non évaluée"
    return FEEDBACK_LABELS.get(value, value)


def note_preview(value: str | None, max_len: int = 80) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


# Verdict et pistes, en libellés courts pour tenir dans un tableau.
PICTO_VERDICT = {
    "ACCESSIBLE": "✅ accessible",
    "A_VERIFIER": "⚠️ à vérifier",
    "FERMEE": "⛔ fermée",
    "INCONNU": "· à enrichir",
}

LIBELLE_COURT = {
    "SPECIALITE": "Ma spécialité",
    "ACCESSIBLE_INDUSTRIE": "Industrie",
    "ACCESSIBLE_LARGE": "Hors domaine",
    "HORS_PORTEE": "Hors de portée",
    "INDETERMINE": "À enrichir",
}

# Ordre de lecture : la spécialité d'abord, les offres fermées en dernier.
ORDRE_PISTES = ("SPECIALITE", "ACCESSIBLE_INDUSTRIE", "ACCESSIBLE_LARGE",
                "INDETERMINE", "HORS_PORTEE")


def to_df(items: list[dict], mode: str) -> pd.DataFrame:
    rows = []
    for x in items:
        if mode == "final":
            score = x.get("final_score_v12", x.get("final_score"))
            rank = x.get("pool_rank_v12", x.get("pool_rank"))
            action = x.get("recommended_action_v12", x.get("recommended_action"))
            priority = x.get("priority_v12", x.get("priority"))
        elif mode == "queue":
            score = x.get("queue_score")
            rank = x.get("queue_rank")
            action = x.get("queue_status")
            priority = x.get("gate_status")
        else:
            score = x.get("final_score") or x.get("queue_score") or x.get("match_score")
            rank = x.get("pool_rank") or x.get("queue_rank")
            action = x.get("recommended_action")
            priority = x.get("priority")

        rows.append({
            "ID": x.get("canonical_job_id"),
            "Rang": rank,
            "Score": score,
            # Verdict et piste : lisibles d'un coup d'œil, contestables
            # parce que la barrière est nommée dans la colonne suivante.
            "Verdict": PICTO_VERDICT.get(x.get("verdict", ""), "") ,
            "Piste": LIBELLE_COURT.get(x.get("piste", ""), ""),
            "Obstacle": x.get("barriere") or x.get("alertes") or "",
            "Atouts": x.get("atouts") or "",
            "Formation": x.get("formation_proposee") or "",
            "Mon avis": label_feedback(x.get("feedback_verdict")),
            "Mon score": x.get("user_score"),
            "Écart": x.get("score_gap"),
            "Ma note": note_preview(x.get("feedback_note")),
            "Postulé": x.get("applied", "Non"),
            "Statut": label_status(x.get("application_status")),
            "Poste": x.get("title"),
            "Entreprise": x.get("company"),
            "Lieu": x.get("location"),
            "Source": x.get("source"),
            "Track": x.get("cv_track") or x.get("best_family"),
            "Priorité": priority,
            "Action": action,
            "Date": x.get("date_published"),
            "Lien": x.get("url"),
        })
    return pd.DataFrame(rows)


def table_config():
    return {
        "ID": None,
        "Rang": st.column_config.NumberColumn("#", format="%d", width="small"),
        "Score": st.column_config.NumberColumn("Score JobHunter", format="%.1f", width="small"),
        "Mon avis": st.column_config.TextColumn("Mon avis", width="medium"),
        "Mon score": st.column_config.NumberColumn("Mon score", format="%.0f", width="small"),
        "Écart": st.column_config.NumberColumn("Écart JH-moi", format="%.1f", width="small"),
        "Ma note": st.column_config.TextColumn("Ma note", width="large"),
        "Postulé": st.column_config.TextColumn("Postulé", width="small"),
        "Statut": st.column_config.TextColumn("Statut", width="medium"),
        "Poste": st.column_config.TextColumn("Poste", width="large"),
        "Entreprise": st.column_config.TextColumn("Entreprise", width="medium"),
        "Lieu": st.column_config.TextColumn("Lieu", width="medium"),
        "Source": st.column_config.TextColumn("Source", width="small"),
        "Track": st.column_config.TextColumn("Profil CV", width="small"),
        "Verdict": st.column_config.TextColumn("Verdict", width="small"),
        "Piste": st.column_config.TextColumn("Piste", width="small"),
        "Obstacle": st.column_config.TextColumn("Obstacle / alerte", width="medium"),
        "Atouts": st.column_config.TextColumn("Vos atouts", width="medium"),
        "Formation": st.column_config.TextColumn("Formation ?", width="small"),
        "Priorité": st.column_config.TextColumn("Priorité", width="small"),
        "Action": st.column_config.TextColumn("Action", width="medium"),
        "Date": st.column_config.TextColumn("Publication", width="small"),
        "Lien": st.column_config.LinkColumn("Ouvrir l'offre", display_text="🔗 Ouvrir", width="small"),
    }


def filtered(
    items: list[dict],
    search: str,
    sources: list[str],
    statuses: list[str],
    min_score: float | None = None,
    feedback_verdicts: list[str] | None = None,
    contested_only: bool = False,
    pistes: list[str] | None = None,
    masquer_fermees: bool = False,
):
    search_l = search.strip().lower()
    pistes = pistes or []
    out = []
    feedback_verdicts = feedback_verdicts or []
    for x in items:
        if search_l:
            hay = " ".join(str(x.get(k) or "") for k in ("title", "company", "location")).lower()
            if search_l not in hay:
                continue
        if sources and (x.get("source") or "") not in sources:
            continue
        if statuses and (x.get("application_status") or "NON_SUIVIE") not in statuses:
            continue
        score = x.get("display_score")
        if min_score is not None and score is not None and float(score) < min_score:
            continue
        verdict = x.get("feedback_verdict") or "UNRATED"
        if feedback_verdicts and verdict not in feedback_verdicts:
            continue
        if contested_only:
            gap = x.get("score_gap")
            if gap is None or abs(float(gap)) < 15:
                continue
        # Filtre par piste : consulter sa specialite sans la noyer sous les
        # offres simplement accessibles.
        if pistes and (x.get("piste") or "") not in pistes:
            continue
        # Masquer les offres fermees : elles restent consultables, mais on
        # ne les impose pas dans la vue par defaut.
        if masquer_fermees and x.get("verdict") == "FERMEE":
            continue
        out.append(x)
    return out


def detail_panel(job: dict, key_prefix: str):
    st.divider()
    st.subheader(job.get("title") or "Offre")
    c1, c2, c3, c4 = st.columns([2, 2, 1, 1])
    c1.write(f"**Entreprise :** {job.get('company') or '—'}")
    c2.write(f"**Lieu :** {job.get('location') or '—'}")
    c3.write(f"**Source :** {job.get('source') or '—'}")
    c4.write(f"**Statut :** {label_status(job.get('application_status'))}")

    score_cols = st.columns(4)
    score_cols[0].metric("Match", job.get("match_score") if job.get("match_score") is not None else "—")
    score_cols[1].metric("Queue", job.get("queue_score") if job.get("queue_score") is not None else "—")
    score_cols[2].metric("Final", job.get("final_score_v12", job.get("final_score")) if (job.get("final_score_v12") is not None or job.get("final_score") is not None) else "—")
    score_cols[3].metric("Priorité", job.get("priority_v12", job.get("priority")) or "—")

    if job.get("url"):
        st.link_button("🔗 Ouvrir l'annonce originale", job["url"], type="primary")

    current = job.get("application_status") or "NON_SUIVIE"
    already_applied = str(job.get("applied") or "").lower() == "oui" or current in {
        "APPLIED", "INTERVIEW", "OFFER", "REJECTED"
    }

    # Personal feedback is deliberately separate from JobHunter's automatic score.
    job = decorate_feedback([job])[0]
    fb = get_feedback(job)
    auto_score = automatic_score(job)

    st.markdown("#### 📝 Mon évaluation de cette offre")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Score JobHunter", f"{auto_score:.1f}" if auto_score is not None else "—")
    m2.metric("Mon score", f"{float(fb['user_score']):.0f}" if fb and fb.get("user_score") is not None else "—")
    gap = None
    if auto_score is not None and fb and fb.get("user_score") is not None:
        gap = round(auto_score - float(fb["user_score"]), 1)
    m3.metric("Écart JH - moi", f"{gap:+.1f}" if gap is not None else "—")
    m4.metric("Mon avis", label_feedback(fb.get("verdict") if fb else None))

    q1, q2, q3 = st.columns(3)
    if q1.button("👍 Correspond", key=f"{key_prefix}_fb_quick_match", width="stretch"):
        current_fb = get_feedback(job) or {}
        save_feedback(
            job,
            "MATCH",
            current_fb.get("user_score"),
            current_fb.get("note") or "",
            current_fb.get("reasons") or [],
        )
        st.toast("Avis enregistré : correspond.")
        st.rerun()
    if q2.button("🤔 À revoir", key=f"{key_prefix}_fb_quick_review", width="stretch"):
        current_fb = get_feedback(job) or {}
        save_feedback(
            job,
            "REVIEW",
            current_fb.get("user_score"),
            current_fb.get("note") or "",
            current_fb.get("reasons") or [],
        )
        st.toast("Avis enregistré : à revoir.")
        st.rerun()
    if q3.button("👎 Ne correspond pas", key=f"{key_prefix}_fb_quick_no", width="stretch"):
        current_fb = get_feedback(job) or {}
        save_feedback(
            job,
            "NO_MATCH",
            current_fb.get("user_score"),
            current_fb.get("note") or "",
            current_fb.get("reasons") or [],
        )
        st.toast("Avis enregistré : ne correspond pas.")
        st.rerun()

    current_fb = get_feedback(job) or {}
    current_verdict = current_fb.get("verdict") if current_fb.get("verdict") in FEEDBACK_VERDICTS else "REVIEW"
    current_score = current_fb.get("user_score")
    current_reasons = [r for r in (current_fb.get("reasons") or []) if r in FEEDBACK_REASONS]

    with st.form(f"{key_prefix}_feedback_form", clear_on_submit=False):
        fba, fbb = st.columns([2, 2])
        verdict = fba.selectbox(
            "Mon avis",
            FEEDBACK_VERDICTS,
            index=FEEDBACK_VERDICTS.index(current_verdict),
            format_func=lambda v: FEEDBACK_LABELS[v],
            key=f"{key_prefix}_feedback_verdict",
        )
        use_score = fbb.toggle(
            "Définir mon propre score",
            value=current_score is not None,
            key=f"{key_prefix}_feedback_use_score",
        )
        personal_score = st.slider(
            "Mon score personnel (0–100)",
            0,
            100,
            int(round(float(current_score))) if current_score is not None else int(round(auto_score or 50)),
            disabled=not use_score,
            key=f"{key_prefix}_feedback_score",
            help="Ce score ne remplace jamais le score JobHunter. Il sert à mesurer ton désaccord.",
        )
        reasons = st.multiselect(
            "Pourquoi ?",
            FEEDBACK_REASONS,
            default=current_reasons,
            key=f"{key_prefix}_feedback_reasons",
        )
        personal_note = st.text_area(
            "Ma note personnelle",
            value=current_fb.get("note") or "",
            placeholder="Ex. JobHunter donne 95/100 mais le néerlandais C1 est obligatoire et le poste est trop senior.",
            height=110,
            key=f"{key_prefix}_feedback_note",
        )
        submitted = st.form_submit_button("💾 Enregistrer mon évaluation", type="primary")
        if submitted:
            save_feedback(
                job,
                verdict,
                float(personal_score) if use_score else None,
                personal_note,
                reasons,
            )
            st.success("Évaluation enregistrée durablement.")
            st.rerun()

    if current_fb:
        d1, d2 = st.columns([1, 4])
        if d1.button("🗑️ Effacer", key=f"{key_prefix}_feedback_delete"):
            delete_feedback(job)
            st.toast("Évaluation supprimée.")
            st.rerun()
        d2.caption(
            f"Dernière modification : {str(current_fb.get('updated_at') or '—').replace('T', ' ')} · "
            "Stockage séparé : database/user_feedback.db"
        )

    st.caption(
        "Ton avis n'altère jamais automatiquement le Matcher, le Gate ou le score JobHunter. "
        "Il constitue un historique personnel exploitable plus tard pour améliorer l'algorithme."
    )

    st.markdown("#### Actions rapides")
    qa1, qa2, qa3, qa4 = st.columns([1.4, 1.2, 1.0, 3.4])
    if already_applied:
        qa1.button("✅ Déjà postulé", disabled=True, key=f"{key_prefix}_already_applied")
    elif qa1.button("✅ J'ai postulé", type="primary", key=f"{key_prefix}_quick_applied"):
        try:
            set_status(job, "APPLIED", "Candidature marquée comme envoyée depuis JobHunter UI.")
            st.success("Candidature marquée comme envoyée.")
            st.rerun()
        except Exception as exc:
            st.error(f"Impossible d'enregistrer la candidature : {exc}")

    if qa2.button("🗣️ Entretien", disabled=not already_applied, key=f"{key_prefix}_quick_interview"):
        try:
            set_status(job, "INTERVIEW", "Entretien enregistré depuis JobHunter UI.")
            st.rerun()
        except Exception as exc:
            st.error(f"Impossible d'enregistrer l'entretien : {exc}")

    if qa3.button("❌ Refus", disabled=not already_applied, key=f"{key_prefix}_quick_rejected"):
        try:
            set_status(job, "REJECTED", "Refus enregistré depuis JobHunter UI.")
            st.rerun()
        except Exception as exc:
            st.error(f"Impossible d'enregistrer le refus : {exc}")

    qa4.caption("Ces boutons écrivent dans le Lifecycle existant de JobHunter. Rien n'est marqué APPLIED automatiquement.")

    with st.expander("Description de l'offre", expanded=False):
        st.write(job.get("description") or "Description non disponible dans cet artefact.")

    st.markdown("#### Suivi de candidature")
    options = USER_STATUSES
    default_index = options.index(current) if current in options else 0
    col_status, col_note, col_action = st.columns([2, 4, 1])
    selected_status = col_status.selectbox(
        "Nouveau statut",
        options,
        index=default_index,
        format_func=lambda s: label_status(s),
        key=f"{key_prefix}_status",
    )
    note = col_note.text_input(
        "Note facultative",
        placeholder="Ex. candidature envoyée via le site de l'entreprise",
        key=f"{key_prefix}_status_note",
    )
    if col_action.button("Enregistrer", type="primary", key=f"{key_prefix}_save_status"):
        try:
            set_status(job, selected_status, note)
            st.success(f"Statut enregistré : {label_status(selected_status)}")
            st.rerun()
        except Exception as exc:
            st.error(f"Impossible d'enregistrer le statut : {exc}")

    note_only = st.text_input(
        "Ajouter une note sans changer le statut",
        key=f"{key_prefix}_note_only",
    )
    if st.button("Ajouter la note", key=f"{key_prefix}_add_note"):
        try:
            add_note(job, note_only)
            st.success("Note ajoutée.")
        except Exception as exc:
            st.error(f"Impossible d'ajouter la note : {exc}")


def scored_tab(items: list[dict], mode: str, key_prefix: str):
    if not items:
        st.info("Aucune donnée disponible pour cette vue.")
        return

    items = decorate_feedback(items)
    source_values = sorted({x.get("source") for x in items if x.get("source")})
    status_values = ["NON_SUIVIE"] + USER_STATUSES
    f1, f2, f3, f4 = st.columns([3, 2, 2, 2])
    search = f1.text_input("Recherche", placeholder="poste, entreprise, lieu…", key=f"{key_prefix}_search")
    sources = f2.multiselect("Sources", source_values, key=f"{key_prefix}_sources")
    statuses = f3.multiselect(
        "Statuts",
        status_values,
        format_func=lambda s: STATUS_FR.get(s, s),
        key=f"{key_prefix}_statuses",
    )

    scores = [float(x["display_score"]) for x in items if x.get("display_score") is not None]
    min_score = None
    if scores:
        floor = int(min(scores))
        ceil = int(max(scores))
        min_score = f4.slider("Score minimum", floor, ceil, floor, key=f"{key_prefix}_minscore")

    g1, g2, g3 = st.columns([2, 2, 4])
    feedback_filter = g1.multiselect(
        "Mon avis",
        ["UNRATED"] + FEEDBACK_VERDICTS,
        format_func=lambda v: "⚪ Non évaluée" if v == "UNRATED" else FEEDBACK_LABELS[v],
        key=f"{key_prefix}_feedback_filter",
    )
    contested_only = g2.toggle(
        "Scores contestés",
        value=False,
        key=f"{key_prefix}_contested_only",
        help="Affiche les offres où l'écart entre le score JobHunter et ton score est d'au moins 15 points.",
    )
    g3.caption(
        "Clique sur une ligne pour noter l'offre. Tes évaluations restent disponibles après les prochains runs."
    )

    # Filtre par piste : consulter sa spécialité sans la noyer sous les
    # offres simplement accessibles. Le comptage par piste est affiché dans
    # le libellé, pour savoir ce qu'on gagne avant de cocher.
    compte = {}
    for x in items:
        cle = x.get("piste") or ""
        compte[cle] = compte.get(cle, 0) + 1

    h1, h2 = st.columns([4, 2])
    pistes = h1.multiselect(
        "Piste",
        [p for p in ORDRE_PISTES if compte.get(p)],
        format_func=lambda p: f"{LIBELLE_COURT.get(p, p)} ({compte.get(p, 0)})",
        key=f"{key_prefix}_pistes",
        help="Ma spécialité : QC, laboratoire, chimie, data. "
             "Industrie : production et procédés, accessibles avec votre "
             "bagage. Hors domaine : rien ne vous bloque, mais le métier "
             "est éloigné de votre profil.",
    )
    masquer_fermees = h2.toggle(
        "Masquer les offres fermées",
        value=False,
        key=f"{key_prefix}_masquer_fermees",
        help="Une offre est fermée quand une barrière est identifiée : "
             "diplôme supérieur, langue hors de portée, expérience trop "
             "longue. La colonne « Obstacle » en donne toujours la raison.",
    )

    shown = filtered(
        items,
        search,
        sources,
        statuses,
        min_score,
        feedback_filter,
        contested_only,
        pistes,
        masquer_fermees,
    )
    st.caption(f"{len(shown)} offre(s) affichée(s) sur {len(items)}")
    df = to_df(shown, mode)
    if df.empty:
        st.warning("Aucune offre ne correspond aux filtres.")
        return

    # UI_FILTER_SELECTION_FIX_V1
    # Streamlit peut conserver un index de selection provenant de l'ancien tableau
    # apres un changement de statut/filtre. La cle du widget est donc liee au
    # contenu reel affiche et l'index reste borne avant tout acces a shown[idx].
    selection_basis = "\x1f".join(
        f"{x.get('stable_item_key') or x.get('entity_id') or x.get('canonical_job_id') or x.get('url') or i}|"
        f"{x.get('application_status') or 'NON_SUIVIE'}"
        for i, x in enumerate(shown)
    )
    selection_sig = hashlib.sha1(
        selection_basis.encode("utf-8", errors="ignore")
    ).hexdigest()[:12]

    event = st.dataframe(
        df,
        width="stretch",
        height=520,
        hide_index=True,
        column_config=table_config(),
        on_select="rerun",
        selection_mode="single-row",
        key=f"{key_prefix}_table_{selection_sig}",
    )

    if event.selection.rows:
        idx = int(event.selection.rows[0])
        if 0 <= idx < len(shown):
            selected_job = shown[idx]
            selected_identity = (
                selected_job.get("stable_item_key")
                or selected_job.get("entity_id")
                or selected_job.get("canonical_job_id")
                or selected_job.get("url")
                or idx
            )
            selected_sig = hashlib.sha1(
                str(selected_identity).encode("utf-8", errors="ignore")
            ).hexdigest()[:10]
            detail_panel(
                selected_job,
                f"{key_prefix}_{selection_sig}_{selected_sig}",
            )
        else:
            st.caption(
                "La selection precedente n'est plus valide apres le changement de statut ou de filtre. "
                "Selectionne simplement une ligne a nouveau."
            )
    else:
        st.caption("Clique sur une ligne pour ouvrir sa fiche, la noter et gérer son Lifecycle.")


@st.fragment(run_every="2s")
def pipeline_live_panel():
    running = is_running()
    state = get_run_state()
    manifest_path, manifest = latest_daily_manifest()

    run_cols = st.columns([1, 3])
    if running:
        run_cols[0].button("⏳ Run production en cours", disabled=True, width="stretch")
        run_cols[1].info(
            "Le Daily Run travaille en arrière-plan. Cette zone se met à jour automatiquement toutes les 2 secondes."
        )
    else:
        if run_cols[0].button("▶ Lancer JobHunter (production)", type="primary", width="stretch"):
            try:
                log_path = launch_daily_run()
                st.success(f"Daily Run lancé. Journal : {log_path.name}")
                st.rerun(scope="fragment")
            except Exception as exc:
                st.error(f"Impossible de lancer le pipeline : {exc}")
        run_cols[1].write(
            "Le bouton utilise le Production Runner certifié : préflight, backup DB, pipeline complet, Handoff et rollback automatique en cas d’échec critique."
        )

    if state:
        status = state.get("status", "—")
        rc = state.get("returncode")
        started = state.get("started_at") or "—"
        finished = state.get("finished_at") or "—"

        if status == "FAILED":
            st.error(f"Dernier lancement UI : FAILED — code {rc}. {state.get('error') or ''}")
        elif status == "COMPLETED":
            st.success(f"Dernier lancement UI : COMPLETED — code {rc}.")
        elif status in {"STARTING", "RUNNING"}:
            st.info(f"État du lancement UI : {status} — démarré à {started}.")

        with st.expander("Diagnostic du lancement"):
            st.write({
                "statut": status,
                "début": started,
                "fin": finished,
                "PID worker": state.get("worker_pid"),
                "code de sortie": rc,
                "erreur": state.get("error"),
            })

    if manifest:
        done = completed_steps(manifest)
        total = len(STEP_ORDER)
        elapsed = format_duration(run_elapsed_seconds(manifest, state))
        current = active_step_activity(manifest)

        m1, m2, m3 = st.columns(3)
        m1.metric("Étapes terminées", f"{done}/{total}")
        m2.metric("Temps écoulé", elapsed)
        m3.metric("Run", manifest.get("status") or "—")

        if current:
            st.markdown(f"#### 🔄 {current.get('step_label') or current.get('step')}")

            # JOBHUNTER_OBSERVABILITY_V1_PROGRESS_START
            mcur = current.get("main_stage_current")
            mtot = current.get("main_stage_total")
            if mcur is not None and mtot:
                ratio = max(0.0, min(1.0, mcur / mtot))
                st.progress(ratio, text=f"MAIN {mcur}/{mtot} — {current.get('main_stage_label') or current.get('step_label')}")

            scur = current.get("source_index")
            stot = current.get("source_total")
            if current.get("source"):
                if scur is not None and stot:
                    sratio = max(0.0, min(1.0, scur / stot))
                    st.progress(sratio, text=f"Source {scur}/{stot} — {current['source']}")
                else:
                    st.write(f"**Source active :** {current['source']}")

            icur = current.get("item_current")
            itot = current.get("item_total")
            if icur is not None and itot:
                iratio = max(0.0, min(1.0, icur / itot))
                kind = current.get("activity_kind") or "Progression"
                suffix = current.get("item_label") or ""
                st.progress(iratio, text=f"{kind} : {icur}/{itot} ({iratio*100:.0f} %) — {suffix}")
            # JOBHUNTER_OBSERVABILITY_V1_PROGRESS_END

            age = current.get("log_age_seconds")
            if age is not None:
                if age < 15:
                    st.caption(f"🟢 Activité détectée — journal mis à jour il y a {age} s")
                elif age < 180:
                    st.caption(f"🟡 Dernière sortie il y a {age} s — une requête réseau peut être en cours")
                else:
                    st.warning(
                        f"Aucune nouvelle ligne dans le journal depuis {age // 60} min. "
                        "Le processus peut être sur une requête lente ; le PID et le manifest restent les sources de vérité."
                    )

            tail = current.get("tail_lines") or []
            if tail:
                with st.expander("Activité en direct", expanded=True):
                    st.code("\n".join(tail), language=None)

        st.dataframe(
            pd.DataFrame(step_rows(manifest)),
            width="stretch",
            hide_index=True,
            height=315,
        )

        if manifest_path:
            st.caption(f"Manifest suivi : {manifest_path.name}")
    elif running:
        st.info("Initialisation du manifest Daily Run…")

    log = latest_ui_log()
    if log and log.exists():
        with st.expander("Journal UI complet"):
            text = log.read_text(encoding="utf-8", errors="replace")
            st.code(text[-12000:], language=None)



def guide_page():
    st.subheader("🧭 Comprendre JobHunter")
    st.caption("Cette page explique le rôle de chaque couche. Streamlit est le cockpit ; le moteur reste le pipeline Python certifié.")

    st.markdown("""
### Vue d’ensemble

**Streamlit → Production Runner → Pipeline → Résultats → Lifecycle**

| Étape | Rôle | Ce que tu dois retenir |
|---|---|---|
| **MAIN** | Collecte les sources, déduplique et score | C’est la partie la plus longue |
| **Preparation** | Sélectionne le lot à vérifier | Aucun document n’est envoyé |
| **Refresh** | Relit les annonces en LIVE | Écarte les offres fermées ou douteuses |
| **Recheck** | Réévalue après Refresh | Applique les blocages réels |
| **Final Pool** | Liste finale fiable | C’est la meilleure liste pour décider |
| **Delta** | Compare au run précédent | NEW / UPDATED / REPOSTED / DISAPPEARED |
| **Lifecycle** | Suit tes candidatures dans le temps | APPLIED reste uniquement une action utilisateur |
| **Handoff** | Prépare les ZIP ChatGPT | Automatique en production + sous-lots manuels possibles |
""")

    st.info(
        "Le fichier RUN_JOBHUNTER_PRODUCTION_V1.bat reste une solution de secours. "
        "Le bouton du Dashboard appelle maintenant le même runner de production sécurisé."
    )

    st.markdown("### Comment lire les écrans")
    st.markdown("""
- **✅ Final Pool** : offres revérifiées et classées juste avant candidature.
- **🆕 Delta / Nouveautés** : ce qui a changé depuis le run précédent.
- **🎯 Queue qualifiée** : liste plus large avant les vérifications finales.
- **💼 Toutes les offres** : catalogue canonique complet du dernier build.
- **📨 Mes candidatures** : suivi Lifecycle (READY, APPLIED, INTERVIEW, etc.).
- **📦 Handoff ChatGPT** : création manuelle de sous-lots à envoyer à ChatGPT.
- **📡 Sources** : activation/désactivation et santé historique des collecteurs.
- **🕒 Historique** : historique brut des collectes.
""")


def delta_page():
    payload, path = load_latest_delta()
    if not payload:
        st.info("Aucun Delta disponible. Lance d’abord un run production.")
        return

    summary = payload.get("summary") or {}
    records = payload.get("records") or []

    if path:
        st.caption(f"Artefact : {path.name}")

    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("NEW", summary.get("NEW", 0))
    m2.metric("UPDATED", summary.get("UPDATED", 0))
    m3.metric("REPOSTED", summary.get("REPOSTED", 0))
    m4.metric("REACTIVATED", summary.get("REACTIVATED", 0))
    m5.metric("DISAPPEARED", summary.get("DISAPPEARED", 0))
    m6.metric("Pool actuel", summary.get("current_total", 0))

    st.caption(
        "DISAPPEARED signifie uniquement « absent du Final Pool actuel » ; ce n’est pas automatiquement la preuve que l’annonce a été supprimée."
    )

    statuses_available = [
        s for s in ["NEW", "UPDATED", "REPOSTED", "REACTIVATED", "DISAPPEARED", "UNCHANGED"]
        if any(str(r.get("delta_status")) == s for r in records)
    ]
    default_statuses = [s for s in statuses_available if s != "UNCHANGED"]

    f1, f2, f3 = st.columns([2.2, 2.2, 3.6])
    statuses = f1.multiselect("Changements", statuses_available, default=default_statuses, key="delta_statuses")
    actions_available = sorted({str(r.get("recommended_action")) for r in records if r.get("recommended_action")})
    actions = f2.multiselect("Actions", actions_available, key="delta_actions")
    search = f3.text_input("Recherche", placeholder="poste, entreprise, lieu…", key="delta_search")
    search_l = search.strip().lower()

    shown = []
    for row in records:
        if statuses and str(row.get("delta_status")) not in statuses:
            continue
        if actions and str(row.get("recommended_action")) not in actions:
            continue
        if search_l:
            hay = " ".join(str(row.get(k) or "") for k in ("title", "company", "location", "source")).lower()
            if search_l not in hay:
                continue
        shown.append(row)

    st.caption(f"{len(shown)} changement(s) affiché(s) sur {len(records)} enregistrement(s).")

    if not shown:
        st.info("Aucun élément pour ces filtres.")
        return

    df = pd.DataFrame([
        {
            "Statut": r.get("delta_status"),
            "Rang": r.get("pool_rank_current"),
            "Score": r.get("final_score_current"),
            "Action": r.get("recommended_action"),
            "Poste": r.get("title"),
            "Entreprise": r.get("company"),
            "Lieu": r.get("location"),
            "Source": r.get("source"),
            "Lien": r.get("url"),
        }
        for r in shown
    ])

    event = st.dataframe(
        df,
        width="stretch",
        height=520,
        hide_index=True,
        column_config={
            "Rang": st.column_config.NumberColumn("#", format="%d", width="small"),
            "Score": st.column_config.NumberColumn("Score", format="%.1f", width="small"),
            "Poste": st.column_config.TextColumn("Poste", width="large"),
            "Entreprise": st.column_config.TextColumn("Entreprise", width="medium"),
            "Lien": st.column_config.LinkColumn("Offre", display_text="🔗 Ouvrir", width="small"),
        },
        on_select="rerun",
        selection_mode="single-row",
        key="delta_table",
    )

    if event.selection.rows:
        row = shown[event.selection.rows[0]]
        st.divider()
        st.subheader(row.get("title") or "Changement")
        st.write(f"**{row.get('company') or '—'}** — {row.get('location') or '—'}")
        st.write(f"**Delta :** {row.get('delta_status')} — **Action :** {row.get('recommended_action') or '—'}")
        if row.get("action_transition"):
            st.write(f"**Transition :** {row.get('action_transition')}")
        changes = (row.get("content_changes") or []) + (row.get("decision_changes") or [])
        if changes:
            st.markdown("#### Changements détectés")
            for change in changes:
                st.write(f"- {change}")
        if row.get("url"):
            st.link_button("🔗 Ouvrir l’annonce", row["url"], type="primary")


def dashboard_page():
    metrics = dashboard_metrics()
    latest = metrics["latest_collection"] or {}

    cols = st.columns(5)
    cols[0].metric("Offres actuelles", metrics["canonical_count"])
    cols[1].metric("Qualifiées", metrics["queue_count"])
    cols[2].metric("Prioritaires", metrics["pool_count"])
    cols[3].metric("Candidatures envoyées", metrics["status_counts"].get("APPLIED", 0))
    cols[4].metric("Entretiens", metrics["status_counts"].get("INTERVIEW", 0))

    feedback_stats = feedback_summary()
    st.markdown("### 📝 Mes évaluations")
    fbc1, fbc2, fbc3, fbc4, fbc5 = st.columns(5)
    fbc1.metric("Évaluées", feedback_stats["total"])
    fbc2.metric("👍 Correspond", feedback_stats["match"])
    fbc3.metric("🤔 À revoir", feedback_stats["review"])
    fbc4.metric("👎 Non", feedback_stats["no_match"])
    fbc5.metric("⚠️ Scores contestés", feedback_stats["contested"])

    st.markdown("### Lancer JobHunter")

    pipeline_live_panel()

    # JOBHUNTER_OBSERVABILITY_V1_STATS_START
    run_history = pipeline_run_history(limit=20)
    if run_history:
        last_run = run_history[0]
        st.markdown("### Statistiques du dernier run")
        s1, s2, s3, s4, s5, s6 = st.columns(6)
        s1.metric("Durée totale", format_duration(last_run.get("duration_seconds")))
        s2.metric("Nouvelles (pool)", last_run.get("new", 0))
        s3.metric("Mises à jour", last_run.get("updated", 0))
        s4.metric("Disparues", last_run.get("disappeared", 0))
        s5.metric("Final Pool", last_run.get("final_pool", 0))
        s6.metric("APPLY NOW", last_run.get("apply_now", 0))

        internal = latest_main_internal_durations()
        if internal:
            total_main = sum(int(x.get("duration_seconds") or 0) for x in internal) or 1
            stage_df = pd.DataFrame([{
                "Étape": x.get("label"),
                "Durée": format_duration(x.get("duration_seconds")),
                "% du MAIN": round(100 * int(x.get("duration_seconds") or 0) / total_main, 1),
            } for x in internal])
            with st.expander("⏱️ Durée par phase", expanded=True):
                st.dataframe(stage_df, width="stretch", hide_index=True)

        source_runtime = latest_source_runtimes()
        enrichment_runtime = latest_enrichment_runtimes()
        if source_runtime:
            with st.expander("🐢 Sources de collecte les plus lentes", expanded=False):
                st.dataframe(pd.DataFrame(source_runtime[:20]), width="stretch", hide_index=True)
        if enrichment_runtime:
            with st.expander("🐢 Enrichissements les plus lents", expanded=True):
                st.dataframe(pd.DataFrame(enrichment_runtime[:20]), width="stretch", hide_index=True)
        if not source_runtime or not enrichment_runtime:
            st.caption("Les durées détaillées par source seront disponibles après le prochain run avec Observability V1.")

        hist_df = pd.DataFrame([{
            "Run": x.get("run_id"),
            "Durée": format_duration(x.get("duration_seconds")),
            "Pool": x.get("final_pool", 0),
            "Nouvelles": x.get("new", 0),
            "MAJ": x.get("updated", 0),
            "Disparues": x.get("disappeared", 0),
            "Statut": x.get("status"),
        } for x in run_history[:10]])
        with st.expander("📈 Historique des 10 derniers runs", expanded=False):
            st.dataframe(hist_df, width="stretch", hide_index=True)
    # JOBHUNTER_OBSERVABILITY_V1_STATS_END

    st.caption("Le run production crée le Handoff complet automatiquement. La page 📦 Handoff ChatGPT reste utile pour créer manuellement un sous-lot personnalisé.")
    last_handoff = latest_handoff()
    if last_handoff:
        h1, h2, h3 = st.columns([2, 1, 2])
        h1.write(f"**Dernier handoff :** {str(last_handoff.get('generated_at') or '—').replace('T', ' ')}")
        h2.write(f"**Chunks :** {len(last_handoff.get('chunk_zips') or [])}")
        if h3.button("📂 Ouvrir les handoffs", key="dashboard_open_handoffs"):
            try:
                open_folder(Path(last_handoff["folder"]).parent)
                st.toast("Explorateur Windows ouvert.")
            except Exception as exc:
                st.error(f"Impossible d'ouvrir le dossier : {exc}")

    st.markdown("### Dernière collecte")
    if latest:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.write(f"**Début**\n\n{latest.get('started_at','—')}")
        c2.write(f"**Statut**\n\n{latest.get('status','—')}")
        c3.write(f"**Collectées**\n\n{latest.get('total_collected',0)}")
        c4.write(f"**Nouvelles**\n\n{latest.get('inserted_count',0)}")
        c5.write(f"**Erreurs**\n\n{latest.get('error_count',0)}")


def all_jobs_page():
    st.caption("Catalogue canonique complet du dernier build. Ce n’est pas une liste de candidatures : utilise Final Pool pour décider quoi envoyer.")
    st.caption("Vue du dernier build canonique. La requête est paginée côté SQLite pour rester légère sur 8 Go de RAM.")
    sources_available = [x["source"] for x in source_metrics()]
    f1, f2, f3, f4 = st.columns([3, 2, 1, 1])
    search = f1.text_input("Recherche globale", placeholder="HPLC, data analyst, GSK…", key="all_search")
    sources = f2.multiselect("Sources", sources_available, key="all_sources")
    active_only = f3.toggle("Actives uniquement", value=True, key="all_active")
    page_size = f4.selectbox("Par page", [50, 100, 200], index=1, key="all_pagesize")

    # On calcule d'abord le total avec la page demandée, puis on corrige si nécessaire.
    page = int(st.session_state.get("all_page", 1))
    items, total, build_id = query_all_jobs(
        text=search,
        sources=sources,
        active_only=active_only,
        page=page,
        page_size=page_size,
    )
    pages = max(1, math.ceil(total / page_size))
    if page > pages:
        page = pages
        st.session_state["all_page"] = page
        items, total, build_id = query_all_jobs(
            text=search, sources=sources, active_only=active_only, page=page, page_size=page_size
        )

    p1, p2, p3 = st.columns([1, 2, 1])
    if p1.button("← Précédent", disabled=page <= 1, key="all_prev"):
        st.session_state["all_page"] = page - 1
        st.rerun()
    p2.markdown(f"<div style='text-align:center'>Page <b>{page}</b> / {pages} — {total} offre(s)</div>", unsafe_allow_html=True)
    if p3.button("Suivant →", disabled=page >= pages, key="all_next"):
        st.session_state["all_page"] = page + 1
        st.rerun()

    st.caption(f"Build : {build_id or '—'}")
    items = decorate_feedback(items)
    df = to_df(items, "all")
    if df.empty:
        st.warning("Aucune offre dans cette vue.")
        return

    event = st.dataframe(
        df,
        width="stretch",
        height=560,
        hide_index=True,
        column_config=table_config(),
        on_select="rerun",
        selection_mode="single-row",
        key="all_jobs_table",
    )
    if event.selection.rows:
        idx = event.selection.rows[0]
        detail_panel(items[idx], f"all_{items[idx].get('canonical_job_id', idx)}")



def feedback_page():
    st.caption(
        "Tes évaluations personnelles sont persistantes et séparées de jobs.db. "
        "Elles n'altèrent jamais automatiquement le score JobHunter."
    )
    rows = feedback_rows()
    stats = feedback_summary()

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Évaluées", stats["total"])
    c2.metric("👍 Correspond", stats["match"])
    c3.metric("🤔 À revoir", stats["review"])
    c4.metric("👎 Ne correspond pas", stats["no_match"])
    c5.metric("⚠️ Scores contestés", stats["contested"])

    if not rows:
        st.info("Aucune offre évaluée pour l'instant. Ouvre une offre dans Final Pool, Queue ou Toutes les offres.")
        return

    f1, f2, f3 = st.columns([3, 2, 2])
    search = f1.text_input("Recherche dans mes évaluations", placeholder="poste, entreprise, note…", key="feedback_search")
    verdicts = f2.multiselect(
        "Avis",
        FEEDBACK_VERDICTS,
        format_func=lambda v: FEEDBACK_LABELS[v],
        key="feedback_verdict_filter",
    )
    contested = f3.toggle(
        "Scores contestés uniquement",
        value=False,
        key="feedback_contested_filter",
        help="Écart absolu ≥ 15 points entre JobHunter et ton score.",
    )

    search_l = search.strip().lower()
    shown = []
    for row in rows:
        if search_l:
            hay = " ".join(
                str(row.get(k) or "")
                for k in ("title", "company", "note", "source")
            ).lower()
            if search_l not in hay:
                continue
        if verdicts and row.get("verdict") not in verdicts:
            continue
        if contested:
            gap = row.get("score_gap")
            if gap is None or abs(float(gap)) < 15:
                continue
        shown.append(row)

    st.caption(f"{len(shown)} évaluation(s) affichée(s) sur {len(rows)}")

    df = pd.DataFrame([
        {
            "Avis": label_feedback(r.get("verdict")),
            "Score JH": r.get("auto_score_at_rating"),
            "Mon score": r.get("user_score"),
            "Écart": r.get("score_gap"),
            "Poste": r.get("title"),
            "Entreprise": r.get("company"),
            "Source": r.get("source"),
            "Motifs": ", ".join(r.get("reasons") or []),
            "Note": r.get("note"),
            "Modifié": str(r.get("updated_at") or "").replace("T", " "),
            "Lien": r.get("url"),
        }
        for r in shown
    ])

    st.dataframe(
        df,
        width="stretch",
        height=560,
        hide_index=True,
        column_config={
            "Score JH": st.column_config.NumberColumn("Score JH", format="%.1f"),
            "Mon score": st.column_config.NumberColumn("Mon score", format="%.0f"),
            "Écart": st.column_config.NumberColumn("Écart JH-moi", format="%.1f"),
            "Lien": st.column_config.LinkColumn("Offre", display_text="🔗 Ouvrir"),
        },
    )

    csv_bytes = df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "⬇️ Exporter mes évaluations en CSV",
        data=csv_bytes,
        file_name="jobhunter_mes_evaluations.csv",
        mime="text/csv",
        key="feedback_export_csv",
    )

    with st.expander("Comment utiliser ces retours pour améliorer JobHunter ?", expanded=False):
        st.write(
            "Quand tu auras accumulé suffisamment d'évaluations, on pourra comparer systématiquement "
            "Score JobHunter ↔ Mon score ↔ motifs. On pourra alors détecter les règles qui surévaluent "
            "ou sous-évaluent certaines offres, sans jamais apprendre automatiquement sur une seule note."
        )


def applications_page():
    st.caption("Lifecycle : ici tu suis les candidatures dans le temps. Le statut APPLIED n’est créé que par une action utilisateur.")
    f1, f2 = st.columns([2, 4])
    status = f1.selectbox(
        "Filtrer par statut",
        ["TOUS"] + USER_STATUSES,
        format_func=lambda s: "Tous" if s == "TOUS" else label_status(s),
    )
    rows = lifecycle_rows(status)
    f2.caption(f"{len(rows)} candidature(s) suivie(s) dans le Lifecycle")
    if not rows:
        st.info("Aucune candidature dans ce statut.")
        return

    df = pd.DataFrame([
        {
            "entity_id": x["entity_id"],
            "Statut": label_status(x.get("current_status")),
            "Postulé": "Oui" if x.get("has_applied") else "Non",
            "Poste": x.get("title"),
            "Entreprise": x.get("company"),
            "Lieu": x.get("location"),
            "Track": x.get("track"),
            "Dernière mise à jour": x.get("status_at"),
            "Lien": x.get("url"),
        }
        for x in rows
    ])
    event = st.dataframe(
        df,
        width="stretch",
        height=520,
        hide_index=True,
        column_config={
            "entity_id": None,
            "Lien": st.column_config.LinkColumn("Offre", display_text="🔗 Ouvrir"),
        },
        on_select="rerun",
        selection_mode="single-row",
        key="applications_table",
    )
    if event.selection.rows:
        row = rows[event.selection.rows[0]]
        st.divider()
        st.subheader(row.get("title") or "Candidature")
        st.write(f"**{row.get('company') or '—'}** — {row.get('location') or '—'}")
        if row.get("url"):
            st.link_button("🔗 Ouvrir l'annonce", row["url"])
        st.markdown("#### Historique")
        history = entity_history(int(row["entity_id"]))
        st.dataframe(pd.DataFrame(history), width="stretch", hide_index=True)


def _handoff_filter_signature(search: str, sources: list[str], actions: list[str], only_not_applied: bool) -> str:
    payload = json.dumps(
        [search, sorted(sources), sorted(actions), bool(only_not_applied)],
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.md5(payload.encode("utf-8")).hexdigest()[:10]


def handoff_page():
    st.caption(
        "Aucune API OpenAI n'est utilisée. Tu choisis toi-même les offres, puis JobHunter crée uniquement les ZIP à envoyer manuellement dans ChatGPT."
    )

    candidates, pool_path = load_handoff_candidates()
    if not candidates:
        st.info("Aucun Final Application Pool disponible. Lance d'abord JobHunter.")
        return

    if pool_path:
        st.caption(f"Final Pool utilisé : {pool_path.name}")

    valid_keys = {str(x.get("stable_item_key")) for x in candidates if x.get("stable_item_key")}
    selected = set(st.session_state.get("handoff_selected_keys", [])) & valid_keys
    st.session_state["handoff_selected_keys"] = list(selected)
    revision = int(st.session_state.get("handoff_editor_revision", 0))

    source_values = sorted({str(x.get("source")) for x in candidates if x.get("source")})
    action_values = sorted({
        str(x.get("recommended_action_v12") or x.get("recommended_action"))
        for x in candidates
        if x.get("recommended_action_v12") or x.get("recommended_action")
    })

    f1, f2, f3, f4 = st.columns([3, 2, 2, 1.5])
    search = f1.text_input("Recherche", placeholder="poste, entreprise, lieu…", key="handoff_search")
    sources = f2.multiselect("Sources", source_values, key="handoff_sources")
    actions = f3.multiselect("Actions", action_values, default=action_values, key="handoff_actions")
    only_not_applied = f4.toggle("Non postulées", value=True, key="handoff_not_applied")

    search_l = search.strip().lower()
    shown = []
    for job in candidates:
        if search_l:
            hay = " ".join(str(job.get(k) or "") for k in ("title", "company", "location")).lower()
            if search_l not in hay:
                continue
        if sources and str(job.get("source") or "") not in sources:
            continue
        action = str(job.get("recommended_action_v12") or job.get("recommended_action") or "")
        if actions and action not in actions:
            continue
        if only_not_applied and str(job.get("applied") or "").lower() == "oui":
            continue
        shown.append(job)

    b1, b2, b3, b4 = st.columns([1.6, 1.4, 1.2, 3.8])
    if b1.button("☑ Tout sélectionner affiché", disabled=not shown, key="handoff_select_visible"):
        selected.update(str(x.get("stable_item_key")) for x in shown if x.get("stable_item_key"))
        st.session_state["handoff_selected_keys"] = list(selected)
        st.session_state["handoff_editor_revision"] = revision + 1
        st.rerun()
    if b2.button("☐ Désélectionner affiché", disabled=not shown, key="handoff_unselect_visible"):
        selected.difference_update(str(x.get("stable_item_key")) for x in shown if x.get("stable_item_key"))
        st.session_state["handoff_selected_keys"] = list(selected)
        st.session_state["handoff_editor_revision"] = revision + 1
        st.rerun()
    if b3.button("🧹 Tout effacer", disabled=not selected, key="handoff_clear_all"):
        st.session_state["handoff_selected_keys"] = []
        st.session_state["handoff_editor_revision"] = revision + 1
        st.rerun()
    b4.info(f"**{len(selected)} offre(s) sélectionnée(s)** — {len(shown)} actuellement affichée(s)")

    rows = []
    for job in shown:
        stable = str(job.get("stable_item_key") or "")
        rows.append({
            "Sélection": stable in selected,
            "stable_item_key": stable,
            "Rang": job.get("pool_rank_v12", job.get("pool_rank")),
            "Score": job.get("final_score_v12", job.get("final_score")),
            "Action": job.get("recommended_action_v12", job.get("recommended_action")),
            "Postulé": job.get("applied", "Non"),
            "Statut": label_status(job.get("application_status")),
            "Poste": job.get("title"),
            "Entreprise": job.get("company"),
            "Lieu": job.get("location"),
            "Source": job.get("source"),
            "Track": job.get("cv_track") or job.get("track"),
            "Lien": job.get("url"),
        })

    if rows:
        df = pd.DataFrame(rows)
        signature = _handoff_filter_signature(search, sources, actions, only_not_applied)
        editor_key = f"handoff_editor_{revision}_{signature}"
        edited = st.data_editor(
            df,
            width="stretch",
            height=520,
            hide_index=True,
            num_rows="fixed",
            disabled=[
                "stable_item_key", "Rang", "Score", "Action", "Postulé", "Statut",
                "Poste", "Entreprise", "Lieu", "Source", "Track", "Lien",
            ],
            column_config={
                "Sélection": st.column_config.CheckboxColumn("Choisir", width="small"),
                "stable_item_key": None,
                "Rang": st.column_config.NumberColumn("#", format="%d", width="small"),
                "Score": st.column_config.NumberColumn("Score", format="%.1f", width="small"),
                "Poste": st.column_config.TextColumn("Poste", width="large"),
                "Entreprise": st.column_config.TextColumn("Entreprise", width="medium"),
                "Lieu": st.column_config.TextColumn("Lieu", width="medium"),
                "Lien": st.column_config.LinkColumn("Offre", display_text="🔗 Ouvrir", width="small"),
            },
            key=editor_key,
        )

        visible_keys = {str(value) for value in df["stable_item_key"].tolist() if str(value)}
        selected_visible = {
            str(value)
            for value in edited.loc[edited["Sélection"] == True, "stable_item_key"].tolist()  # noqa: E712
            if str(value)
        }
        new_selected = (selected - visible_keys) | selected_visible
        if new_selected != selected:
            selected = new_selected
            st.session_state["handoff_selected_keys"] = list(selected)
            st.rerun()

    st.divider()
    st.markdown("### Créer les chunks")
    c1, c2, c3 = st.columns([1.4, 2.0, 4.6])
    chunk_size = int(c1.number_input("Offres par chunk", min_value=1, max_value=50, value=10, step=1, key="handoff_chunk_size"))
    c2.metric("Sélection actuelle", len(selected))
    c3.caption(
        "Exemple : 23 offres avec une taille de 10 → 3 ZIP (10 + 10 + 3). Aucun chunk n'est créé tant que tu ne cliques pas sur le bouton."
    )

    if st.button(
        "📦 Créer les chunks ChatGPT sélectionnés",
        type="primary",
        disabled=not selected,
        key="handoff_create",
    ):
        try:
            ordered_keys = [
                str(job.get("stable_item_key"))
                for job in candidates
                if str(job.get("stable_item_key") or "") in selected
            ]
            with st.spinner("Création des chunks sélectionnés…"):
                result = create_manual_handoff(ordered_keys, chunk_size=chunk_size)
            st.session_state["handoff_last_created_dir"] = str(result["export_dir"])
            st.session_state["handoff_last_created_zips"] = [str(path) for path in result["chunk_zips"]]
            st.success(
                f"Handoff créé : {len(ordered_keys)} offre(s), {len(result['chunk_zips'])} chunk(s)."
            )
        except Exception as exc:
            st.error(f"Impossible de créer les chunks : {exc}")

    created_dir = st.session_state.get("handoff_last_created_dir")
    created_zips = st.session_state.get("handoff_last_created_zips") or []
    if created_dir:
        st.markdown("#### Dernier handoff créé pendant cette session")
        st.code("\n".join(Path(path).name for path in created_zips) or "Aucun ZIP", language=None)
        oc1, oc2 = st.columns([1.6, 5.4])
        if oc1.button("📂 Ouvrir le dossier des chunks", type="primary", key="handoff_open_created"):
            try:
                open_folder(Path(created_dir).parent)
                st.toast("Explorateur Windows ouvert.")
            except Exception as exc:
                st.error(f"Impossible d'ouvrir le dossier : {exc}")
        oc2.code(str(Path(created_dir).parent), language=None)

    st.divider()
    st.markdown("### Historique des handoffs")
    history = handoff_history(limit=15)
    if not history:
        st.info("Aucun handoff créé pour le moment.")
        return

    for idx, item in enumerate(history):
        stamp = str(item.get("generated_at") or "—").replace("T", " ")
        chunks = item.get("chunk_zips") or []
        with st.expander(
            f"{stamp} — {item.get('selected_count', 0)} offre(s) — {len(chunks)} chunk(s)",
            expanded=idx == 0,
        ):
            if chunks:
                st.code("\n".join(path.name for path in chunks), language=None)
            else:
                st.caption("Aucun ZIP chunk détecté pour ce handoff historique.")
            hc1, hc2 = st.columns([1.7, 5.3])
            if hc1.button("📂 Ouvrir le dossier", key=f"handoff_history_open_{idx}"):
                try:
                    open_folder(Path(item["folder"]).parent)
                    st.toast("Explorateur Windows ouvert.")
                except Exception as exc:
                    st.error(f"Impossible d'ouvrir le dossier : {exc}")
            hc2.code(str(Path(item["folder"]).parent), language=None)


def sources_page():
    st.caption("Les cases contrôlent quelles sources seront interrogées au prochain run. Désactiver une source ne supprime pas son historique.")
    registry = registered_sources()
    metrics = {str(row.get("source") or "").upper(): row for row in source_metrics()}

    st.markdown("### Registre des sources")
    st.caption(
        "Les sources actives sont collectées au prochain Daily Run. "
        "Jobat est configuré en recherche FR/EN uniquement."
    )

    key_to_label = {row["key"]: row["source"] for row in registry}
    default_enabled = [row["key"] for row in registry if row.get("active")]
    enabled = st.multiselect(
        "Sources actives",
        options=[row["key"] for row in registry],
        default=default_enabled,
        format_func=lambda key: key_to_label.get(key, key),
        key="registry_enabled_sources",
    )

    c1, c2 = st.columns([1.4, 5.6])
    if c1.button("💾 Enregistrer", type="primary", key="save_source_registry"):
        update_enabled_sources(enabled)
        st.success("Configuration des sources enregistrée. Elle sera utilisée au prochain lancement.")
        st.rerun()
    c2.caption("Désactiver une source ne supprime aucune offre historique de SQLite.")

    display_rows = []
    for row in registry:
        # Les données historiques utilisent collection_channel, généralement identique à la clé.
        historic = metrics.get(str(row["key"]).upper(), {})
        display_rows.append(
            {
                "Active": "✅" if row.get("active") else "⏸️",
                "Source": row.get("source"),
                "Langues": row.get("langues"),
                "Groupe": row.get("groupe"),
                "Offres historiques": historic.get("total_historique", 0),
                "Actives DB": historic.get("actives", 0),
                "Dernière vue": historic.get("derniere_vue") or "—",
                "Note": row.get("notes"),
            }
        )
    st.dataframe(pd.DataFrame(display_rows), width="stretch", hide_index=True)

    st.info(
        "Nouvelle architecture : pour les prochaines sources (StepStone, Science@Work, Randstad…), "
        "on les ajoute au registre au lieu de recâbler toute la collecte dans main.py."
    )


def history_page():
    st.caption("Historique des collectes enregistrées en base : volume collecté, insertions, mises à jour et erreurs.")
    rows = collection_history(50)
    if not rows:
        st.info("Aucun historique de collecte.")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


st.title("🎯 JobHunter")
st.caption("Cockpit local — collecte, scoring, feedback personnel, priorisation et suivi de tes candidatures")

with st.sidebar:
    st.markdown("### Navigation")
    page = st.radio(
        "Navigation principale",
        [
            "🏠 Dashboard",
            "🧭 Comprendre JobHunter",
            "✅ Final Pool",
            "🆕 Delta / Nouveautés",
            "🎯 Queue qualifiée",
            "💼 Toutes les offres",
            "📝 Mes évaluations",
            "📨 Mes candidatures",
            "📦 Handoff ChatGPT",
            "📡 Sources",
            "🕒 Historique",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    st.caption(f"Projet : {ROOT}")
    st.caption("JobHunter UI V2.3 — cockpit production + feedback")

if page == "🏠 Dashboard":
    dashboard_page()
elif page == "🧭 Comprendre JobHunter":
    guide_page()
elif page == "✅ Final Pool":
    pool, _, pool_path = load_latest_final_pool()
    decorated = decorate_scored_jobs(pool, final=True)
    st.subheader("✅ Final Pool")
    st.caption("Liste finale après Refresh + Recheck : c’est la vue de référence pour choisir tes candidatures.")
    if pool_path:
        st.caption(f"Artefact : {pool_path.name}")
    scored_tab(decorated, "final", "pool")
elif page == "🆕 Delta / Nouveautés":
    st.subheader("🆕 Delta / Nouveautés")
    delta_page()
elif page == "🎯 Queue qualifiée":
    queue, queue_path = load_latest_queue()
    decorated = decorate_scored_jobs(queue, final=False)
    st.subheader("🎯 Queue qualifiée")
    st.caption("Liste plus large issue du Gate/Queue, avant les vérifications LIVE finales.")
    if queue_path:
        st.caption(f"Artefact : {queue_path.name}")
    scored_tab(decorated, "queue", "queue")
elif page == "💼 Toutes les offres":
    st.subheader("💼 Toutes les offres")
    all_jobs_page()
elif page == "📝 Mes évaluations":
    st.subheader("📝 Mes évaluations")
    feedback_page()
elif page == "📦 Handoff ChatGPT":
    st.subheader("📦 Handoff ChatGPT")
    handoff_page()
elif page == "📨 Mes candidatures":
    st.subheader("📨 Mes candidatures")
    applications_page()
elif page == "📡 Sources":
    st.subheader("📡 Sources")
    sources_page()
elif page == "🕒 Historique":
    st.subheader("🕒 Historique des collectes")
    history_page()

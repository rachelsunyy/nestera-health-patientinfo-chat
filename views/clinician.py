"""Clinician page: today's roster, then one patient's summary, trends and questions."""

import re
from datetime import date, datetime

import pandas as pd
import streamlit as st

import ui_theme
from agents.summary_agent import SummaryAgent
from agents.trends import IMPROVING, VITAL_LABELS, WINDOW, WORSENING, assess_trend
from data.models import DoctorQuestions, PatientRecord
from views.registration import ExistingPatient, InvalidUpload, NewPatient, read_upload
from views.shared import SAMPLE_DIR, get_db, patient_names

# None is a patient with no check-in today; they rank between attention and routine.
TRIAGE_RANK = {"Escalate": 0, "Schedule visit": 1, None: 2, "Routine review": 3}
ROSTER_REFRESH_SECONDS = 10


def show_summary(summary) -> None:
    ai_chip = (" &nbsp; " + ui_theme.chip("AI-assisted", "gray")) if summary.ai_models else ""
    st.markdown(
        "**Recommended action** &nbsp; "
        + ui_theme.chip(summary.recommended_action, ui_theme.action_tone(summary.recommended_action))
        + ai_chip,
        unsafe_allow_html=True,
    )
    if summary.flagged_items:
        st.error("⚠️ Items requiring clinician attention")
        for item in summary.flagged_items:
            st.markdown(f"- {item}")

    # The stored note repeats the action and flagged items already shown above
    note = re.sub(
        r"### ⚠️ Items Requiring Attention\n.*?(?=\n### )", "",
        summary.summary_markdown, flags=re.S,
    )
    note = re.sub(r"### Recommended Action:[^\n]*\n", "", note)
    st.markdown(note)
    try:
        generated = datetime.fromisoformat(summary.generated_at).strftime("%b %d, %Y at %-I:%M %p")
    except ValueError:
        generated = summary.generated_at
    st.caption(f"Note generated: {generated}")


def checkin_time(checkin) -> str:
    return datetime.fromisoformat(checkin.timestamp).strftime("%-I:%M %p")


def select_patient(patient_id: str | None) -> None:
    st.session_state.clinician_patient_id = patient_id
    if patient_id is None:
        st.query_params.clear()
    # Open lives in the auto-refreshing fragment, whose clicks rerun only the fragment
    st.rerun()


def roster_row(pid: str, name: str, today: str) -> dict:
    rec = db.get_patient(pid)
    todays = db.get_checkins_for_date(pid, today)
    summ = db.get_summary(pid, todays[-1].id) if todays else None
    action = summ.recommended_action if summ else None
    return {
        "id": pid,
        "name": name,
        "diagnosis": rec.primary_diagnosis,
        "status_html": ui_theme.chip("Completed" if todays else "Not started", "green" if todays else "gray")
        + (f'<div class="nh-sub">{len(todays)} check-ins today</div>' if len(todays) > 1 else ""),
        "action_html": (
            ui_theme.chip(action, ui_theme.action_tone(action))
            if action else '<span style="color:#7A8794">—</span>'
        ),
        "done": bool(todays),
        "attention": action not in (None, "Routine review"),
        "rank": TRIAGE_RANK.get(action or ("Routine review" if todays else None), 1),
    }


def uploader_key() -> str:
    return f"register_upload_{st.session_state.get('register_uploads', 0)}"


def save_record(record: PatientRecord, verb: str) -> None:
    db.save_patient(record)
    st.session_state.register_notice = ("success", f"✅ {verb} {record.name} ({record.patient_id})")


def on_upload() -> None:
    uploaded = st.session_state[uploader_key()]
    if uploaded is None:
        return
    # A fresh key empties the uploader, so this file is handled exactly once
    st.session_state.register_uploads = st.session_state.get("register_uploads", 0) + 1
    st.session_state.register_pending = None
    match read_upload(uploaded.getvalue(), db.list_patient_ids()):
        case InvalidUpload(problems):
            lines = "\n".join(f"- {p}" for p in problems)
            st.session_state.register_notice = ("error", f"This file could not be registered:\n\n{lines}")
        case ExistingPatient(record):
            st.session_state.register_pending = record
        case NewPatient(record):
            save_record(record, "Registered:")


def replace_existing() -> None:
    save_record(st.session_state.register_pending, "Replaced the record for")
    st.session_state.register_pending = None


def keep_existing() -> None:
    st.session_state.register_pending = None
    st.session_state.register_notice = ("info", "Nothing was changed.")


def register_patient(names: dict[str, str]) -> None:
    st.file_uploader("Upload patient record JSON", type="json", key=uploader_key(), on_change=on_upload)
    if notice := st.session_state.pop("register_notice", None):
        kind, text = notice
        getattr(st, kind)(text)
    if pending := st.session_state.get("register_pending"):
        st.warning(
            f"A patient with id **{pending.patient_id}** is already registered as "
            f"**{names.get(pending.patient_id, pending.patient_id)}**. Replacing overwrites their record "
            "with the uploaded file. Their check-ins and notes are kept."
        )
        with st.container(horizontal=True):
            st.button("Replace the existing record", type="primary", on_click=replace_existing)
            st.button("Keep the existing record", on_click=keep_existing)

    sample_path = SAMPLE_DIR / "patient_001.json"
    if sample_path.exists():
        st.markdown("**Required JSON format**")
        st.code(sample_path.read_text(), language="json")


@st.fragment(run_every=ROSTER_REFRESH_SECONDS)
def roster_list() -> None:
    names = patient_names(db)
    today = date.today().isoformat()
    with st.container(horizontal=True, vertical_alignment="center"):
        st.caption(f"Updated {datetime.now():%-I:%M:%S %p}. Refreshes every {ROSTER_REFRESH_SECONDS} seconds.")
        st.button("Refresh", icon=":material/refresh:", type="tertiary", key="refresh_roster")
    if not names:
        st.info("No patients are registered yet. Register one below.")
        return
    rows = sorted((roster_row(pid, name, today) for pid, name in names.items()),
                  key=lambda r: (r["rank"], r["name"]))
    n_done = sum(r["done"] for r in rows)
    n_attn = sum(r["attention"] for r in rows)
    ui_theme.kpi_row([
        ("Patients", len(rows), ""),
        ("Check-ins complete", f"{n_done} / {len(rows)}", "green" if n_done == len(rows) else ""),
        ("Need attention", n_attn, "red" if n_attn else "green"),
    ])
    with st.container(key="roster"):
        st.columns([6, 1])[0].markdown(ui_theme.roster_header(), unsafe_allow_html=True)
        for r in rows:
            with st.container(key=f"roster_row_{r['id']}"):
                info, action = st.columns([6, 1], vertical_alignment="center")
                info.markdown(ui_theme.roster_row(r), unsafe_allow_html=True)
                action.button("Open", key=f"open_{r['id']}", on_click=select_patient, args=(r["id"],))


def show_roster(names: dict[str, str]) -> None:
    ui_theme.hero("Clinician Dashboard", f"{date.today().strftime('%A, %B %d, %Y')}  ·  Today's check-in overview")
    roster_list()
    st.write("")
    with st.expander("➕ Register a new patient", expanded=not names):
        register_patient(names)


def show_patient(selected_id: str) -> None:
    record = db.get_patient(selected_id)
    with st.container(horizontal=True, horizontal_alignment="distribute"):
        st.button("Back to roster", icon=":material/arrow_back:", type="tertiary", on_click=select_patient, args=(None,))
        st.button("Refresh", icon=":material/refresh:", type="tertiary", key="refresh_patient")
    ui_theme.hero(record.name, f"Patient detail  ·  {date.today().strftime('%A, %B %d, %Y')}")
    ui_theme.detail_cards([
        ("Patient ID", record.patient_id),
        ("Primary diagnosis", record.primary_diagnosis),
        ("Admitted", record.admission_date),
    ])
    st.write("")

    tab_summary, tab_trends, tab_questions = st.tabs(["📋 Clinical Summary", "📈 Trends", "❓ Add Questions"])
    today = date.today().isoformat()

    with tab_summary:
        todays = db.get_checkins_for_date(selected_id, today)
        if todays:
            latest = todays[-1]
            if len(todays) > 1:
                st.caption(f"{len(todays)} check-ins today. Showing the latest, from {checkin_time(latest)}.")
            existing = db.get_summary(selected_id, latest.id)
            if existing:
                show_summary(existing)
            else:
                st.info("Check-in completed. Generating clinical note…")
                try:
                    show_summary(SummaryAgent(selected_id, db).generate(latest.id))
                except Exception as e:
                    st.error(f"Could not generate summary: {e}")
        else:
            st.info(
                f"**{record.name}** has not completed today's check-in yet ({today}). "
                "The summary will appear here automatically once they finish."
            )

        history = db.get_recent_checkins(selected_id, n=5)
        if history:
            with st.expander("View recent check-in responses"):
                for ci in history:
                    st.markdown(f"**{ci.date} at {checkin_time(ci)}**")
                    st.table(pd.DataFrame(
                        {"Question": [r.question for r in ci.responses], "Answer": [r.answer for r in ci.responses]},
                        index=range(1, len(ci.responses) + 1),
                    ))

    with tab_trends:
        report = assess_trend(db.get_recent_checkins(selected_id, n=WINDOW + 5))
        tone = {WORSENING: "red", IMPROVING: "green"}.get(report.status, "gray")
        st.markdown(
            f"**Trajectory over the last {len(report.points)} check-ins** &nbsp; "
            + ui_theme.chip(report.status, tone),
            unsafe_allow_html=True,
        )
        for reason in report.reasons:
            st.markdown(f"- {reason}")
        if len(report.points) >= 2:
            chart = pd.DataFrame(
                {VITAL_LABELS[k]: {p.label: p.vitals[k] for p in report.points if k in p.vitals}
                 for k in VITAL_LABELS if any(k in p.vitals for p in report.points)}
            )
            for col in chart.columns:
                st.caption(col)
                st.line_chart(chart[col].dropna())
            st.caption(
                "Trend rules and bands are prototype values, not clinically validated. "
                "Readings are taken from the patient's own answers."
            )

    with tab_questions:
        st.subheader(f"Add questions for {record.name}'s next check-in")
        st.caption(
            "These questions will appear first in the chatbot, "
            "before the standard personalized questions."
        )
        existing_qs = db.get_doctor_questions(selected_id, today)
        if existing_qs:
            st.markdown("**Already added for today:**")
            for q in existing_qs:
                st.markdown(f"- {q}")
            st.divider()

        added_by = st.text_input("Your name", placeholder="Dr. Smith")
        new_q = st.text_area(
            "Enter questions — one per line",
            placeholder=(
                "Did you notice any new swelling in your legs?\n"
                "Did you weigh yourself before breakfast today?"
            ),
            height=150,
        )
        if st.button("Save questions", type="primary"):
            questions = [q.strip() for q in new_q.strip().splitlines() if q.strip()]
            if not questions:
                st.error("Please enter at least one question.")
            else:
                db.save_doctor_questions(DoctorQuestions(
                    patient_id=selected_id,
                    questions=questions,
                    added_by=added_by or "Clinician",
                ))
                st.success(f"✅ {len(questions)} question(s) saved for {record.name}.")


db = get_db()
names = patient_names(db)
st.set_page_config(page_title="Clinician Dashboard · Nestera Health", layout="wide")
ui_theme.brand_header()

if "clinician_patient_id" not in st.session_state:
    linked = st.query_params.get("patient")
    st.session_state.clinician_patient_id = linked if linked in names else None
    if linked and linked not in names:
        st.info(f"No patient with id {linked}. Showing today's roster.")

selected = st.session_state.clinician_patient_id
with st.container(key="clinician_page"):
    if selected in names:
        show_patient(selected)
    else:
        show_roster(names)

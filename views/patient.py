"""Patient page: pick your name, then the daily check-in chat."""

from dataclasses import dataclass, field
from datetime import date

import streamlit as st

import config
import ui_theme
from agents.conversation_agent import ConversationalPatientAgent
from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent
from views.shared import get_db, patient_names


@dataclass
class CheckinSession:
    agent: PatientAgent | ConversationalPatientAgent
    messages: list[dict] = field(default_factory=list)
    done: bool = False


def start_checkin(patient_id: str) -> CheckinSession:
    agent_class = ConversationalPatientAgent if config.AI_CONVERSATION_ENABLED else PatientAgent
    agent = agent_class(patient_id, db)
    opening = agent.start_session()
    return CheckinSession(agent, [{"role": "assistant", "content": opening}])


def begin(patient_id: str) -> None:
    try:
        st.session_state.checkin = start_checkin(patient_id)
    except Exception as e:
        st.session_state.checkin = None
        st.error(f"Could not load your information: {e}")


def start_over() -> None:
    st.session_state.checkin = None
    st.query_params.clear()


db = get_db()
names = patient_names(db)
st.set_page_config(page_title="Daily Check-In · Nestera Health")
ui_theme.brand_header()

if "checkin" not in st.session_state:
    st.session_state.checkin = None
    linked = st.query_params.get("patient")
    if linked in names:
        begin(linked)
    elif linked:
        st.info("We couldn't find that check-in link. Please choose your name below.")

session: CheckinSession | None = st.session_state.checkin

if session is None:
    ui_theme.hero("Who is checking in today?", date.today().strftime("%A, %B %d, %Y"))
    if not names:
        st.info("No patients are registered yet. A doctor or care coordinator must register you first.")
        st.stop()
    chosen = st.selectbox(
        "Your name", list(names), index=None, format_func=names.get, placeholder="Choose your name",
    )
    if st.button("Start", type="primary", disabled=chosen is None, key="start"):
        begin(chosen)
        if st.session_state.checkin:
            st.rerun()
    st.stop()

agent = session.agent
record = agent.record
ui_theme.hero(
    f"Daily Check-In — {record.name}",
    f"{date.today().strftime('%A, %B %d, %Y')}  ·  Care team: {record.care_team_contact}",
)
answered, total = agent.progress
if session.done:
    answered = total
st.progress(answered / total if total else 0.0, text=f"{answered} of {total} questions answered")
ui_theme.emergency_notice(record.care_team_contact)

for msg in session.messages:
    avatar = "🏥" if msg["role"] == "assistant" else "🙋"
    with st.chat_message(msg["role"], avatar=avatar):
        st.markdown(msg["content"])

if session.done:
    if getattr(agent, "ended_early", False):
        st.warning("Your check-in was ended early so you can get help. What you shared has been saved for your care team.")
    else:
        st.success(
            "✅ **Check-in complete!** Your responses have been saved "
            "and your care team will review them."
        )
    if st.button("Start a new check-in", type="secondary"):
        begin(agent.patient_id)
        st.rerun()

st.button("Not you? Start over", type="tertiary", on_click=start_over)

if not session.done:
    user_input = st.chat_input("Type your answer here and press Enter…")
    if user_input:
        session.messages.append({"role": "user", "content": user_input})
        with st.chat_message("user", avatar="🙋"):
            st.markdown(user_input)

        reply, done = agent.respond(user_input)

        with st.chat_message("assistant", avatar="🏥"):
            st.markdown(reply)
        session.messages.append({"role": "assistant", "content": reply})
        session.done = done

        if done:
            try:
                SummaryAgent(agent.patient_id, db).generate()
            except Exception:
                pass  # the clinician page generates a missing note on demand

        st.rerun()

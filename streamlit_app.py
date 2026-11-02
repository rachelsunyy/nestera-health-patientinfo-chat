"""Nestera Health Hospital-at-Home check-in: routes / to the landing page, /patient and /clinician to each experience.

Workflow:
  1. A clinician registers a patient record, which adds the patient to the roster.
  2. The patient opens /patient, picks their name and answers personalized questions.
  3. The check-in is saved and its clinical summary generated the moment the patient finishes.
  4. The clinician opens /clinician and sees the note built from the patient's exact responses.
"""

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

st.set_page_config(
    page_icon="assets/nestera-mark.svg",
    layout="centered",
    initial_sidebar_state="collapsed",
)

import ui_theme
from views.shared import get_db

ui_theme.inject_css()
get_db()

st.navigation(
    [
        st.Page("views/landing.py", default=True),
        st.Page("views/patient.py", url_path="patient"),
        st.Page("views/clinician.py", url_path="clinician"),
    ],
    position="hidden",
).run()

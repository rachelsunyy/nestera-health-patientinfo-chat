"""Landing page: the only screen that offers both the patient and the clinician experience."""

import streamlit as st

import ui_theme

st.set_page_config(page_title="Nestera Health")
ui_theme.brand_header()
ui_theme.hero("Welcome to your daily check-in", "Choose how you are using Nestera today.")

patient_col, clinician_col = st.columns(2)
with patient_col, st.container(border=True, key="role_patient"):
    st.markdown("### I'm a patient")
    st.markdown("Answer a few short questions about how you are feeling today. Your care team reviews every answer.")
    st.page_link("views/patient.py", label="Start my check-in", icon=":material/arrow_forward:")
with clinician_col, st.container(border=True, key="role_clinician"):
    st.markdown("### I'm a clinician")
    st.markdown("See today's check-ins for your patients, with clinical notes, flagged items and trends.")
    st.page_link("views/clinician.py", label="Open the dashboard", icon=":material/arrow_forward:")

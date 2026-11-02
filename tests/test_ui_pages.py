"""Each URL shows one role: / offers both, /patient only the check-in, /clinician only the dashboard."""

from agents.patient_agent import PatientAgent
from agents.summary_agent import SummaryAgent
from database.patient_db import MockPatientDatabase
from scripts import seed_demo
from tests.test_seed_demo import kpis, roster_cells

CLINICIAN_STRINGS = ["View as", "Doctor / Nurse", "Clinician Dashboard", "Register a new patient", "Back to roster"]


def screen_text(at) -> str:
    texts = [e.value for kind in ("markdown", "caption", "info", "success", "warning", "error", "subheader")
             for e in getattr(at, kind)]
    texts += [w.label for kind in ("button", "selectbox", "radio", "text_input", "text_area") for w in getattr(at, kind)]
    texts += [t.label for t in at.tabs]
    return "\n".join(str(t) for t in texts if not str(t).startswith("<style>"))


def test_landing_offers_both_experiences(db, open_page):
    at = open_page()
    links = {link.proto.page: link.proto.label for link in at.get("page_link")}
    assert links == {"patient": "Start my check-in", "clinician": "Open the dashboard"}
    assert "I'm a patient" in screen_text(at) and "I'm a clinician" in screen_text(at)


def test_patient_page_shows_nothing_but_the_check_in(db, open_page):
    at = open_page("patient")
    assert not at.sidebar.children
    text = screen_text(at)
    assert "Who is checking in today?" in text
    for s in CLINICIAN_STRINGS:
        assert s not in text, s

    at.selectbox[0].set_value("patient_001").run()
    at.button(key="start").click().run()
    assert "Hello Margaret!" in at.chat_message[0].markdown[0].value
    at.chat_input[0].set_value("Yes, 150 pounds.").run()
    assert at.chat_message[1].markdown[0].value == "Yes, 150 pounds."
    assert len(at.chat_message) == 3
    assert not at.sidebar.children
    text = screen_text(at)
    for s in CLINICIAN_STRINGS:
        assert s not in text, s


def test_start_is_disabled_until_a_name_is_chosen(db, open_page):
    at = open_page("patient")
    assert at.button(key="start").disabled
    at.selectbox[0].set_value("patient_002").run()
    assert not at.button(key="start").disabled


def test_patient_link_skips_the_picker_and_start_over_returns_to_it(db, open_page):
    at = open_page("patient", patient="patient_002")
    assert not at.selectbox
    assert at.chat_message[0].markdown[0].value.startswith("Hello Robert!")

    next(b for b in at.button if b.label == "Not you? Start over").click().run()
    assert not at.chat_message
    assert "Who is checking in today?" in screen_text(at)


def test_unknown_patient_link_explains_and_shows_the_picker(db, open_page):
    at = open_page("patient", patient="nobody")
    assert "couldn't find that check-in link" in at.info[0].value
    assert at.selectbox[0].label == "Your name"
    assert not at.chat_message


def test_clinician_roster_opens_a_patient_and_comes_back(db, open_page, tmp_path):
    seed_demo.seed(tmp_path)
    at = open_page("clinician")
    assert not at.sidebar.children
    assert "View as" not in screen_text(at)
    open_keys = [b.key for b in at.button if b.label == "Open"]
    assert sorted(open_keys) == sorted(f"open_{pid}" for pid in db.list_patient_ids())

    at.button(key="open_demo_twice").click().run()
    assert not [b for b in at.button if b.label == "Open"]
    assert [t.label for t in at.tabs] == ["📋 Clinical Summary", "📈 Trends", "❓ Add Questions"]
    assert any("Samuel Park" in m.value for m in at.markdown)

    next(b for b in at.button if b.label == "Back to roster").click().run()
    assert sorted(b.key for b in at.button if b.label == "Open") == sorted(open_keys)


def test_clinician_link_opens_the_patient_detail(db, open_page):
    at = open_page("clinician", patient="patient_003")
    assert any(b.label == "Back to roster" for b in at.button)
    assert not [b for b in at.button if b.label == "Open"]


def test_recent_responses_are_one_question_answer_table_per_check_in(db, open_page, tmp_path):
    seed_demo.seed(tmp_path)
    at = open_page("clinician", patient="demo_twice")
    checkins = db.get_recent_checkins("demo_twice", n=5)
    assert len(at.table) == len(checkins) == 3
    for table, ci in zip(at.table, checkins):
        df = table.value
        assert list(df.columns) == ["Question", "Answer"]
        assert list(df["Answer"]) == [r.answer for r in ci.responses]


def finish_check_in(db, pid: str) -> None:
    agent = PatientAgent(pid, db)
    agent.start_session()
    done = False
    while not done:
        _, done = agent.respond("Fine")


def test_roster_refresh_shows_a_check_in_finished_in_another_window(db, open_page):
    at = open_page("clinician")
    assert "Check-ins complete 0 / 3" in kpis(at)
    finish_check_in(db, "patient_001")
    at.button(key="refresh_roster").click().run()
    assert "Check-ins complete 1 / 3" in kpis(at)
    assert roster_cells(at, "patient_001")[-2] == "Completed"


def test_patient_refresh_reloads_check_ins_and_summary(db, open_page):
    at = open_page("clinician", patient="patient_001")
    assert "has not completed today's check-in" in at.info[0].value
    finish_check_in(db, "patient_001")
    at.button(key="refresh_patient").click().run()
    assert not at.exception
    assert any(m.value.startswith("**Recommended action**") for m in at.markdown)
    assert len(at.table) == 1


def test_uploading_an_existing_id_replaces_it_only_after_confirming(db, open_page):
    # AppTest cannot upload files, so the test starts where the upload handler leaves a duplicate
    at = open_page("clinician")
    at.session_state["register_pending"] = db.get_patient("patient_001").model_copy(update={"name": "Maggie Chen"})
    at.run()
    assert "already registered as **Margaret Chen**" in at.warning[0].value
    assert db.get_patient("patient_001").name == "Margaret Chen"

    next(b for b in at.button if b.label == "Replace the existing record").click().run()
    assert at.success[0].value.endswith("Replaced the record for Maggie Chen (patient_001)")
    assert db.get_patient("patient_001").name == "Maggie Chen"
    assert not at.warning
    assert roster_cells(at, "patient_001")[0] == "Maggie Chen"


def test_keeping_the_existing_record_changes_nothing(db, open_page):
    at = open_page("clinician")
    at.session_state["register_pending"] = db.get_patient("patient_002").model_copy(update={"name": "Bob Johnson"})
    at.run()
    next(b for b in at.button if b.label == "Keep the existing record").click().run()
    assert at.info[0].value == "Nothing was changed."
    assert db.get_patient("patient_002").name == "Robert Johnson"
    assert not at.warning


SECRET = "bucket gs://internal-7f3a refused: token expired"


def boom(*args, **kwargs):
    raise RuntimeError(SECRET)


def assert_logged(caplog, logger: str) -> None:
    assert any(r.name == logger and r.exc_info and SECRET in str(r.exc_info[1]) for r in caplog.records)


def test_patient_sees_a_calm_message_with_their_care_team_when_the_check_in_cannot_start(db, open_page, monkeypatch, caplog):
    monkeypatch.setattr(PatientAgent, "__init__", boom)
    at = open_page("patient", patient="patient_001")
    contact = db.get_patient("patient_001").care_team_contact
    assert at.error[0].value == (
        "We couldn't start your check-in just now. Please try again in a few minutes. "
        f"If you need to talk to someone, please call your care team at {contact}. In an emergency, call 911."
    )
    assert SECRET not in screen_text(at)
    assert at.selectbox[0].label == "Your name"
    assert_logged(caplog, "views.patient")


def test_patient_message_still_points_to_the_care_team_when_the_record_cannot_load(db, open_page, monkeypatch):
    monkeypatch.setattr(MockPatientDatabase, "get_patient", boom)
    at = open_page("patient", patient="patient_001")
    assert "please call your care team. In an emergency, call 911." in at.error[0].value
    assert SECRET not in screen_text(at)


def test_a_failed_new_check_in_explains_itself(db, open_page, monkeypatch):
    at = open_page("patient", patient="patient_001")
    while at.chat_input:
        at.chat_input[0].set_value("Fine").run()
    monkeypatch.setattr(PatientAgent, "__init__", boom)
    next(b for b in at.button if b.label == "Start a new check-in").click().run()
    assert at.error[0].value.startswith("We couldn't start your check-in just now.")
    assert SECRET not in screen_text(at)


def test_clinician_sees_a_plain_message_when_the_note_cannot_be_generated(db, open_page, monkeypatch, caplog):
    finish_check_in(db, "patient_001")
    monkeypatch.setattr(SummaryAgent, "generate", boom)
    at = open_page("clinician", patient="patient_001")
    assert at.error[0].value.startswith("The clinical note could not be generated right now.")
    assert SECRET not in screen_text(at)
    assert_logged(caplog, "views.clinician")


def test_a_failed_save_shows_a_plain_message(db, open_page, monkeypatch, caplog):
    at = open_page("clinician")
    at.session_state["register_pending"] = db.get_patient("patient_001")
    at.run()
    monkeypatch.setattr(MockPatientDatabase, "save_patient", boom)
    next(b for b in at.button if b.label == "Replace the existing record").click().run()
    assert at.error[0].value == "The patient record could not be saved. Please try again in a moment."
    assert SECRET not in screen_text(at)
    assert_logged(caplog, "views.clinician")

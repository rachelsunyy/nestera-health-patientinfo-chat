"""Each URL shows one role: / offers both, /patient only the check-in, /clinician only the dashboard."""

from scripts import seed_demo

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

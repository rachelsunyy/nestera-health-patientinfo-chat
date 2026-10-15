"""Scrubbing identifiers out of text before it goes to a model."""

import pytest

from agents.deid import make_scrubber

scrub = make_scrubber(["Margaret Chen"])


@pytest.mark.parametrize("text, forbidden", [
    ("Call me at (312) 555-0199", "555-0199"),
    ("my number is 312-555-0199", "312-555-0199"),
    ("email margaret.chen@example.com", "margaret.chen@example.com"),
    ("I was born 03/15/1948", "1948"),
    ("born March 15, 1948", "March"),
    ("I live at 1234 Elm Street", "1234 Elm"),
    ("zip 60637", "60637"),
    ("MRN 12345678", "12345678"),
    ("SSN 123-45-6789", "123-45-6789"),
    ("Margaret said hi", "Margaret"),
    ("Chen here, feeling fine", "Chen"),
    ("Dr. Patel told me to rest", "Patel"),
    ("my name is Rosa Gomez", "Gomez"),
])
def test_identifiers_are_removed(text, forbidden):
    assert forbidden not in scrub(text)


@pytest.mark.parametrize("text", [
    "BP was 120/80 this morning",
    "oxygen 94%",
    "temperature 101.5",
    "blood sugar 110 and 95",
    "weight up 4 pounds",
    "I took 2 tablets at 8 am",
])
def test_clinical_values_are_left_alone(text):
    assert scrub(text) == text


def test_tags_mark_what_was_removed():
    assert scrub("Call (312) 555-0199") == "Call [PHONE]"


@pytest.mark.parametrize("text", ["this is better today", "this is worse than yesterday", "my cough is worse"])
def test_ordinary_phrases_are_not_mistaken_for_names(text):
    assert "[NAME]" not in scrub(text)

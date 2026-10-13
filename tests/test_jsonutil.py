import pytest

from outreach_studio.jsonutil import parse_json


def test_plain_and_fenced():
    assert parse_json('{"a": 1}') == {"a": 1}
    assert parse_json('```json\n{"a": 2}\n```') == {"a": 2}


def test_surrounding_prose():
    assert parse_json('Here you go:\n{"subject": "Hi"}\nThanks') == {"subject": "Hi"}


def test_garbage_raises():
    with pytest.raises(ValueError):
        parse_json("no json here")

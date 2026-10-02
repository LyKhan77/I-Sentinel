"""Prompt contracts independent of model output."""
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest


def event(kind="idle_zone", naive=False):
    return SimpleNamespace(type=kind, severity="warning", ts_event=datetime(2026, 10, 2, 8, tzinfo=None if naive else timezone.utc),
                           payload={"idle_s": 300, "count": 2, "secret": "excluded"})


@pytest.mark.parametrize("kind,phrase", [("idle_zone", "jongkok"), ("loitering", "dilakukan"), ("intrusion", "pakaian"),
                                         ("crowd", "jumlah"), ("running", "dilakukan"), ("person_detect", "dilakukan")])
def test_default_prompt_per_type(kind, phrase):
    from app.services import ai_prompts as p
    text = p.build_caption_prompt(SimpleNamespace(ai_prompt=None), event(kind), "CAM-01", "Area A")
    assert phrase in text and text.endswith("Jawab maksimal 3 kalimat.")
    assert "CAM-01" in text and "Area A" in text and "warning" in text
    assert "idle_s=300" in text and "secret" not in text


def test_custom_prompt_replaces_default():
    from app.services import ai_prompts as p
    text = p.build_caption_prompt(SimpleNamespace(ai_prompt="Fokus helm"), event(), "CAM-01", "Area A")
    assert "Fokus helm" in text and "jongkok" not in text
    assert all(s in text for s in ("CAM-01", "Area A", "warning", "2026", "Jawab maksimal 3 kalimat."))


def test_naive_ts_event_ok():
    from app.services import ai_prompts as p
    assert p.event_metadata(event(naive=True), None, None) == p.event_metadata(event(), None, None)


def test_preset_keys():
    from app.services import ai_prompts as p
    assert p.preset_keys("idle_zone") == ["what_happened", "false_alarm", "report", "person_in_zone", "last_person", "fallen"]
    assert p.preset_keys("running") == ["what_happened", "false_alarm", "report"]
    assert p.preset_keys("attendance") == p.preset_keys("system") == []
    assert p.preset_question("last_person")


def test_system_prompt_guardrails():
    from app.services import ai_prompts as p
    assert all(s in p.SYSTEM_PROMPT for s in ("tidak dapat ditentukan", "identitas", "usia", "etnis", "jam", "instruksi", "saran"))

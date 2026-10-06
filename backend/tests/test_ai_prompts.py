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


def test_system_prompt_requests_plain_text_and_timeline_format():
    """UI merender baris 'm:dd — kejadian' sebagai linimasa; model diminta tanpa markdown."""
    from app.services import ai_prompts
    prompt = ai_prompts.SYSTEM_PROMPT
    assert "tanpa markdown" in prompt
    assert "m:dd" in prompt and "Kesimpulan:" in prompt
    assert "Frame pada detik" in prompt


@pytest.mark.parametrize("key", ["what_happened", "report"])
def test_chronological_presets_ask_for_a_timeline(key):
    from app.services import ai_prompts
    assert "kronologi" in ai_prompts.preset_question(key).lower()


@pytest.mark.parametrize("key", ["false_alarm", "person_in_zone", "last_person", "fallen", "working_or_standing", "who", "count"])
def test_other_presets_ask_for_a_short_answer_without_timeline(key):
    """Tanpa petunjuk ini model membuat linimasa penuh bahkan untuk pertanyaan ya/tidak."""
    from app.services import ai_prompts
    question = ai_prompts.preset_question(key)
    assert "1-3 kalimat" in question and "kronologi" not in question.lower()


def test_system_prompt_limits_timeline_rows_and_forbids_summary_label():
    """Klip 70 detik menghasilkan 12 baris (3 identik) dan label 'Satu kalimat ringkasan:' ikut tertulis."""
    from app.services import ai_prompts
    prompt = ai_prompts.SYSTEM_PROMPT
    assert "paling banyak 8 baris" in prompt
    assert "gabungkan" in prompt
    assert "tanpa label" in prompt

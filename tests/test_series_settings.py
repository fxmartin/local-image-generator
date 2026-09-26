"""Story 09.1-002: global series settings from the first `gemma` call."""

import json

import pytest

from lig.series import prompts
from lig.series.gemma import GemmaClient, GemmaError
from lig.series.settings import (
    SeriesError,
    SeriesSettings,
    extract_json_object,
    plan_settings,
    requested_count,
)

LOOK = " ".join(["woman"] + ["word"] * 29)  # 30 words


def answer(**overrides) -> dict:
    data = {
        "count": 10,
        "character": {"name": "Camille", "look": LOOK},
        "style": "black and white, 35mm grain",
        "setting": "Paris",
        "arc": "From morning to midnight.",
    }
    data.update(overrides)
    return data


class FakeGemma:
    """Replays canned replies and records each call."""

    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(self, system, request, *, temperature, max_tokens):
        self.calls.append({"system": system, "request": request, "temperature": temperature})
        return self.replies.pop(0)


def plan(client, request="Create 10 photos of a woman in Paris", tmp_path=None, **kw):
    return plan_settings(client, request, series_dir=tmp_path, **kw)


# --- schema ---------------------------------------------------------------


def test_valid_settings_roundtrip():
    s = SeriesSettings.model_validate(answer())
    assert s.character.name == "Camille" and s.count == 10


@pytest.mark.parametrize("words", [24, 81])
def test_look_word_count_bounds(words):
    look = " ".join(["w"] * words)
    with pytest.raises(ValueError):
        SeriesSettings.model_validate(answer(character={"name": "C", "look": look}))


@pytest.mark.parametrize("words", [25, 80])
def test_look_word_count_edges_ok(words):
    look = " ".join(["w"] * words)
    SeriesSettings.model_validate(answer(character={"name": "C", "look": look}))


def test_count_must_be_positive():
    with pytest.raises(ValueError):
        SeriesSettings.model_validate(answer(count=0))


@pytest.mark.parametrize("field", ["style", "setting", "arc"])
def test_blank_fields_rejected(field):
    with pytest.raises(ValueError):
        SeriesSettings.model_validate(answer(**{field: "  "}))


# --- extraction -----------------------------------------------------------


def test_extract_from_code_fence_and_prose():
    raw = 'Sure! Here you go:\n```json\n{"a": {"b": 1}}\n```\nEnjoy {not json}'
    assert extract_json_object(raw) == {"a": {"b": 1}}


def test_extract_handles_braces_inside_strings():
    assert extract_json_object('x {"a": "}{"} y') == {"a": "}{"}


def test_extract_without_object_raises():
    with pytest.raises(ValueError):
        extract_json_object("no json here")


# --- count ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("request_text", "expected"),
    [
        ("Create 10 photos of a woman", 10),
        ("three images of a dog", 3),
        ("a Twelve shot series", 12),
        ("some photos of a woman", None),
    ],
)
def test_requested_count(request_text, expected):
    assert requested_count(request_text) == expected


# --- plan_settings --------------------------------------------------------


def test_plan_returns_validated_settings(tmp_path):
    gemma = FakeGemma(json.dumps(answer()))
    s = plan(gemma, tmp_path=tmp_path)
    assert s.count == 10
    assert len(gemma.calls) == 1
    assert gemma.calls[0]["system"] == prompts.GLOBAL_SYSTEM
    assert gemma.calls[0]["temperature"] == 0.4


def test_named_number_wins_over_gemma(tmp_path):
    s = plan(FakeGemma(json.dumps(answer(count=7))), tmp_path=tmp_path)
    assert s.count == 10


def test_count_flag_overrides_request(tmp_path):
    gemma = FakeGemma(json.dumps(answer(count=10)))
    s = plan(gemma, count=4, tmp_path=tmp_path)
    assert s.count == 4
    assert "exactly 4" in gemma.calls[0]["request"]


def test_gemma_count_used_when_none_named(tmp_path):
    s = plan(FakeGemma(json.dumps(answer(count=6))), request="photos of a cat", tmp_path=tmp_path)
    assert s.count == 6


def test_count_above_max_exits_2_before_any_call(tmp_path):
    gemma = FakeGemma()
    with pytest.raises(SeriesError) as info:
        plan(gemma, request="Create 30 photos of a cat", tmp_path=tmp_path)
    assert info.value.exit_code == 2
    assert gemma.calls == []


def test_count_flag_above_max_exits_2(tmp_path):
    with pytest.raises(SeriesError) as info:
        plan(FakeGemma(), count=5, max_shots=4, tmp_path=tmp_path)
    assert info.value.exit_code == 2


def test_gemma_count_above_max_is_a_schema_violation(tmp_path):
    gemma = FakeGemma(json.dumps(answer(count=50)), json.dumps(answer(count=8)))
    s = plan(gemma, request="photos of a cat", tmp_path=tmp_path)
    assert s.count == 8 and len(gemma.calls) == 2


def test_fenced_answer_is_parsed(tmp_path):
    raw = "Here:\n```json\n" + json.dumps(answer()) + "\n```"
    assert plan(FakeGemma(raw), tmp_path=tmp_path).setting == "Paris"


def test_retry_once_with_error_appended(tmp_path):
    gemma = FakeGemma("not json", json.dumps(answer()))
    plan(gemma, tmp_path=tmp_path)
    assert len(gemma.calls) == 2
    retry = gemma.calls[1]["request"]
    assert gemma.calls[0]["request"] in retry
    assert "not json" in retry and "invalid" in retry.lower()


def test_second_failure_saves_raw_and_exits_1(tmp_path):
    bad = json.dumps(answer(character={"name": "C", "look": "too short"}))
    gemma = FakeGemma("garbage", bad)
    with pytest.raises(SeriesError) as info:
        plan(gemma, tmp_path=tmp_path)
    assert info.value.exit_code == 1
    assert (tmp_path / "settings.invalid.txt").read_text() == bad
    assert len(gemma.calls) == 2


def test_fixed_style_and_setting_are_told_and_kept(tmp_path):
    gemma = FakeGemma(json.dumps(answer(style="sepia", setting="Rome")))
    s = plan(gemma, style="black and white", setting="Lyon", tmp_path=tmp_path)
    request = gemma.calls[0]["request"]
    assert "black and white" in request and "Lyon" in request
    assert "do not change" in request.lower()
    assert (s.style, s.setting) == ("black and white", "Lyon")


def test_temperature_passthrough(tmp_path):
    gemma = FakeGemma(json.dumps(answer()))
    plan(gemma, temperature=0.9, tmp_path=tmp_path)
    assert gemma.calls[0]["temperature"] == 0.9


def test_gemma_errors_propagate(tmp_path):
    class Boom:
        def complete(self, *a, **k):
            raise GemmaError("down")

    with pytest.raises(GemmaError):
        plan(Boom(), tmp_path=tmp_path)


def test_end_to_end_with_stub_gemma(stub_bin_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("STUB_GEMMA_REPLY", json.dumps(answer()))
    s = plan(GemmaClient(), tmp_path=tmp_path)
    assert s.character.name == "Camille"


# --- prompt pins ----------------------------------------------------------


def test_global_prompt_pins_key_rules():
    text = prompts.GLOBAL_SYSTEM.lower()
    assert "25 to 80 words" in text
    assert "never" in text and "place" in text and "action" in text
    assert "shared by every photo" in text
    for key in ("count", "character", "name", "look", "style", "setting", "arc"):
        assert f'"{key}"' in text
    assert "json" in text

"""Story 09.1-004: per-shot scene calls."""

import json

import pytest

from lig.series import prompts
from lig.series.settings import SeriesError, SeriesSettings
from lig.series.shots import plan_shot, plan_shots

LOOK = " ".join(["woman"] + ["word"] * 29)
SCENE = " ".join(["scene"] * 25)


def settings(count: int = 3) -> SeriesSettings:
    return SeriesSettings.model_validate(
        {
            "count": count,
            "character": {"name": "Camille", "look": LOOK},
            "style": "black and white",
            "setting": "Paris",
            "arc": "Morning to midnight.",
        }
    )


def reply(title="T", scene=SCENE) -> str:
    return json.dumps({"title": title, "scene": scene})


class FakeGemma:
    def __init__(self, *replies: str) -> None:
        self.replies = list(replies)
        self.calls: list[dict] = []

    def complete(self, system, request, *, temperature, max_tokens):
        self.calls.append({"system": system, "request": request, "temperature": temperature})
        return self.replies.pop(0)


def test_call_carries_settings_position_and_history():
    gemma = FakeGemma(reply("Third"))
    previous = [plan_shot(FakeGemma(reply("One", "a " * 20)), settings(), 1, [])]
    previous.append(plan_shot(FakeGemma(reply("Two", "b " * 20)), settings(), 2, previous))
    plan_shot(gemma, settings(), 3, previous)
    call = gemma.calls[0]
    assert call["system"] == prompts.SHOT_SYSTEM
    assert '"setting": "Paris"' in call["request"]
    assert "Shot 3 of 3" in call["request"]
    assert "1. One: " in call["request"] and "2. Two: " in call["request"]
    assert call["temperature"] == 0.7


def test_first_shot_has_no_history():
    gemma = FakeGemma(reply())
    plan_shot(gemma, settings(), 1, [])
    assert "already planned" not in gemma.calls[0]["request"]


def test_temperature_passthrough():
    gemma = FakeGemma(reply())
    plan_shot(gemma, settings(), 1, [], temperature=0.9)
    assert gemma.calls[0]["temperature"] == 0.9


@pytest.mark.parametrize("words", [19, 81])
def test_scene_word_bounds_fail_twice(words):
    bad = reply(scene=" ".join(["w"] * words))
    with pytest.raises(SeriesError) as info:
        plan_shot(FakeGemma(bad, bad), settings(), 2, [])
    assert info.value.exit_code == 1
    assert "shot 2 of 3" in str(info.value)


@pytest.mark.parametrize("words", [20, 80])
def test_scene_word_edges_ok(words):
    shot = plan_shot(FakeGemma(reply(scene=" ".join(["w"] * words))), settings(), 1, [])
    assert len(shot.scene.split()) == words


def test_retry_once_with_error_appended():
    gemma = FakeGemma("not json", reply("Good"))
    shot = plan_shot(gemma, settings(), 1, [])
    assert shot.title == "Good" and len(gemma.calls) == 2
    assert "not json" in gemma.calls[1]["request"]
    assert "Validation error" in gemma.calls[1]["request"]


def test_fenced_answer_is_parsed():
    shot = plan_shot(FakeGemma(f"```json\n{reply('Fenced')}\n```"), settings(), 1, [])
    assert shot.title == "Fenced"


def test_missing_title_is_invalid():
    bad = json.dumps({"scene": SCENE})
    with pytest.raises(SeriesError):
        plan_shot(FakeGemma(bad, bad), settings(), 1, [])


def test_exactly_n_calls_each_timed():
    gemma = FakeGemma(*[reply(f"T{i}") for i in range(3)])
    shots = list(plan_shots(gemma, settings(3)))
    assert [s.title for s in shots] == ["T0", "T1", "T2"]
    assert len(gemma.calls) == 3
    assert all(s.plan_seconds >= 0 for s in shots)


def test_failure_keeps_earlier_shots():
    bad = "nope"
    gemma = FakeGemma(reply("T0"), bad, bad)
    got = []
    with pytest.raises(SeriesError):
        for shot in plan_shots(gemma, settings(3)):
            got.append(shot)
    assert [s.title for s in got] == ["T0"]


def test_shot_prompt_pins_key_rules():
    text = prompts.SHOT_SYSTEM.lower()
    for word in ("location", "action", "pose", "framing", "angle", "light"):
        assert word in text
    assert "20 to 80 words" in text
    assert "do not describe the character's appearance or the style" in text
    assert "do not repeat a location or a pose" in text

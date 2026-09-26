"""Story 09.1-003: deterministic prompt composition."""

from lig.series.compose import compose_prompt, with_prompt
from lig.series.settings import SeriesSettings
from lig.series.shots import Shot

LOOK = " ".join(["woman"] + ["word"] * 29)
SCENE = " ".join(["scene"] * 25)


def settings() -> SeriesSettings:
    return SeriesSettings.model_validate(
        {
            "count": 2,
            "character": {"name": "Camille", "look": LOOK},
            "style": "black and white, grainy",
            "setting": "Paris",
            "arc": "Morning to midnight.",
        }
    )


def test_prompt_is_look_scene_style():
    assert compose_prompt(settings(), "A cafe.") == f"{LOOK} A cafe. Style: black and white, grainy"


def test_look_and_style_identical_across_shots():
    prompts = [compose_prompt(settings(), s) for s in ("One.", "Two.")]
    for prompt in prompts:
        assert prompt.startswith(LOOK)
        assert prompt.endswith("Style: black and white, grainy")


def test_prefix_and_suffix_added_unchanged():
    prompt = compose_prompt(settings(), "A cafe.", prefix="35mm photo,", suffix="f/1.8")
    assert prompt == f"35mm photo, {LOOK} A cafe. Style: black and white, grainy f/1.8"


def test_blank_prefix_suffix_ignored():
    assert compose_prompt(settings(), "A cafe.", prefix="", suffix=None) == compose_prompt(
        settings(), "A cafe."
    )


def test_with_prompt_stores_prompt_on_shot_and_round_trips():
    shot = with_prompt(Shot(title="T", scene=SCENE), settings(), prefix="35mm photo,")
    assert shot.prompt == compose_prompt(settings(), SCENE, prefix="35mm photo,")
    assert Shot.model_validate_json(shot.model_dump_json()).prompt == shot.prompt

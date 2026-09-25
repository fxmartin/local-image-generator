from pathlib import Path

import pytest
from pydantic import ValidationError

from lig.core.models import EditRequest, GenerateRequest, ImageResult, Timings, WeightsUsed


def test_defaults():
    req = GenerateRequest(prompt="a cat")
    assert (req.width, req.height, req.steps) == (1024, 1024, 40)
    assert req.guidance is None
    assert req.negative_prompt is None
    assert req.transparent is False


@pytest.mark.parametrize(
    ("width", "nearest"),
    [(1000, 992), (1010, 1024), (100, 256), (5000, 4096), (300, 288), (4100, 4096)],
)
def test_invalid_size_names_nearest(width, nearest):
    with pytest.raises(ValidationError, match=f"nearest valid size is {nearest}"):
        GenerateRequest(prompt="x", width=width)


def test_invalid_height_names_nearest():
    with pytest.raises(ValidationError, match="height.*nearest valid size is 512"):
        GenerateRequest(prompt="x", height=500)


@pytest.mark.parametrize("size", [256, 512, 1024, 4096])
def test_valid_sizes(size):
    req = GenerateRequest(prompt="x", width=size, height=size)
    assert req.width == size


def test_seed_random_and_recorded():
    seeds = {GenerateRequest(prompt="x").seed for _ in range(20)}
    assert len(seeds) > 1
    assert all(0 <= s < 2**32 for s in seeds)


def test_explicit_seed_kept_and_bounded():
    assert GenerateRequest(prompt="x", seed=0).seed == 0
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="x", seed=2**32)
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="x", seed=-1)


def test_prompt_and_steps_validated():
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="")
    with pytest.raises(ValidationError):
        GenerateRequest(prompt="x", steps=0)


def test_edit_request_inherits_and_carries_reference():
    req = EditRequest(prompt="x", reference_image=Path("a.png"), reference_sha256="ab" * 32)
    assert isinstance(req, GenerateRequest)
    assert req.strength is None
    assert req.width == 1024
    assert req.seed is not None
    with pytest.raises(ValidationError, match="nearest valid size"):
        EditRequest(
            prompt="x", reference_image=Path("a.png"), reference_sha256="ab" * 32, width=1000
        )


def test_edit_request_strength_and_sha_validated():
    ok = {"prompt": "x", "reference_image": Path("a.png"), "reference_sha256": "ab" * 32}
    assert EditRequest(**ok, strength=0.5).strength == 0.5
    with pytest.raises(ValidationError):
        EditRequest(**ok, strength=1.5)
    with pytest.raises(ValidationError):
        EditRequest(**{**ok, "reference_sha256": "nothex"})


def test_image_result_holds_everything():
    req = GenerateRequest(prompt="x")
    res = ImageResult(
        png=b"\x89PNG",
        request=req,
        engine="sdcpp",
        engine_version="1.0",
        weights=[WeightsUsed(name="qwen-q4", sha256="cd" * 32)],
        timings=Timings(load_s=1.0, per_step_s=0.5, total_s=21.0),
        host="xps13",
    )
    assert res.request.seed == req.seed
    assert res.weights[0].name == "qwen-q4"
    assert res.timings.total_s == 21.0
    assert res.host == "xps13"

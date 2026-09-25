import io
import json
from datetime import datetime
from pathlib import Path

from PIL import Image

from lig import __version__
from lig.core.models import EditRequest, GenerateRequest, ImageResult, Timings, WeightsUsed
from lig.core.output import DEFAULT_OUTPUT_DIR, SidecarSchema, slugify, write_result

NOW = datetime(2026, 9, 25, 13, 4, 5)


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buf, "PNG")
    return buf.getvalue()


def _result(request=None) -> ImageResult:
    return ImageResult(
        png=_png(),
        request=request or GenerateRequest(prompt="A Cat, on a Mat!", seed=7, guidance=6.0),
        engine="fake",
        engine_version="1.2",
        weights=[WeightsUsed(name="w.gguf", sha256="ab" * 32)],
        timings=Timings(load_s=1.0, per_step_s=0.5, total_s=21.0),
        host="xps",
    )


def test_slugify_ascii_lower_bounded():
    assert slugify("A Cat, on a Mat!") == "a-cat-on-a-mat"
    assert slugify("Café ñandú 日本") == "cafe-nandu"
    assert len(slugify("x" * 100)) == 40
    assert not slugify("word " * 20).endswith("-")
    assert slugify("!!!") == "image"


def test_default_dir_is_outputs():
    assert DEFAULT_OUTPUT_DIR == Path("outputs")


def test_write_creates_dir_and_names(tmp_path):
    out = tmp_path / "new" / "dir"
    path = write_result(_result(), out, now=NOW)
    assert path == out / "20260925-130405_a-cat-on-a-mat_s7.png"
    assert path.exists()
    assert path.with_suffix(".json").exists()


def test_collisions_get_numeric_suffix(tmp_path):
    first = write_result(_result(), tmp_path, now=NOW)
    second = write_result(_result(), tmp_path, now=NOW)
    third = write_result(_result(), tmp_path, now=NOW)
    assert second.name == first.stem + "-2.png"
    assert third.name == first.stem + "-3.png"
    assert second.with_suffix(".json").exists()


def test_sidecar_validates(tmp_path):
    path = write_result(_result(), tmp_path, now=NOW)
    side = SidecarSchema.model_validate_json(path.with_suffix(".json").read_text())
    assert side.prompt == "A Cat, on a Mat!"
    assert side.seed == 7 and side.steps == 40 and side.size == (1024, 1024)
    assert side.guidance == 6.0 and side.negative_prompt is None
    assert side.engine == "fake" and side.engine_version == "1.2"
    assert side.weights[0].sha256 == "ab" * 32
    assert side.timings.total_s == 21.0
    assert side.host == "xps" and side.lig_version == __version__
    assert side.created_at == NOW.isoformat()
    assert side.source_path is None and side.source_sha256 is None


def test_edit_sidecar_has_source(tmp_path):
    req = EditRequest(prompt="x", reference_image=Path("in.png"), reference_sha256="c" * 64)
    path = write_result(_result(req), tmp_path, now=NOW)
    side = SidecarSchema.model_validate_json(path.with_suffix(".json").read_text())
    assert side.source_path == "in.png" and side.source_sha256 == "c" * 64


def test_png_text_chunks_match_sidecar(tmp_path):
    path = write_result(_result(), tmp_path, now=NOW)
    side = json.loads(path.with_suffix(".json").read_text())
    with Image.open(path) as img:
        text = img.text
    assert text["lig:prompt"] == side["prompt"]
    assert text["lig:seed"] == str(side["seed"])
    assert text["lig:engine"] == side["engine"]
    assert text["lig:sidecar"] == path.with_suffix(".json").name


def test_atomic_write_leaves_no_temp(tmp_path):
    write_result(_result(), tmp_path, now=NOW)
    assert sorted(p.suffix for p in tmp_path.iterdir()) == [".json", ".png"]


def test_failed_write_leaves_nothing(tmp_path):
    bad = _result().model_copy(update={"png": b"not a png"})
    try:
        write_result(bad, tmp_path, now=NOW)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert list(tmp_path.iterdir()) == []

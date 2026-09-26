"""Story 09.3-003: saved characters are reused across series (data dir is a temp dir)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from lig.series import characters
from lig.series.cli import app
from lig.series.settings import Character, SeriesError, plan_settings

runner = CliRunner()
LOOK = " ".join(["woman"] + ["word"] * 29)
SAVED_LOOK = " ".join(["saved"] * 30)
SCENE = " ".join(["scene"] * 25)
GLOBAL = {
    "count": 1,
    "character": {"name": "Camille", "look": LOOK},
    "style": "black and white",
    "setting": "Paris",
    "arc": "Morning to midnight.",
}


def _gemma(tmp_path: Path) -> Path:
    script = tmp_path / "gemma-multi"
    log = tmp_path / "global-messages.txt"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "system = sys.argv[sys.argv.index('--system') + 1]\n"
        "message = sys.stdin.read()\n"
        f"glob = {json.dumps(json.dumps(GLOBAL))}\n"
        f"shot = {json.dumps(json.dumps({'title': 'Lamp', 'scene': SCENE}))}\n"
        "if 'plan a series' in system:\n"
        f"    open({str(log)!r}, 'a').write(message + '\\n---\\n')\n"
        "print(glob if 'plan a series' in system else shot)\n"
    )
    script.chmod(0o755)
    return script


def _run(tmp_path: Path, *extra: str, name: str = "out"):
    return runner.invoke(
        app,
        ["Create 1 photo of a woman", "--engine", "fake", "--gemma", str(_gemma(tmp_path)),
         "--out", str(tmp_path / name), "--size", "256x256", "--steps", "1", *extra],
    )  # fmt: skip


def test_data_dir_is_the_temp_dir(tmp_path):
    assert characters.characters_dir() == tmp_path / "xdg-data" / "lig" / "characters"


def test_first_run_saves_character(tmp_path):
    result = _run(tmp_path, "--character", "Elara", "--seed", "11")
    assert result.exit_code == 0, result.output
    folder = characters.characters_dir() / "elara"
    data = json.loads((folder / "character.json").read_text())
    assert data == {
        "name": "Camille",
        "look": LOOK,
        "style": "black and white",
        "seed": 11,
        "source_series": str(tmp_path / "out"),
    }
    assert not (folder / "reference.png").exists()


def test_second_run_reuses_look_name_and_seed(tmp_path):
    characters.save(
        "elara", Character(name="Elara", look=SAVED_LOOK), style="s", seed=77, source_series="x"
    )
    result = _run(tmp_path, "--character", "elara", name="second")
    assert result.exit_code == 0, result.output
    manifest = json.loads((tmp_path / "second" / "series.json").read_text())
    assert manifest["seed"] == 77
    assert manifest["plan"]["character"] == {"name": "Elara", "look": SAVED_LOOK}
    assert SAVED_LOOK in (tmp_path / "global-messages.txt").read_text()
    # An existing character is never overwritten.
    assert characters.load("elara").look == SAVED_LOOK


def test_seed_flag_beats_saved_seed(tmp_path):
    characters.save(
        "elara", Character(name="Elara", look=SAVED_LOOK), style="s", seed=77, source_series="x"
    )
    assert _run(tmp_path, "--character", "elara", "--seed", "5").exit_code == 0
    assert json.loads((tmp_path / "out" / "series.json").read_text())["seed"] == 5


def test_failed_series_does_not_save(tmp_path):
    result = runner.invoke(
        app,
        [
            "x",
            "--character",
            "elara",
            "--gemma",
            str(tmp_path / "nope"),
            "--out",
            str(tmp_path / "o"),
        ],
    )
    assert result.exit_code == 4
    assert characters.list_names() == []


def test_plan_settings_replaces_the_models_look():
    class Client:
        def complete(self, system, request, *, temperature, max_tokens):
            return json.dumps(GLOBAL)

    saved = Character(name="Elara", look=SAVED_LOOK)
    settings = plan_settings(Client(), "photos", count=1, character=saved)
    assert settings.character == saved


def test_reference_is_saved_and_shown(tmp_path):
    ref = tmp_path / "ref.png"
    ref.write_bytes(b"png")
    characters.save(
        "elara", Character(name="E", look=SAVED_LOOK), style="s", seed=1, source_series="x",
        reference=ref,
    )  # fmt: skip
    assert characters.reference_path("elara").read_bytes() == b"png"
    assert "reference:" in runner.invoke(app, ["characters", "show", "elara"]).output


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden", "a b"])
def test_bad_names_rejected(bad):
    with pytest.raises(SeriesError):
        characters.normalize(bad)


def test_list_show_rm(tmp_path):
    assert runner.invoke(app, ["characters", "list"]).output == ""
    for name in ("bob", "alice"):
        characters.save(
            name, Character(name=name, look=SAVED_LOOK), style="s", seed=1, source_series="x"
        )
    assert runner.invoke(app, ["characters", "list"]).output.split() == ["alice", "bob"]
    shown = runner.invoke(app, ["characters", "show", "alice"])
    assert shown.exit_code == 0 and SAVED_LOOK in shown.output

    declined = runner.invoke(app, ["characters", "rm", "alice"], input="n\n")
    assert declined.exit_code != 0 and characters.load("alice") is not None
    assert runner.invoke(app, ["characters", "rm", "alice"], input="y\n").exit_code == 0
    assert characters.load("alice") is None
    assert runner.invoke(app, ["characters", "rm", "bob", "--yes"]).exit_code == 0
    assert characters.list_names() == []


def test_show_and_rm_unknown_exit_1():
    assert runner.invoke(app, ["characters", "show", "nobody"]).exit_code == 1
    assert runner.invoke(app, ["characters", "rm", "nobody", "--yes"]).exit_code == 1


def test_corrupt_character_file_is_an_error():
    folder = characters.characters_dir() / "bad"
    folder.mkdir(parents=True)
    (folder / "character.json").write_text("{nope")
    assert runner.invoke(app, ["characters", "show", "bad"]).exit_code == 1
    assert runner.invoke(app, ["characters", "rm", "bad", "--yes"]).exit_code == 1


def test_top_level_help_is_the_run_help_and_points_at_characters():
    help_text = runner.invoke(app, ["--help"], terminal_width=200).output
    assert "--character" in help_text
    assert "lig-series characters" in help_text


def test_options_before_the_request_still_run(tmp_path):
    result = runner.invoke(app, ["--count", "1", "--gemma", "/nonexistent/gemma", "a woman"])
    assert "No such option" not in result.output
    assert result.exit_code != 0

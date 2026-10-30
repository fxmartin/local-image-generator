"""The API key lig sends to an OpenAI-compatible LLM gateway (larm on the M3 Max)."""

from lig.core import llm_key


def test_key_file_lives_in_the_lig_config_dir(tmp_path):
    assert llm_key.key_path() == tmp_path / "xdg-config" / "lig" / "llm.key"


def test_no_env_and_no_file_means_no_key():
    assert llm_key.read_api_key() is None


def test_file_key_is_stripped(tmp_path):
    path = llm_key.key_path()
    path.parent.mkdir(parents=True)
    path.write_text("  sk-file\n")
    assert llm_key.read_api_key() == "sk-file"


def test_env_beats_file(monkeypatch):
    path = llm_key.key_path()
    path.parent.mkdir(parents=True)
    path.write_text("sk-file")
    monkeypatch.setenv(llm_key.KEY_ENV, " sk-env ")
    assert llm_key.read_api_key() == "sk-env"


def test_blank_env_and_empty_file_mean_no_key(monkeypatch):
    path = llm_key.key_path()
    path.parent.mkdir(parents=True)
    path.write_text("\n")
    monkeypatch.setenv(llm_key.KEY_ENV, "  ")
    assert llm_key.read_api_key() is None


def test_unreadable_key_file_means_no_key(monkeypatch):
    # A directory where the file should be: reading fails like a permission error would.
    llm_key.key_path().mkdir(parents=True)
    assert llm_key.read_api_key() is None

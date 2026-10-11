"""Story 08.1-001: the prompt rewriter (MockTransport endpoint) and `generate --rewrite`."""

import json

import httpx
import pytest
from typer.testing import CliRunner

from lig.cli import generate as generate_cmd
from lig.cli.app import app
from lig.core import config as cfg
from lig.core import rewriter

runner = CliRunner()
ENDPOINT = "http://llm.test/v1"
EXPANDED = "A weathered lighthouse at dusk, warm rim light, long shadows, 35mm photograph"


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _chat_reply(content: str):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    return handler


# --- core.rewriter -----------------------------------------------------------------------------


def test_rewrite_posts_chat_completion_and_returns_text():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_reply(f"  {EXPANDED}\n")(request)

    out = rewriter.rewrite_prompt("a lighthouse", ENDPOINT, "qwen-rw", client=_client(handler))

    assert out == EXPANDED
    assert str(seen[0].url) == f"{ENDPOINT}/chat/completions"
    body = json.loads(seen[0].content)
    assert body["model"] == "qwen-rw"
    assert body["messages"][0] == {"role": "system", "content": rewriter.SYSTEM_PROMPT}
    assert body["messages"][1] == {"role": "user", "content": "a lighthouse"}


def test_rewrite_accepts_a_full_chat_completions_url():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return _chat_reply("x y")(request)

    rewriter.rewrite_prompt("p", f"{ENDPOINT}/chat/completions", "m", client=_client(handler))
    assert str(seen[0].url) == f"{ENDPOINT}/chat/completions"


def test_rewrite_strips_think_blocks_and_wrapping_quotes():
    reply = f'<think>plan it out</think>\n"{EXPANDED}"'
    assert (
        rewriter.rewrite_prompt("p", ENDPOINT, "m", client=_client(_chat_reply(reply))) == EXPANDED
    )


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500, text="boom"),
        lambda r: httpx.Response(200, text="not json"),
        lambda r: httpx.Response(200, json={"choices": []}),
        _chat_reply("   "),
        _chat_reply("<think>only thoughts</think>"),
    ],
    ids=["http-500", "not-json", "no-choices", "blank", "only-think"],
)
def test_rewrite_bad_answers_raise_rewriter_error(handler):
    with pytest.raises(rewriter.RewriterError):
        rewriter.rewrite_prompt("p", ENDPOINT, "m", client=_client(handler))


def test_rewrite_unreachable_endpoint_raises_rewriter_error_naming_it():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(rewriter.RewriterError, match="llm.test"):
        rewriter.rewrite_prompt("p", ENDPOINT, "m", client=_client(handler))


def test_load_prompt_file_prefers_prompt_and_carries_original(tmp_path):
    sidecar = tmp_path / "a.json"
    sidecar.write_text(json.dumps({"prompt": EXPANDED, "original_prompt": "a lighthouse"}))
    assert rewriter.load_prompt_file(sidecar) == rewriter.PromptSource(EXPANDED, "a lighthouse")

    plain = tmp_path / "b.json"
    plain.write_text(json.dumps({"prompt": "just this"}))
    assert rewriter.load_prompt_file(plain) == rewriter.PromptSource("just this", None)


@pytest.mark.parametrize("content", ["not json", "[]", '{"prompt": 3}', '{"prompt": "  "}', "{}"])
def test_load_prompt_file_rejects_unusable_files(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(rewriter.RewriterError):
        rewriter.load_prompt_file(path)


def test_load_prompt_file_missing_file(tmp_path):
    with pytest.raises(rewriter.RewriterError, match="nope.json"):
        rewriter.load_prompt_file(tmp_path / "nope.json")


# --- config ------------------------------------------------------------------------------------


def test_rewriter_settings_default_to_unset_and_load_from_file(tmp_path):
    assert cfg.Settings().rewriter.endpoint is None
    path = tmp_path / "config.toml"
    path.write_text(f'[rewriter]\nendpoint = "{ENDPOINT}"\nmodel = "qwen-rw"\n')
    resolved = cfg.load_settings(path=path, env={})
    assert resolved.settings.rewriter.endpoint == ENDPOINT
    assert resolved.settings.rewriter.model == "qwen-rw"
    assert resolved.provenance["rewriter.model"] == "file"
    assert not resolved.warnings


def test_rewriter_endpoint_must_be_http_url():
    with pytest.raises(ValueError):
        cfg.Settings(rewriter={"endpoint": "llm.test/v1"})


# --- CLI ---------------------------------------------------------------------------------------


@pytest.fixture
def cli_env(tmp_path, monkeypatch):
    config_dir = tmp_path / "cfg" / "lig"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        f'[rewriter]\nendpoint = "{ENDPOINT}"\nmodel = "qwen-rw"\n'
    )
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    for key in ("LIG_ENGINE", "LIG_SIZE", "LIG_STEPS", "LIG_OUTPUT_DIR"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _patch_rewriter(monkeypatch, handler):
    real = rewriter.rewrite_prompt
    monkeypatch.setattr(
        generate_cmd.rewriter,
        "rewrite_prompt",
        lambda prompt, endpoint, model, client=None: real(
            prompt, endpoint, model, client=_client(handler)
        ),
    )


def _sidecar(root):
    (path,) = (root / "outputs").glob("*.json")
    return json.loads(path.read_text())


def test_rewrite_shows_expansion_uses_it_and_records_both_prompts(cli_env, monkeypatch):
    _patch_rewriter(monkeypatch, _chat_reply(EXPANDED))
    result = runner.invoke(app, ["generate", "a lighthouse", "--engine", "fake", "--rewrite"])

    assert result.exit_code == 0, result.output
    assert EXPANDED in result.output
    assert result.output.index(EXPANDED) < result.output.index(".png")
    sidecar = _sidecar(cli_env)
    assert sidecar["prompt"] == EXPANDED
    assert sidecar["original_prompt"] == "a lighthouse"


def test_rewrite_json_keeps_stdout_a_single_document(cli_env, monkeypatch):
    _patch_rewriter(monkeypatch, _chat_reply(EXPANDED))
    result = runner.invoke(
        app, ["generate", "a lighthouse", "--engine", "fake", "--rewrite", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["original_prompt"] == "a lighthouse"


def test_without_rewrite_the_sidecar_has_no_original_prompt(cli_env, monkeypatch):
    _patch_rewriter(monkeypatch, lambda r: pytest.fail("rewriter must not be called"))
    result = runner.invoke(app, ["generate", "a lighthouse", "--engine", "fake"])
    assert result.exit_code == 0, result.output
    assert _sidecar(cli_env)["original_prompt"] is None


def test_rewrite_without_config_is_a_usage_error(cli_env, monkeypatch):
    (cli_env / "cfg" / "lig" / "config.toml").write_text("")
    result = runner.invoke(app, ["generate", "x", "--engine", "fake", "--rewrite"])
    assert result.exit_code == 2
    assert "rewriter.endpoint" in result.output and "rewriter.model" in result.output


def _down(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("refused", request=request)


def test_unreachable_endpoint_non_interactive_continues_with_a_warning(cli_env, monkeypatch):
    _patch_rewriter(monkeypatch, _down)
    result = runner.invoke(app, ["generate", "a lighthouse", "--engine", "fake", "--rewrite"])
    assert result.exit_code == 0, result.output
    assert "warning" in result.output and "original prompt" in result.output
    sidecar = _sidecar(cli_env)
    assert sidecar["prompt"] == "a lighthouse"
    assert sidecar["original_prompt"] is None


def test_unreachable_endpoint_interactive_asks_and_can_decline(cli_env, monkeypatch):
    _patch_rewriter(monkeypatch, _down)
    monkeypatch.setattr(generate_cmd, "stdin_is_interactive", lambda: True)
    result = runner.invoke(
        app, ["generate", "a lighthouse", "--engine", "fake", "--rewrite"], input="n\n"
    )
    assert result.exit_code == 1
    assert not list((cli_env / "outputs").glob("*.png"))


def test_unreachable_endpoint_interactive_can_accept(cli_env, monkeypatch):
    _patch_rewriter(monkeypatch, _down)
    monkeypatch.setattr(generate_cmd, "stdin_is_interactive", lambda: True)
    result = runner.invoke(
        app, ["generate", "a lighthouse", "--engine", "fake", "--rewrite"], input="y\n"
    )
    assert result.exit_code == 0, result.output
    assert _sidecar(cli_env)["prompt"] == "a lighthouse"


def test_prompt_from_uses_the_sidecar_prompt_without_calling_the_rewriter(cli_env, monkeypatch):
    saved = cli_env / "saved.json"
    saved.write_text(json.dumps({"prompt": EXPANDED, "original_prompt": "a lighthouse"}))
    _patch_rewriter(monkeypatch, lambda r: pytest.fail("rewriter must not be called"))

    result = runner.invoke(app, ["generate", "--prompt-from", str(saved), "--engine", "fake"])

    assert result.exit_code == 0, result.output
    sidecar = _sidecar(cli_env)
    assert sidecar["prompt"] == EXPANDED
    assert sidecar["original_prompt"] == "a lighthouse"


@pytest.mark.parametrize(
    "args",
    [
        ["generate", "--engine", "fake"],
        ["generate", "x", "--prompt-from", "saved.json", "--engine", "fake"],
        ["generate", "--prompt-from", "saved.json", "--rewrite", "--engine", "fake"],
        ["generate", "--prompt-from", "missing.json", "--engine", "fake"],
    ],
    ids=["no-prompt", "prompt-and-file", "file-and-rewrite", "missing-file"],
)
def test_prompt_source_conflicts_are_usage_errors(cli_env, args):
    (cli_env / "saved.json").write_text(json.dumps({"prompt": "p"}))
    result = runner.invoke(app, args)
    assert result.exit_code == 2, result.output

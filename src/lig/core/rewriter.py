"""Optional prompt rewriter: expand a short prompt through an OpenAI-compatible chat endpoint."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from lig.backends.remote import CONNECT_TIMEOUT_S

# A local LLM may be cold-loading, so reading gets far longer than connecting.
REWRITE_TIMEOUT_S = 120.0
TEMPERATURE = 0.7
MAX_TOKENS = 1024
CHAT_PATH = "/chat/completions"

# Modelled on the guidance of Qwen-Image's published prompt rewriter (keep the intent, spell out
# subject, style, composition and light, keep quoted text verbatim); written fresh rather than
# copied so its licence does not carry over.
SYSTEM_PROMPT = """\
You rewrite short user ideas into rich prompts for a text-to-image model (Qwen-Image).

Rules:
- Keep the user's intent, subjects and any explicit constraints; never add unrelated subjects.
- Expand with concrete visual detail: the subject, setting, style or medium, composition and \
camera angle, lighting, colour palette and mood.
- Text the image must show (signs, labels, captions) stays verbatim, in quotes, in its original \
language.
- Write one paragraph of plain descriptive prose, in the language of the user's prompt, at most \
200 words.
- Reply with the rewritten prompt only: no preface, no explanation, no markdown, no quotation \
marks around it.
"""

_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)
_QUOTE_PAIRS = ('""', "''", "“”")


class RewriterError(Exception):
    """The rewriter or a saved prompt file could not be used."""


@dataclass(frozen=True)
class PromptSource:
    """A prompt read back from a sidecar; `original` is set if it was itself a rewrite."""

    prompt: str
    original: str | None


def make_client() -> httpx.Client:
    return httpx.Client(timeout=httpx.Timeout(REWRITE_TIMEOUT_S, connect=CONNECT_TIMEOUT_S))


def _chat_url(endpoint: str) -> str:
    endpoint = endpoint.rstrip("/")
    return endpoint if endpoint.endswith(CHAT_PATH) else endpoint + CHAT_PATH


def _clean(text: str) -> str:
    text = _THINK_BLOCK.sub("", text).strip()
    if len(text) > 1 and text[0] + text[-1] in _QUOTE_PAIRS:
        text = text[1:-1].strip()
    return text


def rewrite_prompt(
    prompt: str, endpoint: str, model: str, client: httpx.Client | None = None
) -> str:
    """Return the expanded prompt; any failure to get a usable answer raises RewriterError."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "temperature": TEMPERATURE,
        "max_tokens": MAX_TOKENS,
        "stream": False,
    }
    url = _chat_url(endpoint)
    owns_client = client is None
    client = client or make_client()
    try:
        response = client.post(url, json=payload)
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
    except httpx.HTTPError as exc:
        raise RewriterError(f"cannot reach the rewriter at {url}: {exc}") from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise RewriterError(f"the rewriter at {url} sent an unusable answer: {exc!r}") from exc
    finally:
        if owns_client:
            client.close()
    expanded = _clean(content) if isinstance(content, str) else ""
    if not expanded:
        raise RewriterError(f"the rewriter at {url} returned an empty prompt")
    return expanded


def load_prompt_file(path: Path) -> PromptSource:
    """Read the prompt to reuse from a sidecar: `prompt` is the one that was actually rendered."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as exc:
        raise RewriterError(f"cannot read {path}: {exc}") from exc
    except ValueError as exc:
        raise RewriterError(f"{path} is not valid JSON: {exc}") from exc
    prompt = data.get("prompt") if isinstance(data, dict) else None
    if not isinstance(prompt, str) or not prompt.strip():
        raise RewriterError(f"{path} has no usable 'prompt'; expected a lig sidecar")
    original = data.get("original_prompt")
    return PromptSource(prompt, original if isinstance(original, str) else None)

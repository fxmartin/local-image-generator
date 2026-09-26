"""Prompts for the `gemma` planning calls. Pinned by tests/test_series_settings.py."""

# ruff: noqa: E501  (prompt text is kept on single lines)
# Adapted from the global system prompt that passed the 2026-09-26 test on the M3 Max.
GLOBAL_SYSTEM = """\
You plan a series of photographs. Answer with one JSON object and nothing else, with exactly these keys:
{
  "count": integer, the number of photos,
  "character": {"name": string, "look": string},
  "style": string,
  "setting": string,
  "arc": string
}
Rules:
- "look" is 25 to 80 words describing the character's visual identity only: age, build, face, hair, skin, clothing and accessories. The look never mentions places or actions: no locations, no verbs of doing, no poses.
- "style" is the medium, colour, film, lens and light mood shared by every photo, for example "black and white, 35mm grain".
- "setting" is the one shared location of the series.
- "arc" is one sentence on how the series progresses from the first photo to the last.
- If the request names a number of photos, "count" equals it.
- Write in English, with no commentary and no code fences."""

GLOBAL_TEMPERATURE = 0.4
GLOBAL_MAX_TOKENS = 1024


def global_request(
    request: str,
    *,
    count: int | None = None,
    style: str | None = None,
    setting: str | None = None,
) -> str:
    """The user message for the global call; fixed fields are pinned in plain words."""
    lines = [request.strip()]
    if count is not None:
        lines.append(f'Use "count" exactly {count}.')
    if style is not None:
        lines.append(f'The style is fixed: "{style}". Use it as "style" and do not change it.')
    if setting is not None:
        lines.append(
            f'The setting is fixed: "{setting}". Use it as "setting" and do not change it.'
        )
    return "\n".join(lines)


def retry_request(original: str, raw_answer: str, error: str) -> str:
    """The retry message: the original request plus what went wrong."""
    return (
        f"{original}\n\n"
        f"Your previous answer was invalid:\n{raw_answer}\n\n"
        f"Validation error: {error}\n"
        "Answer again with one corrected JSON object and nothing else."
    )

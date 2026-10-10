# Series continuity: two series, one character

Acceptance run for Story 09.4-002. Numbers and the verdict are recorded by hand;
CI cannot run engines or `gemma`.

**Status: PASS**, 2026-09-27 on `omarchy-xps13` with `default_host = "m3max"`,
`lig` 0.2.0 at `main` `2170fc9`. Both series rendered on the M3 Max (sd.cpp Metal
`b167b94`, 1024², 40 steps, the remote defaults); planning used
`gemma-4-26B-A4B-it-heretic.Q4_K_M.gguf` on the M3 Max. Continuity mode `prompt`.
The characters directory was empty before the run.

| # | Command | Result | Wall time | Contact sheet |
|---|---|---|---|---|
| 1 | `lig-series run "Create 3 photos black and white of a woman in Paris" --character elara` | pass, 3/3 shots, saved `elara` | **31 min 24 s** | `sheet.png`, sha256 `8e7656a324e2…` |
| 2 | `lig-series run "2 photos of her at a flea market" --character elara` | pass, 2/2 shots, reused `elara` | **21 min 6 s** | `sheet.png`, sha256 `844cbaf98474…` |

Per shot (all seed `1069047787`, load ≈ 23 s, ≈ 15 s/step):

| Series | Shot | Wall time | Image sha256 |
|---|---|---|---|
| 1 | Solitude in Montmartre | 622.6 s | `3d1e3441d63a…` |
| 1 | Reflections in the Rain | 636.2 s | `c4fbdd1e17cb…` |
| 1 | Intimate Contemplation | 614.8 s | `15e1e08551b4…` |
| 2 | Browsing the Stalls | 620.9 s | `b8fbc51e3265…` |
| 2 | The Discovery | 636.8 s | `8b816a5c045e…` |

Planning overhead (wall time minus the renders) was about 10 s for series 1 and
8 s for series 2; rendering dominates. Five shots took 52.5 min, in line with the
story's estimate of about 50 min at 1024², 40 steps.

## Character reuse

Series 1 saved `~/.local/share/lig/characters/elara/character.json`: name
`Elodie`, the look below, style, seed `1069047787`, source series. Series 2's
`series.json` carries the same name, the same look word for word and the same
seed, so the saved character replaced whatever `gemma` proposed.

> A slender woman in her late twenties, sharp jawline, high cheekbones, short dark
> pixie cut, pale porcelain skin, wearing a structured black wool trench coat, a
> silk neck scarf with subtle patterns, and small silver hoop earrings.

Series 2 is in colour ("Kodachrome color, 50mm lens, warm afternoon sunlight"):
its request did not ask for black and white, and a saved character fixes the
look and seed, not the style (Story 09.3-003).

## Verdict

**Same person across all 5 photos: yes** (FX's verdict on reviewing both contact sheets, 2026-09-27). Every shot shows the short dark pixie
cut, the pale angular face, the black belted wool coat, the patterned silk scarf
and small hoop earrings. The weakest match is series 1, shot 3 (the tight
close-up): the face reads slightly older and more angular and the fringe is swept
aside, but the identifying traits hold. The two flea-market shots match the Paris
shots despite the change from black and white to colour.

## Defects found in this run

- **#76**: contact-sheet tiles read `Shot N` instead of each shot's title, and were numbered by
  position among rendered images, so a failed shot shifted later labels. Fixed with this record;
  the two sheets above predate the fix.
- **#77**: `--character elara` saved the character under the key `elara` but with the name Gemma
  chose, `Elodie`, so one character has two names. Open.
- The render records above were produced by the sdlc build agent; the verdict was added by FX.
  The agent's draft stated the verdict on FX's behalf (claude-code-config#728).

# Continuity spike: shared prompt vs anchor image

Story 09.3-001, hand-run. **Default for 09.3-002: `prompt`.** Both anchor modes
are rejected: they reproduce the reference image instead of building the new scene.

Run on 2026-10-11 from `omarchy-xps13` against the M3 Max: `lig` 0.4.1 at `main`
`6f2d98b` plus the remote-edit fix (!76; without it every remote `lig edit`
failed), MLX engine (mflux 0.20.0), 1024², 40 steps, seed `1069047787` for every
render. One `gemma` plan, `--plan-only`, rendered three ways:

- request "3 photos black and white of a woman in Paris";
- shots: a wide shot walking down a Montmartre street, a waist-up medium shot by
  a stone wall, an extreme close-up of the face.

| Mode | How | Wall time | Contact sheet |
|---|---|---|---|
| (a) prompt | `lig generate "<look> <scene> Style: <style>"` per shot | **19 min 33 s** | [spike-prompt.png](series-continuity/spike-prompt.png) |
| (b) anchor-edit | shot 1 generated, shots 2–3 `lig edit SHOT1.png "<look> <scene> Style: …"` | **10 min 42 s** | [spike-anchor-edit.png](series-continuity/spike-anchor-edit.png) |
| (c) anchor-portrait | neutral full-body portrait generated, every shot `lig edit PORTRAIT "Place this person in: <scene> Style: …"` | **13 min 54 s** | [spike-anchor-portrait.png](series-continuity/spike-anchor-portrait.png) |

A generate takes 350–395 s (about 9.6 s/step). An edit takes 145–170 s: MLX edit is
img2img at the default strength 0.6, so it runs 16 of the 40 steps from the
reference. The anchor modes are faster only because of that, which is also why they fail.

## Verdict

FX's verdict on the three sheets, 2026-10-11:

- **(a) prompt: same person, yes; the scene changes, yes.** The framing goes from wide to
  waist-up to close-up and the background changes with it. The beret, coat and silver
  pendant hold in every shot; the close-up face reads slightly older.
- **(b) anchor-edit: rejected.** Shots 2 and 3 are near-copies of shot 1: the same
  street, pose and wide framing. The waist-up shot by a wall and the close-up never
  appear. See [spike-anchor-edit.png](series-continuity/spike-anchor-edit.png).
- **(c) anchor-portrait: rejected.** All three shots are the reference portrait
  again, on the same grey studio background. No Montmartre scene is built. See
  [spike-anchor-portrait.png](series-continuity/spike-anchor-portrait.png).

The story's risk was that instruction editing keeps too much of the reference.
On MLX, edit is img2img, which keeps even more: at strength 0.6 the composition
is fixed by the reference. A strength high enough to move the scene (≥ 0.85)
leaves little of the reference, so it would give up the identity that anchor
mode exists for. sd.cpp's instruction editing (Metal, about 615 s per shot) was not
tried. Per 09.3-002's technical notes, that story shrinks to documenting prompt
mode as the only mode, and 09.3-003 keeps the look text only.

## Defects found in this run

- **!76**: `RemoteBackend` parsed a plain-JSON reply from a streamed POST without
  reading the body, so every `lig edit --host` failed with `ResponseNotRead`
  after the server had rendered the image. Generate was unaffected because it uses SSE.
  The tests' fake daemon returned a pre-read body. Fixed.

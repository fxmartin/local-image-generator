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

**Same person across all 5 photos: yes.** Every shot shows the short dark pixie
cut, the pale angular face, the black belted wool coat, the patterned silk scarf
and small hoop earrings. The weakest match is series 1, shot 3 (the tight
close-up): the face reads slightly older and more angular and the fringe is swept
aside, but the identifying traits hold. The two flea-market shots match the Paris
shots despite the change from black and white to colour.

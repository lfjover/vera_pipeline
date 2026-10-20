# face_gen

Repaint photos with **Stable Diffusion** (image-to-image and inpainting), locally on the Mac (Apple GPU).
This is the new version of `~/AI/notebooks/munu_face.ipynb`: give it a photo and a
prompt, and it keeps the photo's composition while repainting it in the prompt's style.

```
python -m facegen generate -i ../faces_square/DSCF5110_face.jpg \
    -p @prompts/munu_goddess.txt -n @prompts/negative_faces.txt --count 3   # 3 seeds

python -m facegen grid -i ../faces_square/DSCF5110_face.jpg \
    -p @prompts/munu_psychedelic.txt -n @prompts/negative_faces.txt \
    --strengths 0.6,0.65,0.7 --guidances 6,6.5,7                            # 3×3 contact sheet

python -m facegen vary -i ../faces_square/DSCF5110_face.jpg --count 6    # 6 new people, same background

python -m facegen rerun output/grid_.../r2c0_s123456.json --steps 100      # redo the one you like
```

`-p`/`-n` take text directly, or `@file.txt` to read a prompt file. Prompts can contain
options, `{red hair|black bob|blonde curls}`: each seed picks one, and the `.json` records the pick.

## Settings

| flag | default | what it does |
|------|---------|--------------|
| `--strength` | 0.6 | how much of the photo is repainted. ~0.5 keeps the face recognisable, 0.7+ drifts away |
| `--guidance` | 6 | how strictly to follow the prompt. Higher = stronger style, more artifacts |
| `--steps` | 80 | denoising steps. Img2img only runs `steps × strength` of them (80 × 0.6 = 48). More = cleaner skin and hair, but slower |
| `--seed` | random | same seed + same settings = same image |
| `--size` | 768, or 1024 for SDXL | the photo's long side is resized (up or down) to this. Stay near the model's native size: bigger is slower and can repeat faces |
| `--model` | `sd15` | `sd15`, `sdxl`, or any Hugging Face img2img model id |

## Variations: new faces, same photo

`vary` changes only the face and hair and keeps everything else (pose, neck, shoulders,
clothes, background) pixel-for-pixel:

1. a face-parsing model (`jonathandinu/face-parsing`) masks the face and hair (`mask.png` in the output),
2. an inpainting model repaints only the masked area (`sd15` → `stable-diffusion-v1-5/stable-diffusion-inpainting`,
   `sdxl` → `diffusers/stable-diffusion-xl-1.0-inpainting-0.1`),
3. the original photo is pasted back outside the mask, with a soft 6 px seam. A black-and-white
   photo stays black and white.

The default prompt, `prompts/variations.txt`, picks hair, skin, eyes, age and features at random
for each seed. Edit it, or pass your own with `-p`.

| flag | default | |
|------|---------|--|
| `--count` | 4 | variations (seeds seed, seed+1, ...) |
| `--strength` | 0.9 | 1.0 = ignore the old face entirely; lower keeps more of her head shape and lighting |
| `--grow` | 10 | widen the mask, in pixels, to catch stray hairs |
| `--mask` | automatic | your own mask image (white = repaint), e.g. to also change the clothes |
| `--model` | `sd15` | or `sdxl` (better, much slower) |

Output: `output/vary_<time>_<photo>/` with `v<n>_s<seed>.png` + `.json`, `mask.png`, and a
`contact_sheet.png` with the original first.

## SDXL

`--model sdxl` uses Stable Diffusion XL (`stabilityai/stable-diffusion-xl-base-1.0`) at 1024 px:
much more detail than SD 1.5, but a ~7 GB download and several times slower on an M1 Pro.
On a Mac it loads `madebyollin/sdxl-vae-fp16-fix`, because SDXL's own VAE decodes to black images
in half precision. Small photos are enlarged to 1024 first, so a sharper original still helps.

```
python -m facegen grid -i photo.jpg -p @prompts/munu_goddess.txt --model sdxl \
    --strengths 0.55,0.65 --guidances 5,6.5
```

## Output

- `generate` / `rerun`: `output/<time>_<prompt-slug>_s<seed>.png`
- `grid`: `output/grid_<time>_<prompt-slug>/` with every cell as `r<row>c<col>_s<seed>.png` and
  a labelled `contact_sheet.png` (rows = strengths, columns = guidances)

Every PNG has a `.json` next to it with the full recipe (prompt, negative, strength, guidance,
steps, seed, input photo, model). `rerun` reads it back. Any flag you pass overrides that
setting, and `-i` swaps the input photo. That replaces the notebook's pickles and `input_dicts/`.

## Setup

```
cd face_gen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m pytest
```

The first real run downloads the model (~2 GB) into `~/.cache/huggingface`. It is
loaded once per command, so a 3×3 grid costs one load, not nine. Expect roughly
10–30 s per 512–768 px image on an M1 Pro.

## Changes from the old notebook

- **The model loads once.** `munu_face.ipynb` reloaded it for every image.
- **The default model moved.** `runwayml/stable-diffusion-v1-5` has been taken down from Hugging Face.
  `stable-diffusion-v1-5/stable-diffusion-v1-5` is the same weights.
- **Prompts are limited to 77 tokens.** Stable Diffusion's text encoder (CLIP) reads only
  the first 77 tokens of each prompt. The old negative prompt was far longer, so most of it was
  silently ignored, and `facegen` now warns when this happens.
- **`((weight))` parentheses do nothing here.** That is AUTOMATIC1111 syntax. In diffusers
  the parentheses are just characters that use up tokens, so `prompts/negative_faces.txt`
  is a shorter, plain version of the old list.
- **The NSFW safety filter is off,** as in the notebook (it blacks out harmless portraits).
- Camera RAW files (`../photos/*.RAF`) can't be opened. Export to JPEG first, or use `../faces_square/`.

## Using it from Jupyter

```python
from facegen import Painter, Recipe

painter = Painter()                       # loads the model on first paint
recipe = Recipe(prompt="mother earth, intricate", input="../faces_square/DSCF5110_face.jpg", seed=42)
image = painter.paint(recipe)             # reuse `painter` for every image in the session
```

## Files

```
facegen/recipe.py   Recipe dataclass: settings ⇄ .json, output names
facegen/painter.py  loads the pipeline once, paints a recipe (img2img or inpaint), prompt-length warnings
facegen/masks.py    automatic face+hair mask, mask files
facegen/grid.py     strength × guidance grids and the contact sheet
facegen/cli.py      command line
prompts/            prompt files ported from munu_face.ipynb
tests/              unit tests with a fake pipeline (no model download)
```

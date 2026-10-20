"""Command line entry point:  python -m facegen <command>

  generate   repaint a photo from a prompt (one or more seeds)
  grid       try strength × guidance combinations and save a contact sheet
  vary       new faces and hair on the same photo, background kept exactly (inpainting)
  rerun      paint a saved recipe (.json) again, optionally changing some settings

Prompts can contain {option a|option b|option c}: each seed picks one at random.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import replace
from pathlib import Path

from .grid import contact_sheet, grid_labels, grid_recipes, run_grid
from .masks import AUTO_FACE_HAIR, make_mask
from .painter import Painter, load_image
from .recipe import (DEFAULT_MODEL, INPAINT_ALIASES, MODEL_ALIASES, Recipe, new_seed, output_name, read_text_arg,
                     resolve_model, slugify, timestamp)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = PROJECT_ROOT / "output"
PROMPTS = PROJECT_ROOT / "prompts"
SHEET_COLUMNS = 5


def build_painter(model: str, task: str = "img2img") -> Painter:
    return Painter(model, task=task)


def parse_floats(text: str) -> list[float]:
    try:
        return [float(x) for x in text.split(",") if x.strip()]
    except ValueError:
        raise ValueError(f"expected comma-separated numbers, e.g. 0.6,0.65,0.7, got {text!r}") from None


def recipe_from_args(args) -> Recipe:
    if not Path(args.image).is_file():
        raise FileNotFoundError(f"{args.image} not found")
    return Recipe(
        prompt=read_text_arg(args.prompt),
        negative=read_text_arg(args.negative) or "",
        input=str(Path(args.image).resolve()),
        strength=args.strength,
        guidance=args.guidance,
        steps=args.steps,
        seed=args.seed if args.seed is not None else new_seed(),
        size=args.size,
        model=resolve_model(args.model),
    )


def warn(painter: Painter, recipe: Recipe) -> None:
    for message in painter.prompt_warnings(recipe):
        print(f"warning: {message}", file=sys.stderr)


def paint_and_save(painter: Painter, recipe: Recipe, out_dir: Path, stamp: str) -> Path:
    started = time.monotonic()
    image = painter.paint(recipe)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / output_name(recipe, stamp)
    image.save(path)
    recipe.save(path.with_suffix(".json"))
    print(f"  saved {path}  ({time.monotonic() - started:.0f}s)")
    return path


# ----------------------------------------------------------------- commands
def cmd_generate(args) -> int:
    base = recipe_from_args(args)
    painter = build_painter(base.model)
    warn(painter, base.with_seed(base.seed))
    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT
    stamp = timestamp()
    for k in range(args.count):
        recipe = base.with_seed(base.seed + k)
        print(f"→ seed {recipe.seed}" + (f": {recipe.prompt}" if recipe.prompt != base.prompt else ""))
        paint_and_save(painter, recipe, out_dir, stamp)
    return 0


def cmd_grid(args) -> int:
    base = recipe_from_args(args)
    strengths, guidances = parse_floats(args.strengths), parse_floats(args.guidances)
    rows = grid_recipes(base, strengths, guidances, same_seed=args.same_seed)
    painter = build_painter(base.model)
    warn(painter, rows[0][0])
    out_root = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT
    out_dir = out_root / f"grid_{timestamp()}_{slugify(base.prompt)}"
    total = len(strengths) * len(guidances)
    images = run_grid(painter, rows, out_dir, on_cell=lambda i, j, r: print(
        f"→ ({i},{j}) {i * len(guidances) + j + 1}/{total}  strength {r.strength:g}  guidance {r.guidance:g}  seed {r.seed}"))
    sheet_path = out_dir / "contact_sheet.png"
    contact_sheet(images, grid_labels(rows)).save(sheet_path)
    print(f"Saved {total} images and {sheet_path}")
    print(f"Re-run one with:  python -m facegen rerun {out_dir}/r<i>c<j>_s<seed>.json")
    return 0


def cmd_vary(args) -> int:
    args.model = INPAINT_ALIASES.get(args.model.lower(), args.model)
    base = replace(recipe_from_args(args), task="inpaint", mask_grow=args.grow,
                   mask=str(Path(args.mask).resolve()) if args.mask else AUTO_FACE_HAIR)
    photo = load_image(base.input, base.size)
    print("Finding face and hair…" if base.mask == AUTO_FACE_HAIR else f"Using mask {base.mask}")
    mask = make_mask(base.mask, photo, base.mask_grow)
    out_root = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT
    out_dir = out_root / f"vary_{timestamp()}_{slugify(Path(base.input).stem)}"
    out_dir.mkdir(parents=True, exist_ok=True)
    mask.save(out_dir / "mask.png")

    recipes = [base.with_seed(base.seed + k) for k in range(args.count)]
    painter = build_painter(base.model, task="inpaint")
    warn(painter, recipes[0])
    images = []
    for k, recipe in enumerate(recipes, 1):
        print(f"→ {k}/{len(recipes)} seed {recipe.seed}: {' '.join(recipe.prompt.split())}")
        started = time.monotonic()
        image = painter.paint(recipe, photo, mask)
        path = out_dir / f"v{k}_s{recipe.seed}.png"
        image.save(path)
        recipe.save(path.with_suffix(".json"))
        print(f"  saved {path}  ({time.monotonic() - started:.0f}s)")
        images.append(image)

    cells = [photo, *images]
    labels = ["original", *(f"seed {r.seed}" for r in recipes)]
    chunks = range(0, len(cells), SHEET_COLUMNS)
    sheet_path = out_dir / "contact_sheet.png"
    contact_sheet([cells[i:i + SHEET_COLUMNS] for i in chunks], [labels[i:i + SHEET_COLUMNS] for i in chunks]).save(sheet_path)
    print(f"Saved {len(images)} variations, the mask and {sheet_path}")
    return 0


def cmd_rerun(args) -> int:
    recipe = Recipe.load(Path(args.recipe))
    changes = {k: v for k, v in {
        "strength": args.strength, "guidance": args.guidance, "steps": args.steps, "seed": args.seed,
        "size": args.size, "prompt": read_text_arg(args.prompt), "negative": read_text_arg(args.negative),
        "input": str(Path(args.image).resolve()) if args.image else None,
    }.items() if v is not None}
    recipe = replace(recipe, **changes)
    recipe = recipe.with_seed(recipe.seed)  # picks {a|b} options in a replaced prompt
    if not Path(recipe.input).is_file():
        raise FileNotFoundError(f"input photo {recipe.input} not found (pass another with -i)")
    painter = build_painter(recipe.model, recipe.task)
    warn(painter, recipe)
    out_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT
    print(f"→ seed {recipe.seed}" + (f"  changed: {', '.join(changes)}" if changes else ""))
    paint_and_save(painter, recipe, out_dir, timestamp())
    return 0


# ------------------------------------------------------------------- parser
def add_settings(p: argparse.ArgumentParser, defaults: bool, strength: float = 0.6, guidance: float = 6.0,
                 negative: str | None = None) -> None:
    """Settings shared by all commands. For rerun they default to None (= keep the recipe's value)."""
    d = (lambda value: value) if defaults else (lambda value: None)
    p.add_argument("-n", "--negative", default=d(negative), help="negative prompt, or @file.txt"
                   + (f" (default {negative})" if negative and defaults else ""))
    p.add_argument("--strength", type=float, default=d(strength), help=f"how much to repaint, 0–1 (default {strength:g})")
    p.add_argument("--guidance", type=float, default=d(guidance), help=f"how closely to follow the prompt (default {guidance:g})")
    p.add_argument("--steps", type=int, default=d(80), help="denoising steps (default 80)")
    p.add_argument("--seed", type=int, help="seed (default: random)")
    p.add_argument("--size", "--max-side", type=int,
                   help="resize the photo's long side to this (default: the model's native size, 768 or 1024 for SDXL)")
    p.add_argument("-o", "--output-dir", help="where to save (default: output/)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="facegen", description="Repaint photos with Stable Diffusion.")
    sub = parser.add_subparsers(dest="command", required=True)

    g = sub.add_parser("generate", help="repaint a photo from a prompt")
    g.add_argument("-i", "--image", required=True, help="input photo")
    g.add_argument("-p", "--prompt", required=True, help="prompt, or @file.txt")
    add_settings(g, defaults=True)
    g.add_argument("--count", type=int, default=1, help="how many variations, seed, seed+1, ... (default 1)")
    g.add_argument("--model", default=DEFAULT_MODEL, help=f"Hugging Face model id, or a shortcut: {', '.join(MODEL_ALIASES)} (default sd15)")

    gr = sub.add_parser("grid", help="try strength × guidance combinations")
    gr.add_argument("-i", "--image", required=True, help="input photo")
    gr.add_argument("-p", "--prompt", required=True, help="prompt, or @file.txt")
    add_settings(gr, defaults=True)
    gr.add_argument("--strengths", default="0.6,0.65,0.7", help="comma-separated (default 0.6,0.65,0.7)")
    gr.add_argument("--guidances", default="6,6.5,7", help="comma-separated (default 6,6.5,7)")
    gr.add_argument("--same-seed", action="store_true", help="use one seed for every cell (default: a new seed per cell)")
    gr.add_argument("--model", default=DEFAULT_MODEL, help=f"Hugging Face model id, or a shortcut: {', '.join(MODEL_ALIASES)} (default sd15)")

    v = sub.add_parser("vary", help="new faces and hair, everything else kept exactly")
    v.add_argument("-i", "--image", required=True, help="input photo")
    v.add_argument("-p", "--prompt", default=f"@{PROMPTS / 'variations.txt'}",
                   help="prompt with {a|b|c} options, or @file.txt (default prompts/variations.txt)")
    add_settings(v, defaults=True, strength=0.9, guidance=7.0, negative=f"@{PROMPTS / 'negative_faces.txt'}")
    v.add_argument("--count", type=int, default=4, help="how many variations, seed, seed+1, ... (default 4)")
    v.add_argument("--mask", help="mask image to use instead of the automatic face+hair one (white = repaint)")
    v.add_argument("--grow", type=int, default=10, help="widen the mask by this many pixels (default 10)")
    v.add_argument("--model", default="sd15", help="sd15 or sdxl (their inpainting versions), or an inpainting model id")

    r = sub.add_parser("rerun", help="paint a saved .json recipe again")
    r.add_argument("recipe", help="a .json saved next to an output image")
    r.add_argument("-i", "--image", help="use a different input photo")
    r.add_argument("-p", "--prompt", help="replace the prompt, or @file.txt")
    add_settings(r, defaults=False)

    args = parser.parse_args(argv)
    commands = {"generate": cmd_generate, "grid": cmd_grid, "vary": cmd_vary, "rerun": cmd_rerun}
    try:
        return commands[args.command](args)
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

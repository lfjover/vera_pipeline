"""Try every strength × guidance combination on one photo and lay them out on a contact sheet."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from .painter import Painter, load_image
from .recipe import Recipe, new_seed

LABEL_HEIGHT = 44


def grid_recipes(base: Recipe, strengths: list[float], guidances: list[float], same_seed: bool = False) -> list[list[Recipe]]:
    """One row per strength, one column per guidance; a new seed per cell unless same_seed."""
    return [
        [replace(base, strength=s, guidance=g).with_seed(base.seed if same_seed else new_seed()) for g in guidances]
        for s in strengths
    ]


def run_grid(painter: Painter, rows: list[list[Recipe]], out_dir: Path,
             on_cell: Callable[[int, int, Recipe], None] = lambda i, j, r: None) -> list[list[Image.Image]]:
    """Paint every cell, saving cell images and recipes as r<i>c<j>_s<seed>.png/.json as they finish."""
    out_dir.mkdir(parents=True, exist_ok=True)
    photo = load_image(rows[0][0].input, rows[0][0].size)
    images = []
    for i, row in enumerate(rows):
        images.append([])
        for j, recipe in enumerate(row):
            on_cell(i, j, recipe)
            image = painter.paint(recipe, photo)
            path = out_dir / f"r{i}c{j}_s{recipe.seed}.png"
            image.save(path)
            recipe.save(path.with_suffix(".json"))
            images[-1].append(image)
    return images


def grid_labels(rows: list[list[Recipe]]) -> list[list[str]]:
    return [[f"({i},{j})  strength {r.strength:g}  guidance {r.guidance:g}\nseed {r.seed}" for j, r in enumerate(row)]
            for i, row in enumerate(rows)]


def contact_sheet(images: list[list[Image.Image]], labels: list[list[str]], thumb: int = 384) -> Image.Image:
    """Thumbnails in a grid, each with a (up to two-line) label under it."""
    first = images[0][0]
    tw, th = thumb, round(thumb * first.height / first.width)
    columns = max(len(row) for row in images)
    sheet = Image.new("RGB", (tw * columns, (th + LABEL_HEIGHT) * len(images)), "white")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=15)
    for i, row in enumerate(images):
        for j, image in enumerate(row):
            x, y = j * tw, i * (th + LABEL_HEIGHT)
            sheet.paste(image.resize((tw, th), Image.LANCZOS), (x, y))
            draw.multiline_text((x + 6, y + th + 4), labels[i][j], fill="black", font=font, spacing=3)
    return sheet

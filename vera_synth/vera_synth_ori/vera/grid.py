"""The 3×3 winners grid and the per-photographer candidate sheets."""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]
FONT_PATHS_REGULAR = [
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]

BG = (17, 17, 17)
FG = (240, 236, 228)
MUTED = (160, 156, 150)
ACCENT = (232, 176, 74)


def load_font(size: int, bold: bool = True):
    for path in (FONT_PATHS if bold else FONT_PATHS_REGULAR):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1
        return ImageFont.load_default()


def _tile(path: Path, size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as img:
        return ImageOps.fit(img.convert("RGB"), size, method=Image.LANCZOS, centering=(0.5, 0.4))


def _fit(draw, text: str, font, width: int) -> str:
    """Shorten text with … so it fits the tile width."""
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text.rstrip() + "…"


def build_grid(cells: list[dict], out: Path, title: str, cols: int = 3,
               tile: tuple[int, int] = (540, 960)) -> Path:
    """cells: [{"image": Path, "label": str, "sublabel": str, "detail": str}] in reading order."""
    tw, th = tile
    pad, band, header = 24, 132, 110
    rows = max(1, -(-len(cells) // cols))
    width = cols * tw + (cols + 1) * pad
    height = header + rows * (th + band) + (rows + 1) * pad
    sheet = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 34), title, font=load_font(44), fill=FG)

    name_font, sub_font = load_font(30), load_font(24, bold=False)
    for i, cell in enumerate(cells):
        r, c = divmod(i, cols)
        x = pad + c * (tw + pad)
        y = header + pad + r * (th + band + pad)
        sheet.paste(_tile(Path(cell["image"]), tile), (x, y))
        draw.text((x, y + th + 14), cell.get("label", ""), font=name_font, fill=FG)
        draw.text((x, y + th + 54), _fit(draw, cell.get("sublabel", ""), sub_font, tw), font=sub_font, fill=MUTED)
        draw.text((x, y + th + 88), cell.get("detail", ""), font=sub_font, fill=ACCENT)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="JPEG", quality=92)
    return out


def pair_sheet(start: Path, final: Path, out: Path, title: str,
                tile: tuple[int, int] = (540, 960)) -> Path:
    """Opening frame and final frame side by side."""
    tw, th = tile
    pad, band, header = 24, 70, 90
    sheet = Image.new("RGB", (2 * tw + 3 * pad, header + th + band + 2 * pad), BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 28), title, font=load_font(36), fill=FG)
    font = load_font(26)
    for i, (path, label) in enumerate(((start, "opening"), (final, "final frame"))):
        x = pad + i * (tw + pad)
        y = header + pad
        sheet.paste(_tile(path, tile), (x, y))
        draw.text((x, y + th + 16), label, font=font, fill=ACCENT if i else FG)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="JPEG", quality=90)
    return out


def candidate_sheet(images: list[Path], totals: list[float], winner: int, out: Path, title: str,
                    tile: tuple[int, int] = (360, 640)) -> Path:
    """One row of candidates with their scores; the winner gets a gold frame."""
    tw, th = tile
    pad, band, header = 18, 60, 80
    width = len(images) * tw + (len(images) + 1) * pad
    sheet = Image.new("RGB", (width, header + th + band + 2 * pad), BG)
    draw = ImageDraw.Draw(sheet)
    draw.text((pad, 24), title, font=load_font(32), fill=FG)
    font = load_font(26)
    for i, (path, total) in enumerate(zip(images, totals)):
        x, y = pad + i * (tw + pad), header + pad
        sheet.paste(_tile(path, tile), (x, y))
        color = ACCENT if i == winner else FG
        if i == winner:
            draw.rectangle([x - 6, y - 6, x + tw + 5, y + th + 5], outline=ACCENT, width=6)
        label = f"#{i + 1}  {total:.1f}/10" + ("  WINNER" if i == winner else "")
        draw.text((x, y + th + 14), label, font=font, fill=color)
    out.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(out, format="JPEG", quality=88)
    return out

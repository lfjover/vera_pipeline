"""A Recipe is everything needed to paint one image again, exactly.

Each output PNG is saved with a matching .json recipe, so a good result can be
re-run later (same seed) or tweaked (different strength, steps, input...).
"""

from __future__ import annotations

import json
import random
import re
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "stable-diffusion-v1-5/stable-diffusion-v1-5"
MODEL_ALIASES = {
    "sd15": DEFAULT_MODEL,
    "sdxl": "stabilityai/stable-diffusion-xl-base-1.0",
    "sd15-inpaint": "stable-diffusion-v1-5/stable-diffusion-inpainting",
    "sdxl-inpaint": "diffusers/stable-diffusion-xl-1.0-inpainting-0.1",
}
INPAINT_ALIASES = {"sd15": "sd15-inpaint", "sdxl": "sdxl-inpaint"}
OPTIONS = re.compile(r"\{([^{}]*\|[^{}]*)\}")


def new_seed() -> int:
    return random.randrange(2**32)


def resolve_model(name: str) -> str:
    return MODEL_ALIASES.get(name.lower(), name)


def expand_options(text: str, seed: int) -> str:
    """'{red hair|black bob|blonde curls}' becomes one of the options, picked by the seed."""
    rng = random.Random(seed)
    return OPTIONS.sub(lambda m: rng.choice(m.group(1).split("|")).strip(), text)


def is_sdxl(model: str) -> bool:
    return "xl" in model.lower()


def native_size(model: str) -> int:
    """Long side the model works best at: SDXL was trained at 1024 px, SD 1.5 at 512 (768 still works well)."""
    return 1024 if is_sdxl(model) else 768


@dataclass
class Recipe:
    prompt: str
    input: str
    negative: str = ""
    strength: float = 0.6     # how much of the photo gets repainted (0 = none, 1 = all)
    guidance: float = 6.0     # how closely to follow the prompt
    steps: int = 80           # img2img actually runs steps × strength of them
    seed: int = field(default_factory=new_seed)
    size: int | None = None   # the photo is resized so its long side is this; None = the model's native size
    model: str = DEFAULT_MODEL
    task: str = "img2img"     # or "inpaint": repaint only the mask, keep the rest of the photo
    mask: str = ""            # inpaint only: "face_hair" (automatic) or the path of a mask image
    mask_grow: int = 0        # inpaint only: widen the mask by this many pixels

    def __post_init__(self):
        if self.size is None:
            self.size = native_size(self.model)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False) + "\n")

    @classmethod
    def load(cls, path: Path) -> "Recipe":
        data = json.loads(Path(path).read_text())
        if "max_side" in data:  # recipes saved before `size` replaced it
            data.setdefault("size", data.pop("max_side"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def with_seed(self, seed: int) -> "Recipe":
        """This recipe with another seed, and any {a|b|c} options in the prompts picked for that seed."""
        return replace(self, seed=seed, prompt=expand_options(self.prompt, seed),
                       negative=expand_options(self.negative, seed))


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "image"


def timestamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def output_name(recipe: Recipe, stamp: str) -> str:
    return f"{stamp}_{slugify(recipe.prompt)}_s{recipe.seed}.png"


def read_text_arg(value: str | None) -> str | None:
    """'@path/to/file.txt' reads the prompt from that file; anything else is used as is."""
    if value and value.startswith("@"):
        return Path(value[1:]).read_text().strip()
    return value

"""Stable Diffusion image-to-image and inpainting, loaded once and reused for every image.

(The old munu_face notebook reloaded the whole model for each picture, which is
most of why a 3×3 grid took half an hour.)

Inpainting repaints only the white part of a mask; the rest of the photo is then
pasted back from the original, so it stays pixel-for-pixel the same.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from .masks import make_mask
from .recipe import DEFAULT_MODEL, Recipe, is_sdxl

CLIP_TOKEN_LIMIT = 77
# SDXL's own VAE overflows in float16 and decodes to black images; this one is fixed for fp16.
SDXL_FP16_VAE = "madebyollin/sdxl-vae-fp16-fix"
FEATHER = 6  # px of blur where repainted and original pixels meet


def load_image(path: str | Path, size: int = 768) -> Image.Image:
    """Open a photo upright, in RGB, resized (up or down) so its long side is size, sides divisible by 8."""
    image = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    scale = size / max(image.size)
    width, height = (max(8, int(side * scale) // 8 * 8) for side in image.size)
    return image.resize((width, height), Image.LANCZOS)


def is_grayscale(image: Image.Image, tolerance: int = 8) -> bool:
    pixels = np.asarray(image.convert("RGB"), dtype=np.int16)
    return int(np.abs(pixels - pixels.mean(axis=2, keepdims=True)).max()) <= tolerance


def composite(original: Image.Image, painted: Image.Image, mask: Image.Image) -> Image.Image:
    """Repainted pixels inside the mask, original pixels outside, a soft seam in between."""
    painted = painted.resize(original.size, Image.LANCZOS)
    if is_grayscale(original):  # keep a black-and-white photo black and white
        painted = painted.convert("L").convert("RGB")
    return Image.composite(painted, original, mask.filter(ImageFilter.GaussianBlur(FEATHER)))


def pick_device() -> str:
    import torch

    if torch.backends.mps.is_available():
        return "mps"
    if torch.cuda.is_available():
        return "cuda"
    return "cpu"


def load_pipeline(model: str, device: str, task: str = "img2img"):
    import torch
    from diffusers import AutoPipelineForImage2Image, AutoPipelineForInpainting

    auto = AutoPipelineForInpainting if task == "inpaint" else AutoPipelineForImage2Image

    dtype = torch.float32 if device == "cpu" else torch.float16
    # Same as the old notebook: no NSFW filter (it blacks out harmless portraits).
    kwargs = {"torch_dtype": dtype, "safety_checker": None, "requires_safety_checker": False}
    if is_sdxl(model) and dtype == torch.float16:
        from diffusers import AutoencoderKL

        kwargs["vae"] = AutoencoderKL.from_pretrained(SDXL_FP16_VAE, torch_dtype=dtype)
    try:
        pipe = auto.from_pretrained(model, variant="fp16" if dtype == torch.float16 else None, **kwargs)
    except (OSError, ValueError):  # repo has no fp16 variant
        pipe = auto.from_pretrained(model, **kwargs)
    pipe = pipe.to(device)
    if device == "mps":
        pipe.enable_attention_slicing()  # recommended on Macs with less than 64 GB
        if is_sdxl(model):
            pipe.vae.enable_tiling()  # decoding a 1024 px image in one piece needs several GB more
    pipe.set_progress_bar_config(leave=False)
    return pipe


class Painter:
    def __init__(self, model: str = DEFAULT_MODEL, device: str | None = None, pipeline=None, task: str = "img2img"):
        self.model = model
        self.task = task
        self.device = device
        self._pipe = pipeline

    @property
    def pipe(self):
        if self._pipe is None:
            self.device = self.device or pick_device()
            print(f"Loading {self.model} on {self.device} (the first run downloads it: ~2 GB, ~7 GB for SDXL)…")
            self._pipe = load_pipeline(self.model, self.device, self.task)
        return self._pipe

    def paint(self, recipe: Recipe, image: Image.Image | None = None, mask: Image.Image | None = None) -> Image.Image:
        """Paint a recipe. For inpainting, pass the mask to reuse it, or it is made from recipe.mask."""
        import torch

        if (recipe.model, recipe.task) != (self.model, self.task):
            raise ValueError(f"recipe is for {recipe.model} ({recipe.task}), "
                             f"but this painter has {self.model} ({self.task}) loaded")
        image = image if image is not None else load_image(recipe.input, recipe.size)
        settings = dict(
            prompt=recipe.prompt,
            negative_prompt=recipe.negative or None,
            image=image,
            strength=recipe.strength,
            guidance_scale=recipe.guidance,
            num_inference_steps=recipe.steps,
            generator=torch.Generator("cpu").manual_seed(recipe.seed),
        )
        if recipe.task != "inpaint":
            return self.pipe(**settings).images[0]
        mask = mask if mask is not None else make_mask(recipe.mask, image, recipe.mask_grow)
        painted = self.pipe(**settings, mask_image=mask, width=image.width, height=image.height).images[0]
        return composite(image, painted, mask)

    def prompt_warnings(self, recipe: Recipe) -> list[str]:
        """CLIP reads only the first 77 tokens of each prompt; the rest is silently dropped."""
        tokenizer = getattr(self.pipe, "tokenizer", None)
        if tokenizer is None:
            return []
        warnings = []
        for name, text in (("prompt", recipe.prompt), ("negative", recipe.negative)):
            count = len(tokenizer(text or "")["input_ids"])
            if count > CLIP_TOKEN_LIMIT:
                warnings.append(f"{name} is {count} tokens; only the first {CLIP_TOKEN_LIMIT} are used")
        return warnings

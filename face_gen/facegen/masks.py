"""Masks for inpainting: white = repaint, black = keep exactly as in the photo.

The automatic mask covers the face and hair, found with a face-parsing model
(SegFormer trained on CelebAMask-HQ). Any black-and-white image can be used instead.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

FACE_PARSER = "jonathandinu/face-parsing"
AUTO_FACE_HAIR = "face_hair"
# CelebAMask-HQ labels that make up "face and hair"; neck, clothes and background are kept.
FACE_AND_HAIR = {"skin", "nose", "eye_g", "l_eye", "r_eye", "l_brow", "r_brow", "l_ear", "r_ear",
                 "mouth", "u_lip", "l_lip", "hair", "hat", "ear_r"}

# The parser's preprocessing (from its preprocessor_config.json), done here because
# transformers' Segformer image processors require torchvision.
PARSER_SIZE = 512
IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)

_parser = None


def _load_parser():
    global _parser
    if _parser is None:
        from transformers import SegformerForSemanticSegmentation

        _parser = SegformerForSemanticSegmentation.from_pretrained(FACE_PARSER).eval()
    return _parser


def face_hair_mask(image: Image.Image) -> Image.Image:
    import torch

    model = _load_parser()
    pixels = np.asarray(image.resize((PARSER_SIZE, PARSER_SIZE), Image.BILINEAR), dtype=np.float32) / 255
    pixels = (pixels - IMAGENET_MEAN) / IMAGENET_STD
    with torch.no_grad():
        logits = model(pixel_values=torch.from_numpy(pixels).permute(2, 0, 1)[None]).logits
    logits = torch.nn.functional.interpolate(logits, size=(image.height, image.width), mode="bilinear", align_corners=False)
    labels = logits.argmax(dim=1)[0]
    wanted = torch.tensor([int(i) for i, name in model.config.id2label.items() if name in FACE_AND_HAIR])
    selected = torch.isin(labels, wanted).to(torch.uint8).mul(255).numpy()
    return Image.fromarray(selected, mode="L")


def grow(mask: Image.Image, pixels: int) -> Image.Image:
    """Widen the white area so stray hairs and the hairline edge get repainted too."""
    return mask.filter(ImageFilter.MaxFilter(pixels * 2 + 1)) if pixels > 0 else mask


def make_mask(spec: str, image: Image.Image, grow_pixels: int) -> Image.Image:
    """spec is 'face_hair' for the automatic mask, or the path of a mask image."""
    if spec == AUTO_FACE_HAIR:
        mask = face_hair_mask(image)
    else:
        if not Path(spec).is_file():
            raise FileNotFoundError(f"mask {spec} not found")
        mask = Image.open(spec).convert("L").resize(image.size, Image.NEAREST)
    if mask.getbbox() is None:
        raise ValueError("the mask is empty: no face or hair found (pass a mask image with --mask)")
    return grow(mask, grow_pixels)

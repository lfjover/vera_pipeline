"""Claude (Anthropic Messages API): writes the prompts and scores the candidates."""

from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import requests
from PIL import Image

from .photographers import Photographer

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

PROMPT_RULES = """You write prompts for a photorealistic AI image model (Kling). Each prompt recreates one
dead photographer's portrait or street style, in a fresh new scene, for an Instagram account of cinematic portraits.

Rules for every prompt:
- Describe the photographer's technique (light, color or black and white, framing, lens, film stock,
  setting) in concrete visual terms. Never write the photographer's name.
- The subject is one adult woman in her twenties or thirties, fully clothed, shown with respect.
  Across the batch, every woman must differ in ethnicity, hair and styling.
- Add realism cues: real skin texture with visible pores, small freckles or blemishes, flyaway hairs,
  slightly asymmetrical face, unretouched, a named film stock and lens that fit the photographer's era.
- Her face must be clearly visible and sharp, vertical 9:16 framing.
- Keep each prompt under 900 characters. Write a short negative prompt too.
- When a batch lighting style is given, treat it as the kind of light, not as a sentence to copy.
  Invent a new concrete lighting setup for each photographer in that style. No two prompts may share
  the same gel color, shadow pattern, or light source. Write that setup into the prompt, and also
  return it alone in "light".
- Also write final_light: one sentence naming a cinematic light that is clearly different from the
  light in the prompt. It relights the same person into a final frame, where the camera angle
  and pose will also shift slightly. Describe only the new light, not a new person, place, or clothes.

Return only JSON: a list with one object per photographer, in the order given:
[{"slug": "...", "subject": "one-line description of the woman", "prompt": "...", "negative_prompt": "...", "light": "...", "final_light": "..."}]"""

SCORE_RULES = """You are judging candidate AI images for a portrait Instagram account. All candidates came from
the same prompt, written in the style of {name} ({style}).

Score every image from 0 to 10 on:
- realism: real skin texture, no plastic or airbrushed look, believable hair and fabric
- face_hands: no distorted features, odd eyes, extra or broken fingers
- style: light, color and framing match the photographer's style described above
- animation: face clearly visible, uncluttered background, would work for a short light-change video clip

Be strict and use the whole range. Return only JSON:
{{"scores": [{{"image": 1, "realism": 0, "face_hands": 0, "style": 0, "animation": 0, "reason": "one short sentence"}}]}}"""


class ClaudeError(RuntimeError):
    pass


def extract_json(text: str):
    """Parse the first JSON object or array in a reply, ignoring prose or code fences around it."""
    decoder = json.JSONDecoder()
    starts = [i for i in (text.find("{"), text.find("[")) if i != -1]
    if not starts:
        raise ClaudeError(f"No JSON in Claude's reply: {text[:200]}")
    for start in sorted(starts):
        try:
            value, _ = decoder.raw_decode(text[start:])
            return value
        except json.JSONDecodeError:
            continue
    raise ClaudeError(f"Could not parse JSON in Claude's reply: {text[:200]}")


def encode_image(path: Path, max_side: int = 1024) -> dict:
    """Downscaled JPEG as a base64 image block (smaller upload, fewer tokens)."""
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=88)
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.b64encode(buf.getvalue()).decode()}}


def _as_list(value) -> list[dict]:
    """Accept a bare list, or a list wrapped in an object like {"prompts": [...]}."""
    if isinstance(value, dict):
        lists = [v for v in value.values() if isinstance(v, list)]
        value = lists[0] if lists else [value]
    return [v for v in value if isinstance(v, dict)] if isinstance(value, list) else []


def _norm(text) -> str:
    import unicodedata
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return "".join(c for c in text if c.isalnum())


def _match(items: list[dict], p: Photographer, index: int, expected: int) -> dict | None:
    """Find the prompt for a photographer by slug, then by name, then by position."""
    for item in items:
        if _norm(item.get("slug")) == _norm(p.slug):
            return item
    for item in items:
        if _norm(p.name) in _norm(item.get("slug")) + _norm(item.get("name")) + _norm(item.get("photographer")):
            return item
    if len(items) == expected:
        return items[index]
    return None


class ClaudeClient:
    def __init__(self, api_key: str, model: str, session: requests.Session | None = None):
        self.api_key = api_key
        self.model = model
        self.session = session or requests.Session()
        self.last_reply = ""  # kept so a failed run can save what Claude actually said

    def _call(self, content, system: str | None = None, max_tokens: int = 4000) -> str:
        body = {"model": self.model, "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": content}]}
        if system:
            body["system"] = system
        resp = self.session.post(API_URL, json=body, timeout=180, headers={
            "x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"})
        try:
            data = resp.json()
        except ValueError:
            raise ClaudeError(f"Anthropic API returned HTTP {resp.status_code}: {resp.text[:200]}")
        if resp.status_code >= 400:
            err = data.get("error", {}) if isinstance(data, dict) else {}
            raise ClaudeError(f"Anthropic API error ({resp.status_code}): {err.get('message', data)}")
        if data.get("stop_reason") == "max_tokens":
            raise ClaudeError("Claude's reply was cut off (max_tokens); try again or use --count with fewer photographers")
        self.last_reply = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        return self.last_reply

    def ping(self) -> None:
        self._call("Reply with OK.", max_tokens=5)

    def write_prompts(self, photographers: list[Photographer], direction: str | None = None) -> list[dict]:
        listing = "\n".join(f"- slug: {p.slug} | {p.label}, {p.nationality} | "
                            f"{'color' if p.color else 'black and white or color'} | style: {p.style}"
                            for p in photographers)
        message = f"Write one prompt for each of these photographers:\n{listing}"
        if direction:
            message += (f"\n\nLighting style for this batch. Do not paste this text into the prompts. "
                        f"Write a different lighting setup for each photographer, in this style, blended with "
                        f"that photographer's own technique (where they conflict, this style wins):\n{direction}")
        reply = self._call(message, system=PROMPT_RULES, max_tokens=8000)
        items = _as_list(extract_json(reply))
        out = []
        for i, p in enumerate(photographers):
            item = _match(items, p, i, len(photographers))
            if not item or not str(item.get("prompt", "")).strip():
                raise ClaudeError(f"Claude didn't return a prompt for {p.slug}")
            out.append({"slug": p.slug, "subject": item.get("subject", ""),
                        "prompt": item["prompt"].strip(),
                        "negative_prompt": str(item.get("negative_prompt", "")).strip(),
                        "light": str(item.get("light", "")).strip(),
                        "final_light": str(item.get("final_light", "")).strip()})
        return out

    def score(self, photographer: Photographer, images: list[Path], direction: str | None = None) -> list[dict]:
        content: list[dict] = []
        for i, path in enumerate(images, 1):
            content.append({"type": "text", "text": f"Image {i}:"})
            content.append(encode_image(path))
        content.append({"type": "text", "text": f"Score all {len(images)} images."})
        system = SCORE_RULES.format(name=photographer.name, style=photographer.style)
        if direction:
            system += (f"\n\nThis batch also had a creative direction; count how well each image follows it "
                       f"as part of the style score:\n{direction}")
        reply = self._call(content, system=system, max_tokens=1500)
        scores = extract_json(reply).get("scores", [])
        by_index = {int(s.get("image", 0)): s for s in scores if isinstance(s, dict)}
        if len(by_index) < len(images):
            raise ClaudeError(f"Claude scored {len(by_index)} of {len(images)} images for {photographer.slug}")
        return [by_index[i] for i in range(1, len(images) + 1)]

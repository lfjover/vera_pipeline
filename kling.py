"""Minimal client for the official Kling API (image generation + image-to-video)."""
import base64
import os
import time
from pathlib import Path

import jwt
import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

API_BASE = os.getenv("KLING_API_BASE", "https://api-singapore.klingai.com").rstrip("/")


class KlingError(RuntimeError):
    pass


def _token() -> str:
    ak, sk = os.getenv("KLING_ACCESS_KEY"), os.getenv("KLING_SECRET_KEY")
    if not ak or not sk:
        raise KlingError("Missing KLING_ACCESS_KEY / KLING_SECRET_KEY. Copy .env.example to .env and fill them in.")
    now = int(time.time())
    return jwt.encode({"iss": ak, "exp": now + 1800, "nbf": now - 5}, sk, algorithm="HS256",
                      headers={"alg": "HS256", "typ": "JWT"})


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}", "Content-Type": "application/json"}


def image_b64(path) -> str:
    """Kling wants raw base64 with no data:image prefix."""
    return base64.b64encode(Path(path).read_bytes()).decode()


def _post(endpoint: str, payload: dict) -> str:
    r = requests.post(f"{API_BASE}{endpoint}", json=payload, headers=_headers(), timeout=60)
    data = r.json() if r.content else {}
    if r.status_code != 200 or data.get("code") not in (0, None):
        raise KlingError(f"{endpoint} failed ({r.status_code}): {data.get('message', r.text[:300])}")
    return data["data"]["task_id"]


def _poll(endpoint: str, task_id: str, interval: int = 8, timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = requests.get(f"{API_BASE}{endpoint}/{task_id}", headers=_headers(), timeout=60)
        data = r.json().get("data", {})
        status = data.get("task_status")
        if status == "succeed":
            return data["task_result"]
        if status == "failed":
            raise KlingError(f"Task {task_id} failed: {data.get('task_status_msg', 'no reason given')}")
        print(f"  ...{status or 'waiting'}", flush=True)
        time.sleep(interval)
    raise KlingError(f"Task {task_id} timed out after {timeout}s")


def download(url: str, dest) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(1 << 16):
                f.write(chunk)
    return dest


# ---- image variant (image + prompt -> new image, keeping the face) ----
def image_variant_payload(image_path, prompt, cfg, n=1) -> dict:
    return {
        "model_name": cfg["image_model"],
        "prompt": prompt,
        "image": image_b64(image_path),
        "image_reference": cfg["image_reference"],
        "image_fidelity": cfg["image_fidelity"],
        "human_fidelity": cfg["human_fidelity"],
        "n": n,
    }


def generate_variant(payload: dict) -> tuple[str, list[str]]:
    task_id = _post("/v1/images/generations", payload)
    print(f"  image task {task_id} submitted")
    result = _poll("/v1/images/generations", task_id)
    return task_id, [img["url"] for img in result.get("images", [])]


# ---- clip (start frame + end frame -> video) ----
def clip_payload(start_path, end_path, cfg) -> dict:
    return {
        "model_name": cfg["video_model"],
        "mode": cfg["video_mode"],
        "duration": cfg["video_duration"],
        "image": image_b64(start_path),
        "image_tail": image_b64(end_path),
        "prompt": cfg["clip_prompt"],
        "negative_prompt": cfg["clip_negative_prompt"],
    }


def generate_clip(payload: dict) -> tuple[str, list[str]]:
    task_id = _post("/v1/videos/image2video", payload)
    print(f"  video task {task_id} submitted (this takes a few minutes)")
    result = _poll("/v1/videos/image2video", task_id, interval=15, timeout=1800)
    return task_id, [v["url"] for v in result.get("videos", [])]

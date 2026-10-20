"""Image generation through fal.ai's queue API (pay-as-you-go access to Kling's image models).

  POST https://queue.fal.run/<model>       Authorization: Key <FAL_KEY>, JSON input
       → {request_id, status_url, response_url}
  GET  status_url                          → {"status": IN_QUEUE | IN_PROGRESS | COMPLETED}
  GET  response_url                        → {"images": [{"url": ...}, ...]}

Same interface as KlingClient (create_image_task / wait_for_images / download),
so the pipeline doesn't care which one it talks to. If a model returns fewer
images than asked for, extra requests are made until there are enough.
"""

from __future__ import annotations

import base64
import io
import json
import time
from pathlib import Path
from typing import Callable

import requests
from PIL import Image

QUEUE_URL = "https://queue.fal.run"
DEFAULT_MODEL = "fal-ai/kling-image/o3/text-to-image"
EDIT_MODEL = "fal-ai/kling-image/o3/image-to-image"


class FalError(RuntimeError):
    def __init__(self, message: str, payload=None):
        super().__init__(message)
        self.payload = payload


def _error_text(resp) -> str:
    try:
        body = resp.json()
    except ValueError:
        return resp.text[:300]
    detail = body.get("detail", body) if isinstance(body, dict) else body
    if isinstance(detail, list):  # validation errors: [{"loc": [...], "msg": "..."}]
        return "; ".join(f"{'.'.join(map(str, d.get('loc', [])[1:]))}: {d.get('msg')}" for d in detail
                         if isinstance(d, dict)) or json.dumps(detail)[:300]
    return str(detail)[:300]


class FalClient:
    def __init__(self, key: str, model: str = DEFAULT_MODEL, extra_input: dict | None = None,
                 session: requests.Session | None = None, sleep: Callable[[float], None] = time.sleep):
        if not key:
            raise ValueError("fal needs FAL_KEY")
        self.key = key
        self.model = model.strip("/")
        self.extra_input = extra_input or {}
        self.session = session or requests.Session()
        self._sleep = sleep
        self._tasks: dict[str, dict] = {}

    @property
    def _headers(self) -> dict:
        return {"Authorization": f"Key {self.key}", "Content-Type": "application/json"}

    def _get(self, url: str) -> dict:
        resp = self.session.request("GET", url, headers=self._headers, timeout=60)
        if resp.status_code >= 400:
            raise FalError(f"fal error {resp.status_code}: {_error_text(resp)}")
        return resp.json()

    def _submit(self, prompt: str, n: int, aspect_ratio: str, *, model: str | None = None,
                extra: dict | None = None) -> dict:
        body = {"prompt": prompt, "num_images": n, "aspect_ratio": aspect_ratio, **self.extra_input}
        if extra:
            body.update(extra)
        model = (model or self.model).strip("/")
        resp = self.session.request("POST", f"{QUEUE_URL}/{model}", headers=self._headers,
                                    json=body, timeout=120)
        if resp.status_code >= 400:
            raise FalError(f"fal error {resp.status_code} for {model}: {_error_text(resp)}")
        data = resp.json()
        base = f"{QUEUE_URL}/{model}/requests/{data['request_id']}"
        return {"id": data["request_id"],
                "status_url": data.get("status_url") or f"{base}/status",
                "response_url": data.get("response_url") or base}

    def ping(self) -> None:
        """Checks the key without spending anything: an unknown request id returns 404, a bad key 401/403."""
        resp = self.session.request("GET", f"{QUEUE_URL}/{self.model}/requests/00000000-0000-0000-0000-000000000000/status",
                                    headers=self._headers, timeout=30)
        if resp.status_code in (401, 403):
            raise FalError(f"fal rejected the key ({resp.status_code}): {_error_text(resp)}")

    def create_image_task(self, prompt: str, negative_prompt: str | None = None,
                          n: int = 5, aspect_ratio: str = "9:16") -> str:
        # Most fal Kling image endpoints have no negative prompt field, so fold the key items into the prompt.
        if negative_prompt:
            prompt = f"{prompt} Avoid: {negative_prompt}"
        req = self._submit(prompt, n, aspect_ratio)
        self._tasks[req["id"]] = {"prompt": prompt, "n": n, "aspect_ratio": aspect_ratio, "requests": [req]}
        return req["id"]

    def create_final_frame(self, prompt: str, image: Path, aspect_ratio: str = "9:16") -> str:
        """Relight one existing photo. The prompt should mention @Image, Kling's name for that photo."""
        req = self._submit(prompt, 1, aspect_ratio, model=EDIT_MODEL, extra={
            "image_urls": [_jpeg_data_uri(Path(image))],
            "output_format": "jpeg",
        })
        self._tasks[req["id"]] = {"prompt": prompt, "n": 1, "aspect_ratio": aspect_ratio, "requests": [req]}
        return req["id"]

    def _wait_one(self, req: dict, timeout: float, interval: float) -> list[str]:
        waited = 0.0
        while True:
            status = self._get(req["status_url"]).get("status")
            if status == "COMPLETED":
                break
            if status not in ("IN_QUEUE", "IN_PROGRESS"):
                raise FalError(f"fal request {req['id']} ended with status {status}")
            if waited >= timeout:
                raise FalError(f"fal request {req['id']} still {status} after {timeout:.0f}s")
            self._sleep(interval)
            waited += interval
        result = self._get(req["response_url"])
        images = result.get("images") or ([result["image"]] if result.get("image") else [])
        urls = [img["url"] if isinstance(img, dict) else img for img in images]
        if not urls:
            raise FalError(f"fal request {req['id']} finished without images: {json.dumps(result)[:200]}")
        return urls

    def wait_for_images(self, task_id: str, timeout: float = 900, interval: float = 4) -> list[str]:
        task = self._tasks[task_id]
        urls: list[str] = []
        for req in task["requests"]:
            urls += self._wait_one(req, timeout, interval)
        extra = 0
        while len(urls) < task["n"] and extra < task["n"]:  # model gave fewer images than asked
            extra += 1
            req = self._submit(task["prompt"], task["n"] - len(urls), task["aspect_ratio"])
            urls += self._wait_one(req, timeout, interval)
        return urls[: task["n"]]

    def download(self, url: str, dest: Path) -> Path:
        resp = self.session.get(url, timeout=120)
        if resp.status_code >= 400:
            raise FalError(f"Download failed with HTTP {resp.status_code}: {url}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest


def _jpeg_data_uri(path: Path, max_side: int = 1280) -> str:
    with Image.open(path) as img:
        img = img.convert("RGB")
        img.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=90)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()

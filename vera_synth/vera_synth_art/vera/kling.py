"""Kling image generation over its HTTP API.

Auth: Kling's newer single API key is sent as-is: `Authorization: Bearer <key>`.
Older accounts have an access key + secret key pair instead; then the bearer
token is a short-lived JWT (HS256) signed with the secret key, access key as `iss`.

Flow: POST /v1/images/generations creates a task that renders `n` images
(each from a different random seed); GET /v1/images/generations/{task_id}
reports task_status (submitted, processing, succeed, failed) and, when it
succeeds, task_result.images[].url. Image URLs expire, so download right away.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
from typing import Callable

import requests


class KlingError(RuntimeError):
    def __init__(self, message: str, payload=None):
        super().__init__(message)
        self.payload = payload


def _b64(data: bytes) -> bytes:
    return base64.urlsafe_b64encode(data).rstrip(b"=")


def make_jwt(access_key: str, secret_key: str, now: float | None = None, ttl: int = 1800) -> str:
    now = int(time.time() if now is None else now)
    header = {"alg": "HS256", "typ": "JWT"}
    payload = {"iss": access_key, "exp": now + ttl, "nbf": now - 5}
    signing = (_b64(json.dumps(header, separators=(",", ":")).encode()) + b"."
               + _b64(json.dumps(payload, separators=(",", ":")).encode()))
    signature = _b64(hmac.new(secret_key.encode(), signing, hashlib.sha256).digest())
    return (signing + b"." + signature).decode()


class KlingClient:
    def __init__(self, access_key: str | None = None, secret_key: str | None = None,
                 base_url: str = "https://api-singapore.klingai.com",
                 model: str = "kling-v2-1",
                 session: requests.Session | None = None,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.time,
                 api_key: str | None = None):
        if not api_key and not (access_key and secret_key):
            raise ValueError("Kling needs an API key, or an access key and secret key")
        self.api_key = api_key
        self.access_key = access_key
        self.secret_key = secret_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.session = session or requests.Session()
        self._sleep = sleep
        self._clock = clock
        self._token: str | None = None
        self._token_exp = 0.0

    def _auth(self) -> dict:
        if self.api_key:
            return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        now = self._clock()
        if self._token is None or now > self._token_exp - 60:
            self._token = make_jwt(self.access_key, self.secret_key, now=now)
            self._token_exp = now + 1800
        return {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}

    def _request(self, method: str, path: str, body: dict | None = None, params: dict | None = None) -> dict:
        resp = self.session.request(method, f"{self.base_url}{path}", headers=self._auth(),
                                    json=body, params=params, timeout=60)
        try:
            data = resp.json()
        except ValueError:
            raise KlingError(f"Kling returned HTTP {resp.status_code} with a non-JSON body: {resp.text[:200]}")
        code = data.get("code")
        if resp.status_code >= 400 or code not in (0, None):
            raise KlingError(f"Kling error {code}: {data.get('message') or resp.status_code}", data)
        return data

    def ping(self) -> None:
        """Cheap authenticated call: lists your most recent image task."""
        self._request("GET", "/v1/images/generations", params={"pageNum": 1, "pageSize": 1})

    def create_image_task(self, prompt: str, negative_prompt: str | None = None,
                          n: int = 5, aspect_ratio: str = "9:16") -> str:
        if not 1 <= n <= 9:
            raise ValueError("Kling makes 1 to 9 images per task")
        body = {"model_name": self.model, "prompt": prompt[:2500], "n": n, "aspect_ratio": aspect_ratio}
        if negative_prompt:
            body["negative_prompt"] = negative_prompt[:2500]
        data = self._request("POST", "/v1/images/generations", body=body)
        return data["data"]["task_id"]

    def get_image_task(self, task_id: str) -> dict:
        return self._request("GET", f"/v1/images/generations/{task_id}")["data"]

    def wait_for_images(self, task_id: str, timeout: float = 900, interval: float = 6) -> list[str]:
        waited = 0.0
        while True:
            task = self.get_image_task(task_id)
            status = task.get("task_status")
            if status == "succeed":
                images = (task.get("task_result") or {}).get("images") or []
                urls = [img["url"] for img in sorted(images, key=lambda i: i.get("index", 0)) if img.get("url")]
                if not urls:
                    raise KlingError(f"Task {task_id} succeeded but returned no images", task)
                return urls
            if status == "failed":
                raise KlingError(f"Task {task_id} failed: {task.get('task_status_msg') or 'no reason given'}", task)
            if waited >= timeout:
                raise KlingError(f"Task {task_id} still {status} after {timeout:.0f}s", task)
            self._sleep(interval)
            waited += interval

    def download(self, url: str, dest: Path) -> Path:
        resp = self.session.get(url, timeout=120)
        if resp.status_code >= 400:
            raise KlingError(f"Download failed with HTTP {resp.status_code}: {url}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(resp.content)
        return dest

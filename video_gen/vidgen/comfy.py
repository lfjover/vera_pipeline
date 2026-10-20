"""Thin client for a ComfyUI server's HTTP API.

Generating a video is:
  1. upload any input image        (POST /upload/image)
  2. queue the workflow            (POST /prompt -> prompt_id)
  3. poll until it has run         (GET /history/{prompt_id})
  4. download each output file     (GET /view?filename=...&subfolder=...&type=output)

The server can be anywhere (a rented GPU, reached through an SSH tunnel, is the
usual case); only base_url changes.
"""

from __future__ import annotations

import time
import uuid
from pathlib import Path
from typing import Any, Callable

import requests

DEFAULT_URL = "http://127.0.0.1:8188"
VIDEO_EXTENSIONS = {".mp4", ".webm", ".mov", ".mkv", ".gif", ".webp"}


class ComfyError(RuntimeError):
    """Raised when ComfyUI rejects a workflow or a run fails."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


class ComfyClient:
    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        token: str | None = None,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}
        self.client_id = uuid.uuid4().hex
        self._sleep = sleep
        self._clock = clock

    # ------------------------------------------------------------------ http
    def _request(self, method: str, path: str, **kwargs) -> requests.Response:
        try:
            resp = self.session.request(method, f"{self.base_url}{path}", headers=self.headers,
                                        timeout=kwargs.pop("timeout", 60), **kwargs)
        except requests.ConnectionError as exc:
            raise ComfyError(f"can't reach ComfyUI at {self.base_url} — is the server (or SSH tunnel) up?") from exc
        if resp.status_code >= 400:
            try:
                payload = resp.json()
            except ValueError:
                payload = resp.text
            raise ComfyError(_error_message(payload) or f"HTTP {resp.status_code} from {path}",
                             status=resp.status_code, payload=payload)
        return resp

    def _json(self, method: str, path: str, **kwargs) -> Any:
        return self._request(method, path, **kwargs).json()

    # ---------------------------------------------------------------- server
    def system_stats(self) -> dict:
        return self._json("GET", "/system_stats")

    def model_options(self, node_class: str, input_name: str) -> list[str]:
        """Choices ComfyUI offers for a loader input, e.g. ("UNETLoader", "unet_name")."""
        info = self._json("GET", f"/object_info/{node_class}").get(node_class) or {}
        required = (info.get("input") or {}).get("required") or {}
        spec = required.get(input_name) or [[]]
        options = spec[0]
        if isinstance(options, str) and len(spec) > 1:  # newer "COMBO" style
            options = (spec[1] or {}).get("options", [])
        return list(options) if isinstance(options, list) else []

    # ------------------------------------------------------------------- run
    def upload_image(self, path: Path) -> str:
        """Upload a local image and return the name LoadImage nodes should use."""
        with open(path, "rb") as fh:
            body = self._json("POST", "/upload/image", files={"image": (path.name, fh)},
                              data={"overwrite": "true"}, timeout=300)
        sub = body.get("subfolder")
        return f"{sub}/{body['name']}" if sub else body["name"]

    def queue(self, workflow: dict) -> str:
        body = self._json("POST", "/prompt", json={"prompt": workflow, "client_id": self.client_id})
        if body.get("node_errors"):
            raise ComfyError("workflow rejected: " + _error_message(body), payload=body)
        return body["prompt_id"]

    def wait(self, prompt_id: str, timeout: float = 3600, poll: float = 5,
             on_tick: Callable[[float], None] | None = None) -> dict:
        """Poll /history until the prompt has finished; return its history entry."""
        start = self._clock()
        while True:
            entry = self._json("GET", f"/history/{prompt_id}").get(prompt_id)
            if entry:
                status = entry.get("status") or {}
                if status.get("status_str") == "error":
                    raise ComfyError("generation failed: " + _execution_error(status), payload=status)
                if status.get("completed", True):
                    return entry
            elapsed = self._clock() - start
            if elapsed > timeout:
                raise ComfyError(f"timed out after {int(elapsed)}s waiting for {prompt_id}")
            if on_tick:
                on_tick(elapsed)
            self._sleep(poll)

    def download(self, file: dict, dest_dir: Path, name: str | None = None) -> Path:
        params = {"filename": file["filename"], "subfolder": file.get("subfolder", ""),
                  "type": file.get("type", "output")}
        resp = self._request("GET", "/view", params=params, timeout=600, stream=True)
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / (name or file["filename"])
        with open(dest, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                fh.write(chunk)
        return dest


def output_files(entry: dict, videos_only: bool = True) -> list[dict]:
    """Every file a finished prompt saved (SaveVideo/VHS use "images", "gifs" or "videos")."""
    files = []
    for node_out in (entry.get("outputs") or {}).values():
        for key in ("videos", "gifs", "images"):
            for f in node_out.get(key) or []:
                if f.get("type", "output") != "output":
                    continue  # temp previews
                if videos_only and Path(f["filename"]).suffix.lower() not in VIDEO_EXTENSIONS:
                    continue
                files.append(f)
    return files


def _error_message(payload: Any) -> str:
    if not isinstance(payload, dict):
        return str(payload or "")
    parts = []
    err = payload.get("error")
    if isinstance(err, dict):
        parts.append(err.get("message") or err.get("type") or "")
        if err.get("details"):
            parts.append(str(err["details"]))
    elif err:
        parts.append(str(err))
    for node_id, node in (payload.get("node_errors") or {}).items():
        for e in node.get("errors") or []:
            parts.append(f"node {node_id} ({node.get('class_type')}): {e.get('message')} {e.get('details', '')}".strip())
    return "; ".join(p for p in parts if p)


def _execution_error(status: dict) -> str:
    for kind, data in status.get("messages") or []:
        if kind == "execution_error":
            return f"{data.get('node_type')} (node {data.get('node_id')}): {data.get('exception_message', '').strip()}"
    return "unknown error (check the ComfyUI server log)"

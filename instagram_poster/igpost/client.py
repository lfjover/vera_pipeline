"""Thin client for the Instagram API with Instagram Login (graph.instagram.com).

Publishing is a two-step flow:
  1. create a media container  (POST /{ig_user_id}/media)
  2. publish the container     (POST /{ig_user_id}/media_publish)
Video (Reels) containers must finish processing before step 2, so we poll
GET /{container_id}?fields=status_code until it reports FINISHED.

Meta fetches media from a public URL, so every image_url / video_url passed
here must already be reachable on the internet (see hosting.py).
"""

from __future__ import annotations

import math
import time
from typing import Any, Callable, Iterable

import requests

DEFAULT_HOST = "https://graph.instagram.com"
DEFAULT_API_VERSION = "v25.0"


class InstagramAPIError(RuntimeError):
    """Raised when the Graph API returns an error or a container fails."""

    def __init__(self, message: str, status: int | None = None, payload: Any = None):
        super().__init__(message)
        self.status = status
        self.payload = payload


def _clean(fields: dict[str, Any]) -> dict[str, str]:
    """Drop None values and turn booleans into the 'true'/'false' the API expects."""
    out: dict[str, str] = {}
    for key, value in fields.items():
        if value is None:
            continue
        if isinstance(value, bool):
            out[key] = "true" if value else "false"
        else:
            out[key] = str(value)
    return out


class InstagramClient:
    def __init__(
        self,
        access_token: str,
        ig_user_id: str,
        api_version: str = DEFAULT_API_VERSION,
        host: str = DEFAULT_HOST,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not access_token:
            raise ValueError("access_token is required")
        if not ig_user_id:
            raise ValueError("ig_user_id is required")
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self.api_version = api_version
        self.host = host.rstrip("/")
        self.session = session or requests.Session()
        self._sleep = sleep

    # ------------------------------------------------------------------ http
    def _url(self, path: str) -> str:
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return f"{self.host}/{self.api_version}/{path.lstrip('/')}"

    def _request(self, method: str, path: str, params: dict | None = None,
                 data: dict | None = None) -> dict:
        params = dict(params or {})
        data = dict(data or {})
        if method.upper() == "GET":
            params["access_token"] = self.access_token
        else:
            data["access_token"] = self.access_token
        resp = self.session.request(method, self._url(path), params=params or None,
                                    data=data or None, timeout=60)
        try:
            body = resp.json()
        except ValueError:
            body = {"raw": resp.text}
        if resp.status_code >= 400 or (isinstance(body, dict) and "error" in body):
            err = body.get("error", {}) if isinstance(body, dict) else {}
            message = err.get("error_user_msg") or err.get("message") or f"HTTP {resp.status_code}"
            raise InstagramAPIError(message, resp.status_code, body)
        return body

    # --------------------------------------------------------------- account
    def me(self) -> dict:
        return self._request("GET", "me", params={"fields": "user_id,username,account_type,media_count"})

    def publishing_limit(self) -> dict:
        """Returns e.g. {'quota_usage': 3, 'config': {'quota_total': 100, 'quota_duration': 86400}}."""
        body = self._request("GET", f"{self.ig_user_id}/content_publishing_limit",
                             params={"fields": "config,quota_usage"})
        data = body.get("data") or [{}]
        return data[0]

    def refresh_token(self) -> dict:
        """Extends a long-lived token by another ~60 days. Returns access_token and expires_in."""
        return self._request("GET", f"{self.host}/refresh_access_token",
                             params={"grant_type": "ig_refresh_token"})

    # ------------------------------------------------------------ containers
    def _create_container(self, **fields: Any) -> str:
        body = self._request("POST", f"{self.ig_user_id}/media", data=_clean(fields))
        return body["id"]

    def create_image_container(self, image_url: str, caption: str | None = None,
                               ai_generated: bool = True) -> str:
        return self._create_container(image_url=image_url, caption=caption,
                                      is_ai_generated=ai_generated)

    def create_reel_container(self, video_url: str, caption: str | None = None,
                              ai_generated: bool = True, share_to_feed: bool = True,
                              cover_url: str | None = None,
                              thumb_offset_ms: int | None = None) -> str:
        return self._create_container(media_type="REELS", video_url=video_url, caption=caption,
                                      is_ai_generated=ai_generated, share_to_feed=share_to_feed,
                                      cover_url=cover_url, thumb_offset=thumb_offset_ms)

    def create_carousel_item(self, url: str, is_video: bool = False) -> str:
        if is_video:
            return self._create_container(media_type="VIDEO", video_url=url, is_carousel_item=True)
        return self._create_container(image_url=url, is_carousel_item=True)

    def create_carousel_container(self, children: Iterable[str], caption: str | None = None,
                                  ai_generated: bool = True) -> str:
        children = list(children)
        if not 2 <= len(children) <= 10:
            raise ValueError("A carousel needs between 2 and 10 items")
        # The AI label goes on the carousel container only, not on its items.
        return self._create_container(media_type="CAROUSEL", children=",".join(children),
                                      caption=caption, is_ai_generated=ai_generated)

    def container_status(self, container_id: str) -> dict:
        return self._request("GET", container_id, params={"fields": "status_code,status"})

    def wait_until_ready(self, container_id: str, timeout: float = 300, interval: float = 30) -> None:
        """Poll until the container is FINISHED. Meta asks for roughly one poll per minute, max 5 min."""
        attempts = max(1, math.ceil(timeout / interval)) + 1
        last: dict = {}
        for attempt in range(attempts):
            last = self.container_status(container_id)
            code = last.get("status_code")
            if code == "FINISHED":
                return
            if code in ("ERROR", "EXPIRED"):
                raise InstagramAPIError(
                    f"Container {container_id} {code}: {last.get('status', 'no details')}", payload=last)
            if code == "PUBLISHED":
                raise InstagramAPIError(f"Container {container_id} was already published", payload=last)
            if attempt < attempts - 1:
                self._sleep(interval)
        raise InstagramAPIError(
            f"Container {container_id} not ready after {timeout:.0f}s (last status: {last.get('status_code')})",
            payload=last)

    def publish(self, container_id: str) -> str:
        body = self._request("POST", f"{self.ig_user_id}/media_publish", data={"creation_id": container_id})
        return body["id"]

    def get_media(self, media_id: str) -> dict:
        return self._request("GET", media_id, params={
            "fields": "id,permalink,media_type,media_product_type,timestamp,is_ai_generated"})

    # ------------------------------------------------------------ high level
    def _finish(self, container_id: str, timeout: float, interval: float) -> dict:
        self.wait_until_ready(container_id, timeout=timeout, interval=interval)
        media_id = self.publish(container_id)
        try:
            media = self.get_media(media_id)
        except InstagramAPIError:
            media = {"id": media_id}
        return {"media_id": media_id, "container_id": container_id,
                "permalink": media.get("permalink"), "media": media}

    def post_image(self, image_url: str, caption: str | None = None, ai_generated: bool = True,
                   timeout: float = 120, interval: float = 10) -> dict:
        cid = self.create_image_container(image_url, caption, ai_generated)
        return self._finish(cid, timeout, interval)

    def post_reel(self, video_url: str, caption: str | None = None, ai_generated: bool = True,
                  share_to_feed: bool = True, cover_url: str | None = None,
                  timeout: float = 300, interval: float = 30) -> dict:
        cid = self.create_reel_container(video_url, caption, ai_generated, share_to_feed, cover_url)
        return self._finish(cid, timeout, interval)

    def post_carousel(self, items: list[tuple[str, bool]], caption: str | None = None,
                      ai_generated: bool = True, timeout: float = 300, interval: float = 30) -> dict:
        """items: list of (public_url, is_video)."""
        children = []
        for url, is_video in items:
            child = self.create_carousel_item(url, is_video)
            if is_video:
                self.wait_until_ready(child, timeout=timeout, interval=interval)
            children.append(child)
        cid = self.create_carousel_container(children, caption, ai_generated)
        return self._finish(cid, timeout, interval)

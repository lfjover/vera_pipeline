"""Turn a local media file into a public URL Meta can fetch.

Instagram's API does not accept file uploads for images or Reels on the
Instagram Login path: it downloads the media from a URL you give it. So local
files are first uploaded to an S3-compatible bucket with public read access
(Cloudflare R2 has a free tier and a public r2.dev URL).
"""

from __future__ import annotations

import hashlib
import mimetypes
from pathlib import Path
from typing import Protocol

from .config import Settings

IMAGE_TYPES = {".jpg", ".jpeg"}           # Instagram publishing accepts JPEG only
VIDEO_TYPES = {".mp4", ".mov"}


def is_url(ref: str) -> bool:
    return ref.startswith("https://") or ref.startswith("http://")


def media_kind(ref: str) -> str:
    """'image' or 'video', based on the file extension."""
    suffix = Path(ref.split("?", 1)[0]).suffix.lower()
    if suffix in IMAGE_TYPES:
        return "image"
    if suffix in VIDEO_TYPES:
        return "video"
    if suffix in {".png", ".webp", ".heic"}:
        raise ValueError(f"{ref}: Instagram only publishes JPEG images — convert it to .jpg first")
    raise ValueError(f"{ref}: unsupported media type {suffix or '(none)'}; use .jpg, .mp4 or .mov")


class MediaHost(Protocol):
    def upload(self, path: Path) -> str: ...


class NoHost:
    """Used when no bucket is configured: only already-public URLs work."""

    def upload(self, path: Path) -> str:
        raise RuntimeError(
            f"Can't post local file {path.name}: no hosting configured. Set S3_BUCKET and "
            "PUBLIC_BASE_URL in .env (see README), or pass a public https:// URL instead.")


class DryRunHost:
    """Pretends to upload so --dry-run never touches the network."""

    def __init__(self, public_base_url: str | None):
        self.base = (public_base_url or "https://example.invalid").rstrip("/")

    def upload(self, path: Path) -> str:
        return f"{self.base}/<dry-run>/{path.name}"


class S3Host:
    def __init__(self, settings: Settings):
        try:
            import boto3  # optional dependency
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("Install boto3 to upload media: pip install boto3") from exc
        self.bucket = settings.s3_bucket
        self.prefix = settings.s3_prefix
        self.base = settings.public_base_url.rstrip("/")
        self.s3 = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key_id,
            aws_secret_access_key=settings.s3_secret_access_key,
            region_name=settings.s3_region or "auto",
        )

    def upload(self, path: Path) -> str:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
        key = f"{self.prefix}{digest}-{path.name}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        self.s3.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})
        return f"{self.base}/{key}"


def make_host(settings: Settings, dry_run: bool = False) -> MediaHost:
    if dry_run:
        return DryRunHost(settings.public_base_url)
    if settings.hosting_configured:
        return S3Host(settings)
    return NoHost()


def resolve_media(ref: str, host: MediaHost, base_dir: Path) -> tuple[str, bool]:
    """Return (public_url, is_video) for a local path or URL."""
    is_video = media_kind(ref) == "video"
    if is_url(ref):
        return ref, is_video
    path = Path(ref).expanduser()
    if not path.is_absolute():
        path = (base_dir / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Media file not found: {path}")
    return host.upload(path), is_video

"""Post definitions and the file-based queue.

Each queued post is one JSON file in queue/:

    {
      "type": "reel",                     # image | reel | carousel
      "media": ["../media/clip01.mp4"],   # paths (relative to the JSON file) or public URLs
      "caption": "Morning by the pool ☀️ #beachhotel",
      "publish_after": "2026-10-17T18:00:00-05:00",   # optional; missing = post now
      "ai_generated": true                # adds Instagram's "AI info" label (default true)
    }

After publishing, the file moves to queue/published/ with the result added;
on failure it moves to queue/failed/ with the error.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .hosting import media_kind

POST_TYPES = ("image", "reel", "carousel")
MAX_CAPTION = 2200
MAX_HASHTAGS = 30


def parse_time(value: str | None) -> datetime | None:
    if not value:
        return None
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:          # no offset given: treat as this computer's local time
        dt = dt.astimezone()
    return dt


@dataclass
class Post:
    type: str
    media: list[str]
    caption: str = ""
    publish_after: datetime | None = None
    ai_generated: bool = True
    share_to_feed: bool = True
    source: Path | None = None
    extra: dict = field(default_factory=dict)

    def validate(self) -> None:
        if self.type not in POST_TYPES:
            raise ValueError(f"type must be one of {POST_TYPES}, got {self.type!r}")
        if not self.media:
            raise ValueError("media is empty")
        kinds = [media_kind(m) for m in self.media]
        if self.type == "image" and (len(kinds) != 1 or kinds[0] != "image"):
            raise ValueError("an image post needs exactly one .jpg")
        if self.type == "reel" and (len(kinds) != 1 or kinds[0] != "video"):
            raise ValueError("a reel needs exactly one .mp4 or .mov")
        if self.type == "carousel" and not 2 <= len(kinds) <= 10:
            raise ValueError("a carousel needs 2 to 10 items")
        if len(self.caption) > MAX_CAPTION:
            raise ValueError(f"caption is {len(self.caption)} characters; the limit is {MAX_CAPTION}")
        hashtags = re.findall(r"#\w+", self.caption)
        if len(hashtags) > MAX_HASHTAGS:
            raise ValueError(f"caption has {len(hashtags)} hashtags; the limit is {MAX_HASHTAGS}")

    def is_due(self, now: datetime | None = None) -> bool:
        if self.publish_after is None:
            return True
        return self.publish_after <= (now or datetime.now(timezone.utc))

    @property
    def base_dir(self) -> Path:
        return self.source.parent if self.source else Path.cwd()

    @classmethod
    def from_dict(cls, data: dict, source: Path | None = None) -> "Post":
        known = {"type", "media", "caption", "publish_after", "ai_generated", "share_to_feed"}
        media = data.get("media", [])
        if isinstance(media, str):
            media = [media]
        post = cls(
            type=str(data.get("type", "")).lower(),
            media=list(media),
            caption=data.get("caption", "") or "",
            publish_after=parse_time(data.get("publish_after")),
            ai_generated=bool(data.get("ai_generated", True)),
            share_to_feed=bool(data.get("share_to_feed", True)),
            source=source,
            extra={k: v for k, v in data.items() if k not in known},
        )
        post.validate()
        return post

    @classmethod
    def load(cls, path: Path) -> "Post":
        return cls.from_dict(json.loads(path.read_text()), source=path)


def load_queue(queue_dir: Path) -> tuple[list[Post], list[tuple[Path, str]]]:
    """Return (valid posts sorted by time, [(file, error)] for invalid files)."""
    posts, errors = [], []
    for path in sorted(queue_dir.glob("*.json")):
        try:
            posts.append(Post.load(path))
        except Exception as exc:  # report bad files instead of crashing the whole run
            errors.append((path, str(exc)))
    far_past = datetime.min.replace(tzinfo=timezone.utc)
    posts.sort(key=lambda p: (p.publish_after or far_past, p.source.name if p.source else ""))
    return posts, errors


def _archive(post: Post, folder: str, update: dict) -> Path:
    assert post.source is not None
    data = json.loads(post.source.read_text())
    data.update(update)
    dest_dir = post.source.parent / folder
    dest_dir.mkdir(exist_ok=True)
    dest = dest_dir / post.source.name
    dest.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    post.source.unlink()
    return dest


def mark_published(post: Post, result: dict) -> Path:
    return _archive(post, "published", {
        "published_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "media_id": result.get("media_id"),
        "permalink": result.get("permalink"),
    })


def mark_failed(post: Post, error: str) -> Path:
    return _archive(post, "failed", {
        "failed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "error": error,
    })


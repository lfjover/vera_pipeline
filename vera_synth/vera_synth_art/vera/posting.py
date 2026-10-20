"""Turn a finished run into one Instagram post per winning painting.

Feed images have to be between 4:5 and 1.91:1. Each square painting is placed
on a white 4:5 canvas so the picture itself is not cropped. The queue file is
what `igpost run-queue` publishes; this module never publishes.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image, ImageOps

from .config import PROJECT_ROOT

FEED_SIZE = (1080, 1350)  # 4:5, the tallest ratio Instagram's feed accepts
FRAME = 84  # white border inside the 4:5 canvas, in pixels
HASHTAGS = (
    "#portrait", "#portraitphotography", "#filmphotography", "#photographer",
    "#filmlight", "#streetportrait", "#classicphotography", "#aiart",
    "#aiportrait", "#madewithai",
)

IG_KEYS = (
    "IG_ACCESS_TOKEN", "IG_USER_ID", "S3_BUCKET", "S3_ACCESS_KEY_ID",
    "S3_SECRET_ACCESS_KEY", "PUBLIC_BASE_URL",
)


def load_account(account_dir: Path | None = None) -> dict:
    account_dir = account_dir or PROJECT_ROOT
    data = {"id": account_dir.name, "name": account_dir.name, "interval_hours": 5, "ai_generated": True}
    path = account_dir / "account.json"
    if path.exists():
        data.update(json.loads(path.read_text()))
    return data


def crop_for_feed(src: Path, dest: Path) -> Path:
    """Place a square painting on a 4:5 JPEG with a white mat. The painting is not cropped."""
    side = min(FEED_SIZE) - 2 * FRAME
    with Image.open(src) as img:
        painting = ImageOps.contain(img.convert("RGB"), (side, side), method=Image.LANCZOS)
    canvas = Image.new("RGB", FEED_SIZE, (255, 255, 255))
    x = (FEED_SIZE[0] - painting.width) // 2
    y = (FEED_SIZE[1] - painting.height) // 2
    canvas.paste(painting, (x, y))
    dest.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest, format="JPEG", quality=92)
    return dest


def build_caption(item: dict) -> str:
    """Hashtags only. The photographer's name stays off the caption; the AI disclosure is the platform label."""
    return " ".join(HASHTAGS)


def _aware(when: datetime) -> datetime:
    return when if when.tzinfo else when.astimezone()


def publish_times(count: int, now: datetime, interval_hours: float, queue_dir: Path) -> list[str]:
    """One slot every `interval_hours`, starting after the latest post already queued or published."""
    latest = None
    for folder in (queue_dir, queue_dir / "published"):
        if not folder.exists():
            continue
        for path in folder.glob("*.json"):
            try:
                raw = json.loads(path.read_text()).get("publish_after")
            except (OSError, json.JSONDecodeError):
                continue
            if not raw:
                continue
            when = _aware(datetime.fromisoformat(raw))
            if latest is None or when > latest:
                latest = when
    gap = timedelta(hours=interval_hours)
    start = _aware(now)
    if latest is not None and latest + gap > start:
        start = latest + gap
    return [(start + gap * i).isoformat(timespec="minutes") for i in range(count)]


def _existing_queue_file(queue_dir: Path, name: str) -> Path | None:
    for folder in (queue_dir, queue_dir / "published", queue_dir / "failed"):
        path = folder / name
        if path.exists():
            return path
    return None


def enqueue_run(run_dir: Path, *, now: datetime | None = None, account_dir: Path | None = None) -> list[Path]:
    """Write one queue file per winner. A file that already exists is left as it is."""
    run_dir = Path(run_dir)
    account_dir = account_dir or run_dir.parent.parent
    account = load_account(account_dir)
    queue_dir = account_dir / "queue"
    queue_dir.mkdir(parents=True, exist_ok=True)
    prompts = json.loads((run_dir / "prompts.json").read_text())
    scores = json.loads((run_dir / "scores.json").read_text())
    winners = [item for item in prompts["items"] if item["slug"] in scores]
    if not winners:
        raise ValueError(f"{run_dir.name} has no winners to post")

    paths = []
    pending = []
    feed = run_dir / "feed"
    for i, item in enumerate(winners, 1):
        name = f"{run_dir.name}_{i:02d}.json"
        existing = _existing_queue_file(queue_dir, name)
        if existing:
            paths.append((i, existing))
            continue
        pending.append((i, item, name))
    times = publish_times(len(pending), now or datetime.now(), float(account.get("interval_hours", 5)), queue_dir)
    for (i, item, name), when in zip(pending, times):
        src = run_dir / item["slug"] / scores[item["slug"]]["winner"]
        dest = feed / f"{i:02d}.jpg"
        if not dest.exists():
            crop_for_feed(src, dest)
        queue_path = queue_dir / name
        payload = {
            "type": "image",
            "media": [Path(os.path.relpath(dest, queue_path.parent)).as_posix()],
            "caption": build_caption(item),
            "publish_after": when,
            "ai_generated": bool(account.get("ai_generated", True)),
            "account": account.get("id", account_dir.name),
            "run": run_dir.name,
            "photographer": item["slug"],
        }
        queue_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        paths.append((i, queue_path))
    return [path for _, path in sorted(paths)]

import json
from datetime import datetime, timezone

import pytest

from igpost.hosting import DryRunHost, resolve_media
from igpost.posts import Post, load_queue, mark_failed, mark_published


def write(path, data):
    path.write_text(json.dumps(data))
    return path


def test_validation_rules():
    Post.from_dict({"type": "image", "media": ["a.jpg"]})
    Post.from_dict({"type": "reel", "media": "clip.mp4"})
    with pytest.raises(ValueError, match="JPEG"):
        Post.from_dict({"type": "image", "media": ["a.png"]})
    with pytest.raises(ValueError, match="reel"):
        Post.from_dict({"type": "reel", "media": ["a.jpg"]})
    with pytest.raises(ValueError, match="2 to 10"):
        Post.from_dict({"type": "carousel", "media": ["a.jpg"]})
    with pytest.raises(ValueError, match="hashtags"):
        Post.from_dict({"type": "image", "media": ["a.jpg"], "caption": " ".join(f"#t{i}" for i in range(31))})


def test_ai_label_defaults_on():
    assert Post.from_dict({"type": "image", "media": ["a.jpg"]}).ai_generated is True


def test_queue_orders_by_time_and_reports_bad_files(tmp_path):
    write(tmp_path / "b.json", {"type": "image", "media": ["x.jpg"], "publish_after": "2030-01-01T09:00:00Z"})
    write(tmp_path / "a.json", {"type": "image", "media": ["x.jpg"], "publish_after": "2026-01-01T09:00:00-05:00"})
    write(tmp_path / "bad.json", {"type": "story", "media": ["x.jpg"]})
    posts, errors = load_queue(tmp_path)
    assert [p.source.name for p in posts] == ["a.json", "b.json"]
    assert errors[0][0].name == "bad.json"
    now = datetime(2027, 1, 1, tzinfo=timezone.utc)
    assert [p.is_due(now) for p in posts] == [True, False]


def test_mark_published_and_failed_move_files(tmp_path):
    p1 = Post.load(write(tmp_path / "one.json", {"type": "image", "media": ["x.jpg"]}))
    p2 = Post.load(write(tmp_path / "two.json", {"type": "image", "media": ["x.jpg"]}))
    done = mark_published(p1, {"media_id": "M1", "permalink": "https://instagram.com/p/1"})
    bad = mark_failed(p2, "boom")
    assert not (tmp_path / "one.json").exists() and not (tmp_path / "two.json").exists()
    assert json.loads(done.read_text())["media_id"] == "M1"
    assert json.loads(bad.read_text())["error"] == "boom"
    assert load_queue(tmp_path) == ([], [])


def test_resolve_media_relative_to_queue_file(tmp_path):
    (tmp_path / "media").mkdir()
    (tmp_path / "media" / "pic.jpg").write_bytes(b"jpg")
    url, is_video = resolve_media("media/pic.jpg", DryRunHost("https://cdn.test"), tmp_path)
    assert url == "https://cdn.test/<dry-run>/pic.jpg" and is_video is False
    assert resolve_media("https://cdn.test/v.mp4", DryRunHost(None), tmp_path) == ("https://cdn.test/v.mp4", True)
    with pytest.raises(FileNotFoundError):
        resolve_media("media/missing.jpg", DryRunHost(None), tmp_path)

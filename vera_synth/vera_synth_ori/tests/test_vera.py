import base64
import hashlib
import hmac
import json
import random
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from PIL import Image

from vera import photographers as ph
from vera.claude import ClaudeClient, ClaudeError, extract_json
from vera.config import Settings
from vera.kling import KlingClient, KlingError, make_jwt
from vera.pipeline import choose_photographers, run, weighted_total
from vera.posting import enqueue_run


class FakeResponse:
    def __init__(self, body=None, status=200, content=b""):
        self._body, self.status_code, self.content = body, status, content
        self.text = json.dumps(body) if body is not None else ""

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.responses.pop(0)

    def post(self, url, **kw):
        return self.request("POST", url, **kw)

    def get(self, url, **kw):
        return self.request("GET", url, **kw)


def settings(tmp_path):
    return Settings(None, "fal-ai/test", None, None, None, "https://kling.test", "kling-v2-1", None, "claude-test", tmp_path / "runs")


# ------------------------------------------------------------------ kling
def test_jwt_is_hs256_signed_with_secret():
    token = make_jwt("AK", "SK", now=1000)
    head, payload, sig = token.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    assert json.loads(base64.urlsafe_b64decode(pad(head))) == {"alg": "HS256", "typ": "JWT"}
    assert json.loads(base64.urlsafe_b64decode(pad(payload))) == {"iss": "AK", "exp": 2800, "nbf": 995}
    expected = hmac.new(b"SK", f"{head}.{payload}".encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64decode(pad(sig)) == expected


def test_kling_create_and_wait():
    session = FakeSession([
        FakeResponse({"code": 0, "data": {"task_id": "T1", "task_status": "submitted"}}),
        FakeResponse({"code": 0, "data": {"task_status": "processing"}}),
        FakeResponse({"code": 0, "data": {"task_status": "succeed", "task_result": {"images": [
            {"index": 1, "url": "https://x/b.png"}, {"index": 0, "url": "https://x/a.png"}]}}}),
    ])
    sleeps = []
    k = KlingClient("AK", "SK", "https://kling.test/", session=session, sleep=sleeps.append, clock=lambda: 1000)
    assert k.create_image_task("a portrait", "blurry", n=5) == "T1"
    method, url, kw = session.calls[0]
    assert (method, url) == ("POST", "https://kling.test/v1/images/generations")
    assert kw["json"] == {"model_name": "kling-v2-1", "prompt": "a portrait", "n": 5,
                          "aspect_ratio": "9:16", "negative_prompt": "blurry"}
    assert kw["headers"]["Authorization"].startswith("Bearer ")
    assert k.wait_for_images("T1") == ["https://x/a.png", "https://x/b.png"]
    assert session.calls[1][1] == "https://kling.test/v1/images/generations/T1"
    assert len(sleeps) == 1


def test_kling_errors():
    k = KlingClient("AK", "SK", session=FakeSession([FakeResponse({"code": 1102, "message": "balance not enough"}, 429)]))
    with pytest.raises(KlingError, match="balance not enough"):
        k.create_image_task("x")
    k = KlingClient("AK", "SK", session=FakeSession([FakeResponse({"code": 0, "data": {
        "task_status": "failed", "task_status_msg": "content flagged"}})]))
    with pytest.raises(KlingError, match="content flagged"):
        k.wait_for_images("T")
    with pytest.raises(ValueError):
        k.create_image_task("x", n=12)


def test_kling_single_api_key_is_sent_as_bearer():
    session = FakeSession([FakeResponse({"code": 0, "data": {"task_id": "T9"}})])
    k = KlingClient(api_key="kk-123", session=session)
    assert k.create_image_task("x") == "T9"
    assert session.calls[0][2]["headers"]["Authorization"] == "Bearer kk-123"
    with pytest.raises(ValueError):
        KlingClient()


def test_settings_accept_either_kind_of_kling_key(tmp_path):
    s = settings(tmp_path)
    s.anthropic_api_key = "a"
    assert s.missing() == ["FAL_KEY (or KLING_API_KEY)"]
    s.kling_api_key = "k"
    assert s.missing() == []
    s.kling_api_key, s.kling_access_key, s.kling_secret_key = None, "ak", "sk"
    assert s.missing() == []


def test_fal_queue_flow_tops_up_missing_images(tmp_path):
    from vera.fal import FalClient
    session = FakeSession([
        FakeResponse({"request_id": "R1", "status_url": "https://q/s1", "response_url": "https://q/r1"}),
        FakeResponse({"status": "IN_QUEUE"}),
        FakeResponse({"status": "COMPLETED"}),
        FakeResponse({"images": [{"url": "https://cdn/1.png"}]}),            # asked for 3, got 1
        FakeResponse({"request_id": "R2", "status_url": "https://q/s2", "response_url": "https://q/r2"}),
        FakeResponse({"status": "COMPLETED"}),
        FakeResponse({"images": [{"url": "https://cdn/2.png"}, {"url": "https://cdn/3.png"}]}),
    ])
    sleeps = []
    fal = FalClient("FK", "fal-ai/kling-image/o3/text-to-image", session=session, sleep=sleeps.append)
    task = fal.create_image_task("portrait", "blurry", n=3)
    method, url, kw = session.calls[0]
    assert (method, url) == ("POST", "https://queue.fal.run/fal-ai/kling-image/o3/text-to-image")
    assert kw["headers"]["Authorization"] == "Key FK"
    assert kw["json"] == {"prompt": "portrait Avoid: blurry", "num_images": 3, "aspect_ratio": "9:16"}
    assert fal.wait_for_images(task) == ["https://cdn/1.png", "https://cdn/2.png", "https://cdn/3.png"]
    assert session.calls[4][2]["json"]["num_images"] == 2 and len(sleeps) == 1


def test_fal_final_frame_sends_the_photo(tmp_path):
    from vera.fal import FalClient
    src = tmp_path / "c1.jpg"
    Image.new("RGB", (80, 140), (20, 30, 40)).save(src)
    session = FakeSession([
        FakeResponse({"request_id": "F1", "status_url": "https://q/s", "response_url": "https://q/r"}),
    ])
    fal = FalClient("FK", session=session, sleep=lambda s: None)
    fal.create_final_frame("@Image same person, cool side light", src)
    method, url, kw = session.calls[0]
    assert (method, url) == ("POST", "https://queue.fal.run/fal-ai/kling-image/o3/image-to-image")
    body = kw["json"]
    assert body["prompt"].startswith("@Image")
    assert body["image_urls"][0].startswith("data:image/jpeg;base64,")
    assert body["aspect_ratio"] == "9:16" and body["num_images"] == 1


def test_fal_errors_are_readable():
    from vera.fal import FalClient, FalError
    session = FakeSession([FakeResponse({"detail": [{"loc": ["body", "aspect_ratio"], "msg": "bad value"}]}, 422)])
    with pytest.raises(FalError, match="aspect_ratio: bad value"):
        FalClient("FK", session=session).create_image_task("x")
    session = FakeSession([FakeResponse({"detail": "Not authenticated"}, 401)])
    with pytest.raises(FalError, match="rejected the key"):
        FalClient("FK", session=session).ping()
    FalClient("FK", session=FakeSession([FakeResponse({"detail": "not found"}, 404)])).ping()


def test_settings_prefer_fal_when_key_set(tmp_path):
    from vera.fal import FalClient
    s = settings(tmp_path)
    s.fal_key, s.kling_api_key = "fk", "kk"
    assert s.image_provider == "fal" and isinstance(s.image_client(), FalClient)
    s.fal_key = None
    assert s.image_provider == "kling" and isinstance(s.image_client(), KlingClient)


# ----------------------------------------------------------------- claude
def test_extract_json_ignores_prose_and_fences():
    assert extract_json('Sure!\n```json\n[{"slug": "a"}]\n```') == [{"slug": "a"}]
    assert extract_json('{"scores": [1]} trailing') == {"scores": [1]}
    with pytest.raises(ClaudeError):
        extract_json("no json here")


def test_claude_write_prompts_keeps_order_and_requires_all():
    picks = [ph.get("fan-ho"), ph.get("saul-leiter")]
    reply = [{"slug": "saul-leiter", "subject": "s", "prompt": "p2", "negative_prompt": "n2"},
             {"slug": "fan-ho", "subject": "f", "prompt": "p1"}]
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(reply)}]})])
    out = ClaudeClient("KEY", "m", session=session).write_prompts(picks)
    assert [o["slug"] for o in out] == ["fan-ho", "saul-leiter"]
    assert out[0]["negative_prompt"] == ""
    headers = session.calls[0][2]["headers"]
    assert headers["x-api-key"] == "KEY" and headers["anthropic-version"] == "2023-06-01"
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(reply[:1])}]})])
    with pytest.raises(ClaudeError, match="fan-ho"):
        ClaudeClient("KEY", "m", session=session).write_prompts(picks)


def test_claude_prompts_accept_wrapped_or_renamed_items():
    picks = [ph.get("sergio-larrain"), ph.get("fan-ho")]
    wrapped = {"prompts": [{"photographer": "Sergio Larraín", "prompt": "p1"},
                           {"slug": "Fan Ho", "prompt": "p2"}]}
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(wrapped)}]})])
    out = ClaudeClient("K", "m", session=session).write_prompts(picks)
    assert [o["prompt"] for o in out] == ["p1", "p2"]
    by_position = [{"prompt": "a"}, {"prompt": "b"}]
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(by_position)}]})])
    assert [o["prompt"] for o in ClaudeClient("K", "m", session=session).write_prompts(picks)] == ["a", "b"]
    session = FakeSession([FakeResponse({"stop_reason": "max_tokens", "content": [{"type": "text", "text": "[{"}]})])
    with pytest.raises(ClaudeError, match="cut off"):
        ClaudeClient("K", "m", session=session).write_prompts(picks)


def test_direction_reaches_prompt_writing_and_scoring(tmp_path):
    reply = [{"slug": "fan-ho", "prompt": "p"}]
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(reply)}]})])
    ClaudeClient("K", "m", session=session).write_prompts([ph.get("fan-ho")], direction="neon gels")
    assert "neon gels" in session.calls[0][2]["json"]["messages"][0]["content"]
    img = tmp_path / "c1.jpg"
    Image.new("RGB", (10, 10)).save(img)
    scores = {"scores": [{"image": 1, "realism": 5, "face_hands": 5, "style": 5, "animation": 5}]}
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(scores)}]})])
    ClaudeClient("K", "m", session=session).score(ph.get("fan-ho"), [img], direction="neon gels")
    assert "neon gels" in session.calls[0][2]["json"]["system"]


def test_direction_file_and_resume_keep_direction(tmp_path):
    from vera.pipeline import read_direction
    f = tmp_path / "direction.txt"
    f.write_text("# comment\n\nExperimental light:\n colored gels\n")
    assert read_direction(f) == "Experimental light: colored gels"
    assert read_direction(tmp_path / "missing.txt") is None
    s = settings(tmp_path)
    first = run(s, dry_run=True, only=["fan-ho"], direction="colored gels", log=lambda m: None,
                now=datetime(2026, 1, 1))
    prompts = json.loads((Path(first["run_dir"]) / "prompts.json").read_text())
    assert prompts["direction"] == "colored gels" and "colored gels" in prompts["items"][0]["prompt"]
    again = run(s, dry_run=True, resume=Path(first["run_dir"]), direction="something else", log=lambda m: None)
    prompts = json.loads((Path(again["run_dir"]) / "prompts.json").read_text())
    assert prompts["direction"] == "colored gels"


def test_claude_score_sends_images(tmp_path):
    paths = []
    for i in range(2):
        p = tmp_path / f"c{i + 1}.jpg"
        Image.new("RGB", (2000, 3000), (i * 100, 50, 50)).save(p)
        paths.append(p)
    reply = {"scores": [{"image": 2, "realism": 9, "face_hands": 9, "style": 8, "animation": 7, "reason": "b"},
                        {"image": 1, "realism": 5, "face_hands": 5, "style": 5, "animation": 5, "reason": "a"}]}
    session = FakeSession([FakeResponse({"content": [{"type": "text", "text": json.dumps(reply)}]})])
    scores = ClaudeClient("KEY", "m", session=session).score(ph.get("fan-ho"), paths)
    assert [s["reason"] for s in scores] == ["a", "b"]
    content = session.calls[0][2]["json"]["messages"][0]["content"]
    assert sum(1 for b in content if b["type"] == "image") == 2


# --------------------------------------------------------------- pipeline
def test_weighted_total():
    assert weighted_total({"realism": 10, "face_hands": 10, "style": 10, "animation": 10}) == 10
    assert weighted_total({"realism": 10}) == 3.5
    assert weighted_total({"realism": "bad", "style": 20}) == 2.5


def test_choose_avoids_recent_runs():
    recent = [[p.slug for p in ph.PHOTOGRAPHERS[:9]], [p.slug for p in ph.PHOTOGRAPHERS[9:18]]]
    picked = choose_photographers(9, recent, random.Random(1))
    assert len({p.slug for p in picked}) == 9
    assert not {p.slug for p in picked} & set(recent[0] + recent[1])  # recent ones are skipped
    assert [p.slug for p in choose_photographers(2, [], random.Random(1), only=["fan-ho", "irving-penn"])] == \
        ["fan-ho", "irving-penn"]
    with pytest.raises(ValueError):
        choose_photographers(2, [], random.Random(1), only=["nobody"])


def test_every_photographer_is_marked_with_death_year():
    assert len(ph.PHOTOGRAPHERS) >= 70
    for p in ph.PHOTOGRAPHERS:
        assert p.nationality and p.style
        born, died = p.years.split("–")
        assert born.isdigit() and died.isdigit() and int(died) > int(born)
    assert len({p.slug for p in ph.PHOTOGRAPHERS}) == len(ph.PHOTOGRAPHERS)


def test_dry_run_end_to_end_makes_grid(tmp_path):
    s = settings(tmp_path)
    summary = run(s, dry_run=True, rng=random.Random(7), now=datetime(2026, 10, 19, 15, 30), log=lambda m: None)
    run_dir = Path(summary["run_dir"])
    assert run_dir.name == "2026-10-19_1530_dry"
    assert summary["errors"] == {} and len(summary["finished"]) == 9
    grid = Image.open(summary["grid"])
    assert grid.size[0] > 1600 and grid.size[1] > grid.size[0]
    scores = json.loads((run_dir / "scores.json").read_text())
    for slug, s_ in scores.items():
        assert len(s_["candidates"]) == 3
        assert s_["total"] == max(c["total"] for c in s_["candidates"])
        assert (run_dir / slug / "candidates.jpg").exists()
        assert (run_dir / slug / s_["winner"]).exists()
        assert s_["final"] == "final.jpg"
        assert (run_dir / slug / "final.jpg").exists()
        assert (run_dir / slug / "pair.jpg").exists()
        assert not list((run_dir / slug).glob("raw_*"))
    assert not (s.runs_dir / "history.json").exists()  # dry runs don't count as history


class CountingKling:
    """Fails for one photographer the first time, to test --resume."""

    def __init__(self, fail_slug_prompt=None):
        from vera.pipeline import OfflineKling
        self.inner, self.created, self.fail = OfflineKling(), 0, fail_slug_prompt

    def create_image_task(self, prompt, negative_prompt=None, n=5, aspect_ratio="9:16"):
        if self.fail and self.fail in prompt:
            raise KlingError("network down")
        self.created += 1
        return self.inner.create_image_task(prompt, negative_prompt, n, aspect_ratio)

    def wait_for_images(self, task_id, **kw):
        return self.inner.wait_for_images(task_id, **kw)

    def create_final_frame(self, prompt, image, aspect_ratio="9:16"):
        return self.inner.create_final_frame(prompt, image, aspect_ratio)

    def download(self, url, dest):
        return self.inner.download(url, dest)


def test_successful_run_queues_one_post_per_winner(tmp_path):
    from vera.pipeline import OfflineClaude, OfflineKling
    s = settings(tmp_path)
    summary = run(s, only=["fan-ho", "irving-penn"], kling=OfflineKling(), claude=OfflineClaude(),
                  now=datetime(2026, 10, 19, 9, 0), log=lambda m: None)
    queued = [Path(p) for p in summary["queued"]]
    assert len(queued) == 2
    post = json.loads(queued[0].read_text())
    assert post["type"] == "image" and post["ai_generated"] is True
    assert post["account"] == tmp_path.name
    assert len(post["media"]) == 1 and post["media"][0].endswith(".jpg")
    assert post["caption"].count("#") == 10
    assert "Fan Ho" not in post["caption"]
    assert "#madewithai" in post["caption"]
    second = json.loads(queued[1].read_text())
    gap = datetime.fromisoformat(second["publish_after"]) - datetime.fromisoformat(post["publish_after"])
    assert gap == timedelta(hours=5)
    img = Image.open((queued[0].parent / post["media"][0]).resolve())
    assert img.size == (1080, 1350)
    assert img.getpixel((0, 0)) == (255, 255, 255)
    again = enqueue_run(Path(summary["run_dir"]), now=datetime(2026, 10, 19, 9, 0))
    assert again == queued


def test_failed_photographer_can_be_resumed_without_regenerating(tmp_path):
    from vera.pipeline import OfflineClaude
    s = settings(tmp_path)
    fan = ph.get("fan-ho")
    k1 = CountingKling(fail_slug_prompt=fan.style[:30])
    first = run(s, only=["fan-ho", "irving-penn", "saul-leiter"], kling=k1, claude=OfflineClaude(),
                now=datetime(2026, 10, 19, 9, 0), log=lambda m: None)
    assert set(first["errors"]) == {"fan-ho"} and k1.created == 2
    history = json.loads((s.runs_dir / "history.json").read_text())
    assert history["runs"][0]["photographers"] == ["fan-ho", "irving-penn", "saul-leiter"]

    k2 = CountingKling()
    second = run(s, resume=Path(first["run_dir"]), kling=k2, claude=OfflineClaude(), log=lambda m: None)
    assert second["errors"] == {} and k2.created == 1  # only Fan Ho was generated again
    assert len(second["finished"]) == 3
    assert len(json.loads((s.runs_dir / "history.json").read_text())["runs"]) == 1

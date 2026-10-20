import pytest

from igpost.client import InstagramAPIError, InstagramClient


class FakeResponse:
    def __init__(self, body, status=200):
        self._body, self.status_code, self.text = body, status, str(body)

    def json(self):
        return self._body


class FakeSession:
    """Replays canned responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, params=None, data=None, timeout=None):
        self.calls.append({"method": method, "url": url, "params": params or {}, "data": data or {}})
        return self.responses.pop(0)


def make_client(responses):
    session = FakeSession(responses)
    sleeps = []
    client = InstagramClient("TOKEN", "1784", session=session, sleep=sleeps.append)
    return client, session, sleeps


def test_post_image_creates_container_with_ai_label_then_publishes():
    client, session, _ = make_client([
        FakeResponse({"id": "C1"}),
        FakeResponse({"status_code": "FINISHED"}),
        FakeResponse({"id": "M1"}),
        FakeResponse({"id": "M1", "permalink": "https://instagram.com/p/abc"}),
    ])
    result = client.post_image("https://cdn.example.com/a.jpg", "hello")
    assert result == {"media_id": "M1", "container_id": "C1", "permalink": "https://instagram.com/p/abc",
                      "media": {"id": "M1", "permalink": "https://instagram.com/p/abc"}}
    create = session.calls[0]
    assert create["method"] == "POST"
    assert create["url"] == "https://graph.instagram.com/v25.0/1784/media"
    assert create["data"] == {"image_url": "https://cdn.example.com/a.jpg", "caption": "hello",
                              "is_ai_generated": "true", "access_token": "TOKEN"}
    assert session.calls[2]["url"].endswith("/1784/media_publish")
    assert session.calls[2]["data"]["creation_id"] == "C1"


def test_reel_container_fields():
    client, session, _ = make_client([FakeResponse({"id": "C2"})])
    client.create_reel_container("https://cdn.example.com/v.mp4", "cap", ai_generated=False)
    data = session.calls[0]["data"]
    assert data["media_type"] == "REELS"
    assert data["video_url"] == "https://cdn.example.com/v.mp4"
    assert data["is_ai_generated"] == "false"
    assert data["share_to_feed"] == "true"
    assert "cover_url" not in data


def test_wait_polls_until_finished():
    client, session, sleeps = make_client([
        FakeResponse({"status_code": "IN_PROGRESS"}),
        FakeResponse({"status_code": "IN_PROGRESS"}),
        FakeResponse({"status_code": "FINISHED"}),
    ])
    client.wait_until_ready("C3", timeout=300, interval=30)
    assert len(session.calls) == 3
    assert sleeps == [30, 30]
    assert session.calls[0]["params"]["fields"] == "status_code,status"


def test_wait_raises_on_error_status():
    client, _, _ = make_client([FakeResponse({"status_code": "ERROR", "status": "Error: bad aspect ratio"})])
    with pytest.raises(InstagramAPIError, match="bad aspect ratio"):
        client.wait_until_ready("C4")


def test_wait_times_out():
    client, session, _ = make_client([FakeResponse({"status_code": "IN_PROGRESS"})] * 3)
    with pytest.raises(InstagramAPIError, match="not ready"):
        client.wait_until_ready("C5", timeout=20, interval=10)
    assert len(session.calls) == 3


def test_api_error_message_is_surfaced():
    client, _, _ = make_client([FakeResponse(
        {"error": {"message": "Invalid OAuth access token", "code": 190}}, status=400)])
    with pytest.raises(InstagramAPIError, match="Invalid OAuth") as info:
        client.me()
    assert info.value.status == 400


def test_carousel_labels_only_parent_container():
    client, session, _ = make_client([
        FakeResponse({"id": "K1"}), FakeResponse({"id": "K2"}),
        FakeResponse({"id": "P1"}), FakeResponse({"status_code": "FINISHED"}),
        FakeResponse({"id": "M9"}), FakeResponse({"id": "M9"}),
    ])
    client.post_carousel([("https://x/a.jpg", False), ("https://x/b.jpg", False)], "two")
    child, parent = session.calls[0]["data"], session.calls[2]["data"]
    assert child["is_carousel_item"] == "true" and "is_ai_generated" not in child
    assert parent["media_type"] == "CAROUSEL" and parent["children"] == "K1,K2"
    assert parent["is_ai_generated"] == "true"


def test_refresh_token_uses_unversioned_endpoint():
    client, session, _ = make_client([FakeResponse({"access_token": "NEW", "expires_in": 5184000})])
    assert client.refresh_token()["access_token"] == "NEW"
    assert session.calls[0]["url"] == "https://graph.instagram.com/refresh_access_token"
    assert session.calls[0]["params"]["grant_type"] == "ig_refresh_token"

import pytest

from vidgen.comfy import ComfyClient, ComfyError, output_files


class FakeResponse:
    def __init__(self, body=None, status=200, content=b""):
        self._body, self.status_code, self.text, self.content = body, status, str(body), content

    def json(self):
        if self._body is None:
            raise ValueError("no json")
        return self._body

    def iter_content(self, size):
        yield self.content


class FakeSession:
    """Replays canned responses and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, headers=None, timeout=None, **kwargs):
        self.calls.append({"method": method, "url": url, "headers": headers, **kwargs})
        return self.responses.pop(0)


def make_client(responses, **kw):
    session = FakeSession(responses)
    sleeps = []
    ticks = iter(range(0, 100000, 5))
    client = ComfyClient("http://gpu:8188/", session=session, sleep=sleeps.append,
                         clock=lambda: next(ticks), **kw)
    return client, session, sleeps


def test_queue_posts_prompt_with_client_id_and_token():
    client, session, _ = make_client([FakeResponse({"prompt_id": "P1", "node_errors": {}})], token="T")
    assert client.queue({"1": {"class_type": "X", "inputs": {}}}) == "P1"
    call = session.calls[0]
    assert call["url"] == "http://gpu:8188/prompt"
    assert call["json"]["client_id"] == client.client_id
    assert call["headers"] == {"Authorization": "Bearer T"}


def test_queue_rejection_reports_node_errors():
    body = {"error": {"message": "Prompt outputs failed validation"},
            "node_errors": {"7": {"class_type": "UNETLoader",
                                  "errors": [{"message": "Value not in list", "details": "unet_name: 'x'"}]}}}
    client, _, _ = make_client([FakeResponse(body, status=400)])
    with pytest.raises(ComfyError, match=r"node 7 \(UNETLoader\): Value not in list unet_name"):
        client.queue({})


def test_wait_polls_until_history_has_entry():
    done = {"P1": {"status": {"status_str": "success", "completed": True}, "outputs": {}}}
    client, session, sleeps = make_client([FakeResponse({}), FakeResponse({}), FakeResponse(done)])
    assert client.wait("P1", poll=2) == done["P1"]
    assert sleeps == [2, 2]
    assert session.calls[0]["url"] == "http://gpu:8188/history/P1"


def test_wait_raises_execution_error():
    failed = {"P1": {"status": {"status_str": "error", "completed": False, "messages": [
        ["execution_start", {}],
        ["execution_error", {"node_id": "3", "node_type": "KSampler", "exception_message": "CUDA out of memory\n"}],
    ]}}}
    client, _, _ = make_client([FakeResponse(failed)])
    with pytest.raises(ComfyError, match="KSampler \\(node 3\\): CUDA out of memory"):
        client.wait("P1")


def test_wait_times_out():
    client, _, _ = make_client([FakeResponse({})] * 10)
    with pytest.raises(ComfyError, match="timed out"):
        client.wait("P1", timeout=12, poll=1)


def test_upload_image_returns_subfolder_path(tmp_path):
    img = tmp_path / "face.jpg"
    img.write_bytes(b"jpg")
    client, session, _ = make_client([FakeResponse({"name": "face.jpg", "subfolder": "in", "type": "input"})])
    assert client.upload_image(img) == "in/face.jpg"
    assert session.calls[0]["data"] == {"overwrite": "true"}


def test_download_writes_file(tmp_path):
    client, session, _ = make_client([FakeResponse(content=b"MP4DATA")])
    dest = client.download({"filename": "H3_00001.mp4", "subfolder": "video", "type": "output"}, tmp_path, "a.mp4")
    assert dest.read_bytes() == b"MP4DATA"
    assert session.calls[0]["params"] == {"filename": "H3_00001.mp4", "subfolder": "video", "type": "output"}


def test_output_files_keeps_saved_videos_only():
    entry = {"outputs": {
        "9": {"images": [{"filename": "H3_00001.mp4", "subfolder": "", "type": "output", "animated": [True]}]},
        "10": {"gifs": [{"filename": "prev.mp4", "type": "temp"}]},
        "11": {"images": [{"filename": "frame.png", "type": "output"}]},
    }}
    assert [f["filename"] for f in output_files(entry)] == ["H3_00001.mp4"]


def test_model_options_handles_both_combo_styles():
    old = {"UNETLoader": {"input": {"required": {"unet_name": [["a.safetensors", "h3.safetensors"]]}}}}
    new = {"UNETLoader": {"input": {"required": {"unet_name": ["COMBO", {"options": ["h3.safetensors"]}]}}}}
    client, _, _ = make_client([FakeResponse(old), FakeResponse(new)])
    assert client.model_options("UNETLoader", "unet_name") == ["a.safetensors", "h3.safetensors"]
    assert client.model_options("UNETLoader", "unet_name") == ["h3.safetensors"]

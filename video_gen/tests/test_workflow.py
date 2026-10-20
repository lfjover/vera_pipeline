import json

import pytest

from vidgen.cli import main
from vidgen.workflow import ambiguous_prompts, apply, guess_bindings, load_bindings, load_workflow, parse_override

WORKFLOW = {
    "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_fl2va_pruned_int8_convrot.safetensors"}},
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["2", 0]},
          "_meta": {"title": "Positive Prompt"}},
    "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry", "clip": ["2", 0]},
          "_meta": {"title": "Negative Prompt"}},
    "12": {"class_type": "LoadImage", "inputs": {"image": "start.png"}, "_meta": {"title": "Start Frame"}},
    "13": {"class_type": "LoadImage", "inputs": {"image": "end.png"}, "_meta": {"title": "End Frame"}},
    "20": {"class_type": "EmptyH3Latent", "inputs": {"width": 1344, "height": 768, "length": 121}},
    "30": {"class_type": "KSampler", "inputs": {"seed": 1, "steps": 20, "model": ["1", 0]}},
    "40": {"class_type": "SaveVideo", "inputs": {"video": ["35", 0], "filename_prefix": "H3"}},
}


@pytest.fixture
def wf_file(tmp_path):
    path = tmp_path / "h3_i2v.json"
    path.write_text(json.dumps(WORKFLOW))
    return path


def test_guess_bindings():
    b = guess_bindings(WORKFLOW)
    assert b["prompt"] == ["6.text"]
    assert b["negative"] == ["7.text"]
    assert b["image"] == ["12.image"]
    assert b["end_image"] == ["13.image"]
    assert b["seed"] == ["30.seed"]
    assert (b["width"], b["height"], b["length"], b["steps"]) == (["20.width"], ["20.height"], ["20.length"], ["30.steps"])


def test_two_unlabelled_prompts_are_not_guessed():
    wf = {"1": {"class_type": "CLIPTextEncode", "inputs": {"text": "a"}},
          "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "b"}}}
    assert "prompt" not in guess_bindings(wf)
    assert ambiguous_prompts(wf) == ["1.text", "2.text"]


def test_apply_writes_values_without_touching_original():
    out = apply(WORKFLOW, guess_bindings(WORKFLOW), {"prompt": "a dog", "seed": 42, "width": 768, "length": None},
                overrides={"30.steps": 8})
    assert out["6"]["inputs"]["text"] == "a dog"
    assert out["30"]["inputs"] == {"seed": 42, "steps": 8, "model": ["1", 0]}
    assert out["20"]["inputs"]["length"] == 121
    assert WORKFLOW["6"]["inputs"]["text"] == "a cat"


def test_apply_missing_binding_is_an_error():
    with pytest.raises(ValueError, match="no input bound to 'fps'"):
        apply(WORKFLOW, guess_bindings(WORKFLOW), {"fps": 24})


def test_bindings_file_overrides_guess_and_is_validated(wf_file):
    side = wf_file.with_name("h3_i2v.bindings.json")
    side.write_text(json.dumps({"prompt": "7.text"}))
    assert load_bindings(wf_file, WORKFLOW) == ({"prompt": ["7.text"]}, True)
    side.write_text(json.dumps({"prompt": "7.nope"}))
    with pytest.raises(ValueError, match="has no input 'nope'"):
        load_bindings(wf_file, WORKFLOW)


def test_ui_format_workflow_is_rejected(tmp_path):
    path = tmp_path / "ui.json"
    path.write_text(json.dumps({"nodes": [], "links": []}))
    with pytest.raises(ValueError, match="Export \\(API\\)"):
        load_workflow(path)


def test_parse_override():
    assert parse_override("30.cfg=4.5") == ("30.cfg", 4.5)
    assert parse_override("1.unet_name=h3.safetensors") == ("1.unet_name", "h3.safetensors")


def test_generate_dry_run(wf_file, tmp_path, capsys):
    img = tmp_path / "face.jpg"
    img.write_bytes(b"x")
    code = main(["--env-file", str(tmp_path / "none.env"), "generate", str(wf_file), "-p", "she smiles",
                 "-i", str(img), "--size", "768x1344", "--seed", "5", "--count", "2", "--dry-run"])
    out = capsys.readouterr().out
    assert code == 0
    assert "would queue 2 run(s)" in out
    assert "5, 6" in out and "6.text" in out and "<upload face.jpg>" in out

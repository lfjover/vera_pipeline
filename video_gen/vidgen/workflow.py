"""ComfyUI workflows (API format) and the "bindings" that say where our parameters go.

A workflow exported with *Workflow → Export (API)* is a dict of
{node_id: {"class_type": ..., "inputs": {...}, "_meta": {"title": ...}}}.
Bindings map a parameter name to one or more "node_id.input_name" targets:

    {"prompt": ["12.text"], "image": ["31.image"], "seed": ["40.seed", "41.noise_seed"]}

They're read from <workflow>.bindings.json when it exists; otherwise they are
guessed from the node types and titles (run `python -m vidgen inspect` to see).
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

PARAMS = ("prompt", "negative", "image", "end_image", "seed", "width", "height", "length", "fps", "steps")

# input names that mean the same thing across node packs
_INPUT_ALIASES = {
    "seed": ("seed", "noise_seed"),
    "width": ("width",),
    "height": ("height",),
    "length": ("length", "num_frames", "frames", "frame_count"),
    "fps": ("fps", "frame_rate"),
    "steps": ("steps",),
}
_TEXT_INPUTS = ("text", "prompt", "positive_prompt")


def load_workflow(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    if "nodes" in data and "links" in data:
        raise ValueError(f"{path.name} is a UI workflow; in ComfyUI use Workflow → Export (API) instead")
    if not data or not all(isinstance(n, dict) and "class_type" in n for n in data.values()):
        raise ValueError(f"{path.name} doesn't look like an API-format ComfyUI workflow")
    return data


def bindings_path(workflow_path: Path) -> Path:
    workflow_path = Path(workflow_path)
    return workflow_path.with_name(workflow_path.stem + ".bindings.json")


def load_bindings(workflow_path: Path, workflow: dict) -> tuple[dict[str, list[str]], bool]:
    """Return (bindings, explicit). Explicit bindings come from the sidecar file."""
    path = bindings_path(workflow_path)
    if path.exists():
        raw = json.loads(path.read_text())
        bindings = {k: [v] if isinstance(v, str) else list(v) for k, v in raw.items()}
        for name, targets in bindings.items():
            for t in targets:
                _split_target(t, workflow)  # validate now, not mid-run
        return bindings, True
    return guess_bindings(workflow), False


def _title(node: dict) -> str:
    return ((node.get("_meta") or {}).get("title") or "").lower()


def _is_literal(value: Any) -> bool:
    # a list value is a link to another node's output, not something we can set
    return not isinstance(value, list)


def guess_bindings(workflow: dict) -> dict[str, list[str]]:
    bindings: dict[str, list[str]] = {}
    positive, negative = [], []
    load_images = []
    for node_id, node in sorted(workflow.items(), key=lambda kv: _sort_key(kv[0])):
        inputs = node.get("inputs") or {}
        title = _title(node)
        for name in _TEXT_INPUTS:
            if isinstance(inputs.get(name), str):
                (negative if "negative" in title else positive).append(f"{node_id}.{name}")
                break
        if node.get("class_type") == "LoadImage" and _is_literal(inputs.get("image")):
            load_images.append((node_id, title))
        for param, aliases in _INPUT_ALIASES.items():
            for alias in aliases:
                if alias in inputs and _is_literal(inputs[alias]):
                    bindings.setdefault(param, []).append(f"{node_id}.{alias}")
    # only bind the prompt when it's unambiguous; otherwise ask for a bindings file
    if len(positive) == 1:
        bindings["prompt"] = positive
    if len(negative) == 1:
        bindings["negative"] = negative
    if load_images:
        end = [nid for nid, title in load_images if "end" in title or "last" in title]
        start = [nid for nid, _ in load_images if nid not in end]
        if start:
            bindings["image"] = [f"{start[0]}.image"]
        if end:
            bindings["end_image"] = [f"{end[0]}.image"]
    return bindings


def ambiguous_prompts(workflow: dict) -> list[str]:
    """Text inputs not marked negative; more than one means the prompt binding can't be guessed."""
    out = []
    for node_id, node in workflow.items():
        inputs = node.get("inputs") or {}
        for name in _TEXT_INPUTS:
            if isinstance(inputs.get(name), str) and "negative" not in _title(node):
                out.append(f"{node_id}.{name}")
                break
    return out if len(out) > 1 else []


def apply(workflow: dict, bindings: dict[str, list[str]], values: dict[str, Any],
          overrides: dict[str, Any] | None = None) -> dict:
    """Return a copy of the workflow with values written into their bound inputs."""
    wf = copy.deepcopy(workflow)
    for param, value in values.items():
        if value is None:
            continue
        targets = bindings.get(param)
        if not targets:
            raise ValueError(f"the workflow has no input bound to '{param}'; add it to the bindings file")
        for target in targets:
            node_id, name = _split_target(target, wf)
            wf[node_id]["inputs"][name] = value
    for target, value in (overrides or {}).items():
        node_id, name = _split_target(target, wf)
        wf[node_id]["inputs"][name] = value
    return wf


def parse_override(text: str) -> tuple[str, Any]:
    """'12.cfg=4.5' -> ('12.cfg', 4.5); values are parsed as JSON when possible."""
    if "=" not in text:
        raise ValueError(f"--set expects NODE.INPUT=VALUE, got {text!r}")
    target, raw = text.split("=", 1)
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    return target.strip(), value


def describe(workflow: dict) -> list[str]:
    lines = []
    for node_id, node in sorted(workflow.items(), key=lambda kv: _sort_key(kv[0])):
        title = (node.get("_meta") or {}).get("title") or ""
        lines.append(f"[{node_id}] {node['class_type']}" + (f"  “{title}”" if title and title != node["class_type"] else ""))
        for name, value in (node.get("inputs") or {}).items():
            if _is_literal(value):
                shown = value if not isinstance(value, str) or len(value) <= 70 else value[:67] + "..."
                lines.append(f"      {name} = {shown!r}")
    return lines


def _split_target(target: str, workflow: dict) -> tuple[str, str]:
    node_id, sep, name = target.partition(".")
    if not sep or not name:
        raise ValueError(f"binding target {target!r} should look like NODE_ID.INPUT")
    if node_id not in workflow:
        raise ValueError(f"binding target {target!r}: node {node_id} isn't in the workflow")
    if name not in (workflow[node_id].get("inputs") or {}):
        raise ValueError(f"binding target {target!r}: node {node_id} ({workflow[node_id]['class_type']}) has no input '{name}'")
    return node_id, name


def _sort_key(node_id: str):
    return (0, int(node_id), "") if node_id.isdigit() else (1, 0, node_id)

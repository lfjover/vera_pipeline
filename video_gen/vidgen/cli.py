"""Command line entry point:  python -m vidgen <command>

  check      reach the ComfyUI server, show its GPU and which H3 checkpoints it has
  inspect    list a workflow's nodes and where prompt/image/seed/... will be written
  generate   fill in a workflow, run it, and download the finished video(s)
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from datetime import datetime
from pathlib import Path

from .comfy import ComfyClient, ComfyError, output_files
from .config import DEFAULT_ENV_FILE, Settings
from .workflow import PARAMS, ambiguous_prompts, apply, bindings_path, describe, load_bindings, load_workflow, parse_override

H3_PATTERN = re.compile(r"h3", re.IGNORECASE)


def build_client(settings: Settings) -> ComfyClient:
    return ComfyClient(settings.comfy_url, token=settings.comfy_token)


def slugify(text: str, limit: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return slug[:limit].rstrip("-") or "video"


def parse_size(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)[x×](\d+)", text.strip())
    if not match:
        raise ValueError(f"--size expects WIDTHxHEIGHT, e.g. 768x1344, got {text!r}")
    return int(match.group(1)), int(match.group(2))


# ----------------------------------------------------------------- commands
def cmd_check(args, settings: Settings) -> int:
    client = build_client(settings)
    stats = client.system_stats()
    system = stats.get("system") or {}
    print(f"ComfyUI {system.get('comfyui_version', '?')} at {settings.comfy_url} (python {str(system.get('python_version', '?')).split()[0]})")
    for dev in stats.get("devices") or []:
        total = dev.get("vram_total") or 0
        free = dev.get("vram_free") or 0
        print(f"  device: {dev.get('name')}  {total / 2**30:.1f} GB VRAM, {free / 2**30:.1f} GB free")
    models = [m for m in client.model_options("UNETLoader", "unet_name") if H3_PATTERN.search(m)]
    if models:
        print("H3 checkpoints:")
        for m in models:
            print(f"  {m}")
    else:
        print("No H3 checkpoints in models/diffusion_models — see README 'GPU server setup'.")
        return 1
    return 0


def cmd_inspect(args, settings: Settings) -> int:
    path = Path(args.workflow)
    workflow = load_workflow(path)
    bindings, explicit = load_bindings(path, workflow)
    print("\n".join(describe(workflow)))
    print()
    print(f"Bindings ({'from ' + bindings_path(path).name if explicit else 'guessed — save them to ' + bindings_path(path).name + ' to pin them'}):")
    for param in PARAMS:
        print(f"  {param:<10} → {', '.join(bindings.get(param, [])) or '—'}")
    if not explicit and "prompt" not in bindings and ambiguous_prompts(workflow):
        print(f"\nSeveral text inputs could be the prompt: {', '.join(ambiguous_prompts(workflow))}")
        print(f"Pick one in {bindings_path(path).name}, e.g. {{\"prompt\": \"{ambiguous_prompts(workflow)[0]}\"}}")
    return 0


def cmd_generate(args, settings: Settings) -> int:
    wf_path = Path(args.workflow)
    workflow = load_workflow(wf_path)
    bindings, _ = load_bindings(wf_path, workflow)
    overrides = dict(parse_override(s) for s in args.set or [])

    values = {"prompt": args.prompt, "negative": args.negative, "length": args.length,
              "fps": args.fps, "steps": args.steps}
    if args.size:
        values["width"], values["height"] = parse_size(args.size)
    images = {"image": args.image, "end_image": args.end_image}
    for key, ref in images.items():
        if ref and not Path(ref).is_file():
            raise FileNotFoundError(f"{ref} not found")
    first_seed = args.seed if args.seed is not None else random.randrange(2**32)
    seeds = [first_seed + i for i in range(args.count)]

    if args.dry_run:
        for key, ref in images.items():
            if ref:
                values[key] = f"<upload {Path(ref).name}>"
        for seed in seeds:
            apply(workflow, bindings, {**values, "seed": seed}, overrides)  # raises on a missing binding
        print(f"[dry run] would queue {len(seeds)} run(s) of {wf_path.name} on {settings.comfy_url}")
        for k, v in values.items():
            if v is not None:
                print(f"  {k:<10} {v!r}  → {', '.join(bindings[k])}")
        print(f"  {'seed':<10} {', '.join(map(str, seeds))}  → {', '.join(bindings.get('seed', ['—']))}")
        for t, v in overrides.items():
            print(f"  set        {t} = {v!r}")
        return 0

    client = build_client(settings)
    for key, ref in images.items():
        if ref:
            values[key] = client.upload_image(Path(ref))
            print(f"Uploaded {ref} as {values[key]}")

    out_dir = Path(args.output_dir) if args.output_dir else settings.output_dir
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    slug = slugify(args.prompt or wf_path.stem)
    failures = 0
    for seed in seeds:
        prompt_id = client.queue(apply(workflow, bindings, {**values, "seed": seed}, overrides))
        print(f"→ seed {seed}: queued {prompt_id}")
        try:
            entry = client.wait(prompt_id, timeout=settings.timeout,
                                on_tick=lambda s: print(f"  … {int(s)}s", end="\r", flush=True))
        except ComfyError as exc:
            failures += 1
            print(f"  failed: {exc}", file=sys.stderr)
            continue
        files = output_files(entry)
        if not files:
            failures += 1
            print("  finished but saved no video — does the workflow end in a SaveVideo node?", file=sys.stderr)
            continue
        for i, f in enumerate(files):
            suffix = f"-{i + 1}" if len(files) > 1 else ""
            dest = client.download(f, out_dir, f"{stamp}_{slug}_s{seed}{suffix}{Path(f['filename']).suffix}")
            dest.with_suffix(".json").write_text(json.dumps({
                "workflow": str(wf_path), "prompt_id": prompt_id, "seed": seed,
                "params": {k: v for k, v in values.items() if v is not None},
                "set": overrides, "source": dict(f, server=settings.comfy_url),
            }, indent=2, ensure_ascii=False) + "\n")
            print(f"  saved {dest}")
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vidgen", description="Generate videos with MiniMax H3 via ComfyUI.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="path to .env (default: project .env)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="verify the ComfyUI server and list H3 checkpoints")

    i = sub.add_parser("inspect", help="show a workflow's nodes and parameter bindings")
    i.add_argument("workflow", help="API-format workflow JSON")

    g = sub.add_parser("generate", help="run a workflow and download the video")
    g.add_argument("workflow", help="API-format workflow JSON, e.g. workflows/h3_i2v.json")
    g.add_argument("-p", "--prompt", help="what should happen in the video")
    g.add_argument("-n", "--negative", help="negative prompt")
    g.add_argument("-i", "--image", help="start frame / reference image (uploaded to the server)")
    g.add_argument("--end-image", help="last frame image, for first/last-frame workflows")
    g.add_argument("--size", help="WIDTHxHEIGHT, e.g. 768x1344 for a vertical Reel")
    g.add_argument("--length", type=int, help="number of frames (H3 runs at 24 fps)")
    g.add_argument("--fps", type=int)
    g.add_argument("--steps", type=int, help="sampling steps (8 with the turbo LoRA, 20 without)")
    g.add_argument("--seed", type=int, help="first seed (default: random)")
    g.add_argument("--count", type=int, default=1, help="how many variations, seed, seed+1, ... (default 1)")
    g.add_argument("--set", action="append", metavar="NODE.INPUT=VALUE", help="set any other input; repeatable")
    g.add_argument("-o", "--output-dir", help="where to save (default: output/)")
    g.add_argument("--dry-run", action="store_true", help="check the bindings and show what would run")

    args = parser.parse_args(argv)
    settings = Settings.from_env(Path(args.env_file))
    commands = {"check": cmd_check, "inspect": cmd_inspect, "generate": cmd_generate}
    try:
        return commands[args.command](args, settings)
    except ComfyError as exc:
        print(f"ComfyUI error: {exc}", file=sys.stderr)
        return 2
    except (ValueError, FileNotFoundError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

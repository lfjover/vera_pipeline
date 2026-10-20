"""python -m vera <command>

  list     the photographers the pipeline picks from
  check    confirm the Kling and Anthropic keys work
  run      one full run: 9 photographers × 3 images → best of each → 3×3 grid
  grid     rebuild the grid of an existing run folder
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import photographers as ph
from .config import DEFAULT_DIRECTION_FILE, DEFAULT_ENV_FILE, PROJECT_ROOT, Settings
from .pipeline import make_grid, read_direction, run
from .posting import IG_KEYS, enqueue_run, load_account


def cmd_list(args, settings) -> int:
    for p in sorted(ph.PHOTOGRAPHERS, key=lambda p: p.name):
        print(f"{p.label:40} {p.nationality:36} {'color' if p.color else 'b&w  '}  {p.slug}")
    print(f"\n{len(ph.PHOTOGRAPHERS)} photographers. Use the slug (e.g. fan-ho) with --photographers.")
    return 0


def cmd_check(args, settings) -> int:
    missing = settings.missing()
    if missing:
        print(f"Missing in .env: {', '.join(missing)}")
        return 1
    from .claude import ClaudeClient
    ok = True
    label = f"fal ({settings.fal_model})" if settings.fal_key else f"Kling ({settings.kling_base_url})"
    try:
        settings.image_client().ping()
        print(f"Images, {label}: OK")
    except Exception as exc:
        ok = False
        print(f"Images, {label}: FAILED — {exc}")
    try:
        ClaudeClient(settings.anthropic_api_key, settings.anthropic_model).ping()
        print(f"Anthropic: OK (model {settings.anthropic_model})")
    except Exception as exc:
        ok = False
        print(f"Anthropic: FAILED — {exc}")
    return 0 if ok else 1


def cmd_run(args, settings) -> int:
    only = [s.strip() for s in args.photographers.split(",")] if args.photographers else None
    if args.no_direction:
        direction = None
    elif args.direction:
        direction = args.direction.strip()
    else:
        direction = read_direction(DEFAULT_DIRECTION_FILE)
    if args.resume and (args.direction or args.no_direction):
        print("Note: a resumed run keeps the prompts (and direction) it was written with.")
    summary = run(settings, count=args.count, per=args.per, only=only, dry_run=args.dry_run,
                  resume=Path(args.resume) if args.resume else None, parallel=args.parallel,
                  direction=direction)
    print()
    print(f"Run folder: {summary['run_dir']}")
    print(f"Grid: {summary['grid'] or 'not made (no finished photographers)'}")
    if summary["errors"]:
        print("Problems:")
        for slug, err in summary["errors"].items():
            print(f"  {slug}: {err}")
        print(f"Fix the cause and finish the run with: python -m vera run --resume {summary['run_dir']}")
        return 1
    return 0


def cmd_enqueue(args, settings) -> int:
    for path in enqueue_run(Path(args.run_dir)):
        print(path)
    return 0


def cmd_account(args, settings) -> int:
    import os
    account = load_account()
    print(f"{account['name']}  ({account['id']})")
    print(f"Focus: {account.get('focus', 'photography')}")
    missing = settings.missing()
    print("Image generation: ready" if not missing else "Image generation missing: " + ", ".join(missing))
    print("Instagram:")
    for key in IG_KEYS:
        print(f"  {key}: {'set' if os.environ.get(key, '').strip() else 'missing'}")
    queue = PROJECT_ROOT / "queue"
    waiting = sorted(p.name for p in queue.glob("*.json")) if queue.exists() else []
    print(f"Queue: {len(waiting)} waiting" + (f" ({', '.join(waiting)})" if waiting else ""))
    return 0 if not missing else 1


def cmd_grid(args, settings) -> int:
    path = make_grid(Path(args.run_dir))
    print(path or "No scored photographers in that run yet.")
    return 0 if path else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="vera", description="VeraSynth Photo: photographer-style portrait grids.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="show the photographer list")
    sub.add_parser("check", help="test the API keys")
    r = sub.add_parser("run", help="make today's grid")
    r.add_argument("--count", type=int, default=9, help="photographers per run (default 9)")
    r.add_argument("--per", type=int, default=3, help="images per photographer, 1-9 (default 3)")
    r.add_argument("--photographers", help="comma-separated slugs instead of a random pick, e.g. fan-ho,saul-leiter")
    r.add_argument("--parallel", type=int, default=3, help="Kling tasks running at once (default 3)")
    r.add_argument("--resume", metavar="RUN_DIR", help="finish an interrupted run without redoing finished steps")
    r.add_argument("--dry-run", action="store_true", help="no API calls: placeholder images and scores")
    r.add_argument("--direction", help="creative direction for every prompt this run (instead of direction.txt)")
    r.add_argument("--no-direction", action="store_true", help="ignore direction.txt for this run")
    g = sub.add_parser("grid", help="rebuild the grid of a run folder")
    g.add_argument("run_dir")
    e = sub.add_parser("enqueue", help="queue each winning portrait as its own Instagram post")
    e.add_argument("run_dir")
    sub.add_parser("account", help="show whether this account is ready to generate and post")

    args = parser.parse_args(argv)
    settings = Settings.from_env(Path(args.env_file))
    commands = {"list": cmd_list, "check": cmd_check, "run": cmd_run, "grid": cmd_grid,
                "enqueue": cmd_enqueue, "account": cmd_account}
    try:
        return commands[args.command](args, settings)
    except (ValueError, RuntimeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

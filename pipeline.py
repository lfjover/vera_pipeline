"""Vera pipeline, version 1 (Kling only).

  python pipeline.py variant inbox/winner.png --light red_moody --pose head_turn
  python pipeline.py clip    inbox/winner.png output/winner/red_moody-head_turn_1.png
  python pipeline.py both    inbox/winner.png --light red_moody --pose head_turn
  python pipeline.py presets

Add --dry-run to any command to see the prompt and settings without calling Kling.
"""
import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent
OUTPUT = ROOT / "output"
LOG = OUTPUT / "runs.csv"
LOG_FIELDS = ["timestamp", "kind", "source", "end_frame", "light", "pose", "model",
              "task_id", "output", "face_match", "lighting", "pose_natural", "keep", "notes"]


def load_cfg():
    return json.loads((ROOT / "presets.json").read_text())


def log_row(**row):
    OUTPUT.mkdir(exist_ok=True)
    new = not LOG.exists()
    with open(LOG, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if new:
            w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"), **row})


def build_prompt(cfg, light, pose):
    if light not in cfg["lighting"]:
        sys.exit(f"Unknown --light '{light}'. Options: {', '.join(cfg['lighting'])}")
    if pose not in cfg["pose"]:
        sys.exit(f"Unknown --pose '{pose}'. Options: {', '.join(cfg['pose'])}")
    parts = [cfg["base_instruction"], cfg["lighting"][light], cfg["pose"][pose]]
    return " ".join(p for p in parts if p)


def check_image(path):
    p = Path(path)
    if not p.exists():
        sys.exit(f"Image not found: {p}")
    if p.stat().st_size > 10 * 1024 * 1024:
        sys.exit(f"{p.name} is over 10MB, which Kling rejects. Export a smaller JPG first.")
    return p


def cmd_variant(args, cfg):
    import kling
    src = check_image(args.image)
    prompt = build_prompt(cfg, args.light, args.pose)
    payload = kling.image_variant_payload(src, prompt, cfg, n=args.n)
    print(f"Variant for {src.name}: light={args.light}, pose={args.pose}, model={cfg['image_model']}")
    print(f"Prompt: {prompt}")
    if args.dry_run:
        print("(dry run, nothing sent)")
        return []
    task_id, urls = kling.generate_variant(payload)
    saved = []
    for i, url in enumerate(urls, 1):
        dest = OUTPUT / src.stem / f"{args.light}-{args.pose}_{datetime.now():%H%M%S}_{i}.png"
        kling.download(url, dest)
        log_row(kind="variant", source=src.name, light=args.light, pose=args.pose,
                model=cfg["image_model"], task_id=task_id, output=str(dest.relative_to(ROOT)))
        print(f"  saved {dest.relative_to(ROOT)}")
        saved.append(dest)
    return saved


def cmd_clip(args, cfg, start=None, end=None):
    import kling
    start = check_image(start or args.start)
    end = check_image(end or args.end)
    payload = kling.clip_payload(start, end, cfg)
    print(f"Clip {start.name} -> {end.name}: {cfg['video_model']} {cfg['video_mode']} {cfg['video_duration']}s")
    if args.dry_run:
        print("(dry run, nothing sent)")
        return
    task_id, urls = kling.generate_clip(payload)
    for i, url in enumerate(urls, 1):
        dest = OUTPUT / start.stem / f"clip_{end.stem}_{i}.mp4"
        kling.download(url, dest)
        log_row(kind="clip", source=start.name, end_frame=end.name, model=cfg["video_model"],
                task_id=task_id, output=str(dest.relative_to(ROOT)))
        print(f"  saved {dest.relative_to(ROOT)}")


def cmd_both(args, cfg):
    variants = cmd_variant(args, cfg)
    if args.dry_run:
        cmd_clip(args, cfg, start=args.image, end=args.image)
        return
    if not variants:
        sys.exit("No variant came back, so no clip was made.")
    print("\nCheck the variant now. If her face changed, stop here (Ctrl+C) and try again.")
    if input("Make the clip from this variant? [y/N] ").strip().lower() == "y":
        cmd_clip(args, cfg, start=args.image, end=variants[0])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("variant", "both"):
        p = sub.add_parser(name)
        p.add_argument("image")
        p.add_argument("--light", default="red_moody")
        p.add_argument("--pose", default="head_turn")
        p.add_argument("-n", type=int, default=1, help="how many variants to generate (1-4)")
        p.add_argument("--dry-run", action="store_true")
    p = sub.add_parser("clip")
    p.add_argument("start")
    p.add_argument("end")
    p.add_argument("--dry-run", action="store_true")
    sub.add_parser("presets")
    args = ap.parse_args()
    cfg = load_cfg()

    if args.cmd == "presets":
        print("Lighting:", ", ".join(cfg["lighting"]))
        print("Pose:    ", ", ".join(cfg["pose"]))
    elif args.cmd == "variant":
        cmd_variant(args, cfg)
    elif args.cmd == "clip":
        cmd_clip(args, cfg)
    else:
        cmd_both(args, cfg)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit("\nStopped.")
    except Exception as e:
        if type(e).__name__ == "KlingError":
            sys.exit(f"Kling error: {e}")
        raise

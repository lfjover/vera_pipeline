"""One Vera run: pick photographers → write prompts → generate → score → grid.

Every step saves its result in the run folder before moving on, so a run that
stops halfway (network error, Ctrl-C) can be finished with `--resume <folder>`
without paying for the finished images again.

runs/2026-10-19_1530/
  prompts.json            the photographers and the prompts Claude wrote
  fan-ho/c1.jpg … c3.jpg  the candidates (plus task.json with Kling's task id)
  fan-ho/candidates.jpg   the three side by side with their scores
  fan-ho/final.jpg        the winning photo again, same person, different cinematic light
  fan-ho/pair.jpg         opening frame beside that final frame
  scores.json             every score, reason and the winner per photographer
  grid_2026-10-19.jpg     the nine opening frames, 3×3
  grid_final_2026-10-19.jpg
  summary.json
"""

from __future__ import annotations

import hashlib
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw

from . import photographers as ph
from .grid import build_grid, candidate_sheet, load_font, pair_sheet
from .posting import enqueue_run

WEIGHTS = {"realism": 0.35, "face_hands": 0.25, "style": 0.25, "animation": 0.15}
HISTORY_FILE = "history.json"


def weighted_total(score: dict) -> float:
    total = 0.0
    for key, weight in WEIGHTS.items():
        try:
            value = float(score.get(key, 0))
        except (TypeError, ValueError):
            value = 0.0
        total += max(0.0, min(10.0, value)) * weight
    return round(total, 2)


# ------------------------------------------------------------- choosing
def load_history(runs_dir: Path) -> list[list[str]]:
    path = runs_dir / HISTORY_FILE
    if not path.exists():
        return []
    return [run.get("photographers", []) for run in json.loads(path.read_text()).get("runs", [])]


def save_history(runs_dir: Path, run_name: str, slugs: list[str]) -> None:
    path = runs_dir / HISTORY_FILE
    data = json.loads(path.read_text()) if path.exists() else {"runs": []}
    data["runs"] = [r for r in data["runs"] if r.get("run") != run_name]
    data["runs"].append({"run": run_name, "photographers": slugs})
    path.write_text(json.dumps(data, indent=2) + "\n")


def choose_photographers(count: int, history: list[list[str]], rng: random.Random,
                         avoid_last: int = 2, only: list[str] | None = None) -> list[ph.Photographer]:
    """Pick `count` photographers, preferring ones not used in the last `avoid_last` runs."""
    if only:
        return [ph.get(slug) for slug in only]
    if count > len(ph.PHOTOGRAPHERS):
        raise ValueError(f"Only {len(ph.PHOTOGRAPHERS)} photographers on the list")
    recent = {slug for run in history[-avoid_last:] for slug in run} if avoid_last else set()
    fresh = [p for p in ph.PHOTOGRAPHERS if p.slug not in recent]
    used = [p for p in ph.PHOTOGRAPHERS if p.slug in recent]
    picked = rng.sample(fresh, min(count, len(fresh)))
    if len(picked) < count:
        picked += rng.sample(used, count - len(picked))
    return picked


# ------------------------------------------------- offline stand-ins (--dry-run)
DEFAULT_FINAL_LIGHT = (
    "a different cinematic light from the opening frame: if that frame is warm, switch to a cool hard key; "
    "if it is already colored, switch to one contrasting gel and a new shadow pattern. Keep the face lit"
)


def final_prompt(light: str | None) -> str:
    """Keep the person in @Image, with a new light and a small change of angle and pose."""
    light = (light or "").strip() or DEFAULT_FINAL_LIGHT
    return (
        "@Image is the opening frame of a short shot. Recreate the same person: "
        "same face, same hair, same clothes, same place. "
        "Move the camera a little and change her pose slightly, enough that the two frames "
        "would make a living clip: a turn of the head, a shift of the shoulders, a step, "
        "or a change of which way she is looking. Do not invent a new scene or a new person. "
        f"Also change the light to this different cinematic setup: {light}. "
        "The face stays sharp and recognizable. No text, no extra people."
    )


def template_prompt(p: ph.Photographer) -> dict:
    return {"slug": p.slug, "subject": "a woman in her twenties",
            "prompt": (f"Portrait of a woman in her twenties, {p.style}. Real skin texture with visible pores, "
                       "flyaway hairs, unretouched, film grain. Face clearly visible. Vertical 9:16."),
            "negative_prompt": "plastic skin, airbrushed, distorted face, extra fingers, text, watermark",
            "light": f"one lighting setup in the batch style, specific to {p.slug}",
            "final_light": "a cool hard side light with a single teal gel, different from the opening frame"}


class OfflineKling:
    """Draws placeholder images instead of calling Kling."""

    def __init__(self):
        self._tasks: dict[str, tuple[str, int]] = {}

    def create_image_task(self, prompt, negative_prompt=None, n=5, aspect_ratio="9:16"):
        task_id = "dry-" + hashlib.sha1(prompt.encode()).hexdigest()[:10]
        self._tasks[task_id] = (prompt, n)
        return task_id

    def wait_for_images(self, task_id, **_):
        _, n = self._tasks[task_id]
        kind = "offline-final" if task_id.startswith("dry-final-") else "offline"
        return [f"{kind}://{task_id}/{i}" for i in range(n)]

    def download(self, url: str, dest: Path) -> Path:
        if url.startswith("offline-final://"):
            task_id = url.split("://", 1)[1].rsplit("/", 1)[0]
            source, _ = self._tasks[task_id]
            with Image.open(source) as img:
                frame = img.convert("RGB")
            tint = Image.new("RGB", frame.size, (20, 90, 140))
            frame = Image.blend(frame, tint, 0.45)
            dest.parent.mkdir(parents=True, exist_ok=True)
            frame.save(dest, format="PNG")
            return dest
        seed = int(hashlib.sha1(url.encode()).hexdigest()[:6], 16)
        hue = seed % 360
        img = Image.new("HSV", (576, 1024), (int(hue * 255 / 360), 90, 70)).convert("RGB")
        draw = ImageDraw.Draw(img)
        draw.ellipse([168, 260, 408, 560], fill=(214, 170, 140))
        draw.rectangle([128, 600, 448, 1024], fill=(40, 40, 48))
        draw.text((24, 24), "DRY RUN", font=load_font(40), fill=(255, 255, 255))
        draw.text((24, 76), url.rsplit("/", 1)[-1], font=load_font(28, bold=False), fill=(255, 255, 255))
        dest.parent.mkdir(parents=True, exist_ok=True)
        img.save(dest, format="PNG")
        return dest

    def create_final_frame(self, prompt, image, aspect_ratio="9:16"):
        task_id = "dry-final-" + hashlib.sha1(f"{prompt}{image}".encode()).hexdigest()[:10]
        self._tasks[task_id] = (str(image), 1)
        return task_id


class OfflineClaude:
    def write_prompts(self, photographers, direction=None):
        out = [template_prompt(p) for p in photographers]
        if direction:
            for item in out:
                item["light"] = f"{direction} Setup for {item['slug']} only."
                item["prompt"] = item["prompt"].replace(
                    " Vertical 9:16.", f" {item['light']} Vertical 9:16.")
        return out

    def score(self, photographer, images, direction=None):
        out = []
        for i, path in enumerate(images, 1):
            h = int(hashlib.sha1(f"{photographer.slug}{path.name}".encode()).hexdigest()[:8], 16)
            out.append({"image": i, "realism": 4 + h % 6, "face_hands": 4 + (h >> 4) % 6,
                        "style": 4 + (h >> 8) % 6, "animation": 4 + (h >> 12) % 6,
                        "reason": "placeholder score (dry run)"})
        return out


# ----------------------------------------------------------------- steps
def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def candidates_in(folder: Path) -> list[Path]:
    return sorted(folder.glob("c[0-9]*.jpg"), key=lambda p: int(p.stem[1:]))


def generate_one(kling, item: dict, folder: Path, per: int) -> list[Path]:
    existing = candidates_in(folder)
    if len(existing) >= per:
        return existing[:per]
    folder.mkdir(parents=True, exist_ok=True)
    task_id = kling.create_image_task(item["prompt"], item.get("negative_prompt"), n=per, aspect_ratio="9:16")
    _write_json(folder / "task.json", {"task_id": task_id, "prompt": item["prompt"]})
    urls = kling.wait_for_images(task_id)
    paths = []
    for i, url in enumerate(urls[:per], 1):
        raw = kling.download(url, folder / f"raw_{i}")
        dest = folder / f"c{i}.jpg"
        with Image.open(raw) as img:
            img.convert("RGB").save(dest, format="JPEG", quality=95)
        raw.unlink(missing_ok=True)
        paths.append(dest)
    return paths


def generate_final(kling, item: dict, folder: Path, winner: Path) -> Path:
    """A second still of the winning photo: same person, different cinematic light."""
    dest = folder / "final.jpg"
    if dest.exists():
        return dest
    if not hasattr(kling, "create_final_frame"):
        raise RuntimeError("this image client cannot relight a photo into a final frame")
    prompt = final_prompt(item.get("final_light"))
    task_id = kling.create_final_frame(prompt, winner, aspect_ratio="9:16")
    _write_json(folder / "final_task.json", {"task_id": task_id, "prompt": prompt})
    raw = kling.download(kling.wait_for_images(task_id)[0], folder / "raw_final")
    with Image.open(raw) as img:
        img.convert("RGB").save(dest, format="JPEG", quality=95)
    raw.unlink(missing_ok=True)
    return dest


def read_direction(path: Path) -> str | None:
    """The batch-wide creative direction: direction.txt, ignoring blank lines and # comments."""
    if not path.exists():
        return None
    lines = [l.strip() for l in path.read_text().splitlines() if l.strip() and not l.strip().startswith("#")]
    return " ".join(lines) or None


def run(settings, *, count: int = 9, per: int = 3, only: list[str] | None = None,
        dry_run: bool = False, resume: Path | None = None, parallel: int = 3,
        direction: str | None = None,
        kling=None, claude=None, rng: random.Random | None = None,
        now: datetime | None = None, log: Callable[[str], None] = print) -> dict:
    now = now or datetime.now()
    rng = rng or random.Random()
    runs_dir: Path = settings.runs_dir
    runs_dir.mkdir(parents=True, exist_ok=True)
    if kling is None or claude is None:
        if dry_run:
            kling, claude = kling or OfflineKling(), claude or OfflineClaude()
        else:
            settings.require_keys()
            from .claude import ClaudeClient
            kling = kling or settings.image_client()
            log(f"Images via {settings.image_provider}" + (f" ({settings.fal_model})" if settings.fal_key else ""))
            claude = claude or ClaudeClient(settings.anthropic_api_key, settings.anthropic_model)

    run_dir = Path(resume) if resume else runs_dir / (now.strftime("%Y-%m-%d_%H%M") + ("_dry" if dry_run else ""))
    run_dir.mkdir(parents=True, exist_ok=True)
    errors: dict[str, str] = {}

    # 1-2. photographers and prompts
    prompts_path = run_dir / "prompts.json"
    if prompts_path.exists():
        prompts = json.loads(prompts_path.read_text())
        log(f"Resuming {run_dir.name}: {len(prompts['items'])} prompts already written")
    else:
        chosen = choose_photographers(count, load_history(runs_dir), rng, only=only)
        log("Photographers: " + ", ".join(p.name for p in chosen))
        if direction:
            log(f"Direction: {direction}")
        log("Writing prompts…")
        try:
            written = claude.write_prompts(chosen, direction=direction)
        except Exception as first:
            log(f"  retrying ({first})")
            try:
                written = claude.write_prompts(chosen, direction=direction)
            except Exception:
                reply = getattr(claude, "last_reply", "")
                if reply:
                    (run_dir / "claude_reply.txt").write_text(reply)
                raise
        prompts = {"created": now.isoformat(timespec="seconds"), "dry_run": dry_run, "per_prompt": per,
                   "direction": direction or "",
                   "items": [{**w, "name": p.name, "years": p.years, "nationality": p.nationality}
                             for p, w in zip(chosen, written)]}
        _write_json(prompts_path, prompts)
    items = prompts["items"]
    per = prompts.get("per_prompt", per)
    direction = prompts.get("direction") or None  # a resumed run keeps the direction it was written with

    # 3. generate (a few photographers at a time)
    log(f"Generating {per} images × {len(items)} prompts = {per * len(items)} images…")
    generated: dict[str, list[Path]] = {}
    with ThreadPoolExecutor(max_workers=max(1, parallel)) as pool:
        futures = {pool.submit(generate_one, kling, item, run_dir / item["slug"], per): item for item in items}
        for fut in as_completed(futures):
            item = futures[fut]
            try:
                generated[item["slug"]] = fut.result()
                log(f"  ✓ {item['name']}: {len(generated[item['slug']])} images")
            except Exception as exc:  # keep going with the other photographers
                errors[item["slug"]] = f"generate: {exc}"
                log(f"  ✗ {item['name']}: {exc}")

    # 4. score and pick winners
    scores_path = run_dir / "scores.json"
    scores = json.loads(scores_path.read_text()) if scores_path.exists() else {}
    log("Scoring…")
    for item in items:
        slug = item["slug"]
        if slug in scores or slug not in generated:
            continue
        images = generated[slug]
        try:
            raw_scores = claude.score(ph.get(slug), images, direction=item.get("light") or direction)
        except Exception as exc:
            errors[slug] = f"score: {exc}"
            log(f"  ✗ {item['name']}: {exc}")
            continue
        cands = [{"file": img.name, **{k: s.get(k) for k in (*WEIGHTS, "reason")}, "total": weighted_total(s)}
                 for img, s in zip(images, raw_scores)]
        best = max(range(len(cands)), key=lambda i: cands[i]["total"])
        scores[slug] = {"winner": cands[best]["file"], "total": cands[best]["total"], "candidates": cands}
        _write_json(scores_path, scores)
        candidate_sheet(images, [c["total"] for c in cands], best, run_dir / slug / "candidates.jpg",
                        f"{item['name']} — candidates")
        log(f"  {item['name']}: winner {cands[best]['file']} ({cands[best]['total']:.1f}/10)")

    # 5. one final frame per winner: the same photograph, relit
    log("Final frames…")
    for item in items:
        slug = item["slug"]
        if slug not in scores:
            continue
        folder = run_dir / slug
        winner = folder / scores[slug]["winner"]
        try:
            generate_final(kling, item, folder, winner)
            scores[slug]["final"] = "final.jpg"
            _write_json(scores_path, scores)
            pair_sheet(winner, folder / "final.jpg", folder / "pair.jpg", item["name"])
            log(f"  {item['name']}: final frame")
        except Exception as exc:
            errors[f"final:{slug}"] = str(exc)
            log(f"  ✗ {item['name']} final frame: {exc}")

    # 6. grids
    dry = prompts.get("dry_run", dry_run)
    grid_path = make_grid(run_dir, dry_run=dry)
    final_grid = make_final_grid(run_dir, dry_run=dry)

    finished = [i["slug"] for i in items if i["slug"] in scores]
    if not prompts.get("dry_run", dry_run):
        save_history(runs_dir, run_dir.name, [i["slug"] for i in items])
    portrait_errors = {k: v for k, v in errors.items() if not k.startswith("final:")}
    queued = None
    if not prompts.get("dry_run", dry_run) and not portrait_errors and len(finished) >= 1:
        try:
            queued = [str(p) for p in enqueue_run(run_dir, now=now)]
            log(f"Queued {len(queued)} posts")
        except Exception as exc:
            errors["queue"] = str(exc)
            log(f"  ✗ queue: {exc}")
    summary = {"run_dir": str(run_dir), "grid": str(grid_path) if grid_path else None,
               "grid_final": str(final_grid) if final_grid else None,
               "finished": finished, "errors": errors, "queued": queued,
               "winners": {s: scores[s]["winner"] for s in finished},
               "finals": {s: scores[s]["final"] for s in finished if scores[s].get("final")}}
    _write_json(run_dir / "summary.json", summary)
    return summary


def _nationality(item: dict) -> str:
    if item.get("nationality"):
        return item["nationality"]
    p = ph.BY_SLUG.get(item.get("slug", ""))
    return p.nationality if p else ""


def make_grid(run_dir: Path, dry_run: bool = False) -> Path | None:
    prompts = json.loads((run_dir / "prompts.json").read_text())
    scores_path = run_dir / "scores.json"
    scores = json.loads(scores_path.read_text()) if scores_path.exists() else {}
    cells = []
    for item in prompts["items"]:
        s = scores.get(item["slug"])
        if not s:
            continue
        cells.append({"image": run_dir / item["slug"] / s["winner"], "label": item["name"],
                      "sublabel": f"{_nationality(item)}  ·  {item['years']}",
                      "detail": f"score {s['total']:.1f}/10"})
    if not cells:
        return None
    date = prompts.get("created", "")[:10] or run_dir.name[:10]
    title = f"VeraSynth Ori  ·  {date}" + ("  ·  DRY RUN" if dry_run else "")
    return build_grid(cells, run_dir / f"grid_{date}.jpg", title, cols=_grid_cols(len(cells)))


def make_final_grid(run_dir: Path, dry_run: bool = False) -> Path | None:
    prompts = json.loads((run_dir / "prompts.json").read_text())
    scores_path = run_dir / "scores.json"
    scores = json.loads(scores_path.read_text()) if scores_path.exists() else {}
    cells = []
    for item in prompts["items"]:
        s = scores.get(item["slug"])
        if not s or not s.get("final"):
            continue
        cells.append({"image": run_dir / item["slug"] / s["final"], "label": item["name"],
                      "sublabel": "final frame",
                      "detail": (item.get("final_light") or "")[:80]})
    if not cells:
        return None
    date = prompts.get("created", "")[:10] or run_dir.name[:10]
    title = f"VeraSynth Ori  ·  final frames  ·  {date}" + ("  ·  DRY RUN" if dry_run else "")
    return build_grid(cells, run_dir / f"grid_final_{date}.jpg", title, cols=_grid_cols(len(cells)))


def _grid_cols(count: int) -> int:
    """Four portraits lay out as 2×2. A full run stays 3×3."""
    return 2 if count == 4 else 3

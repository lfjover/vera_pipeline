# vera_synth_photo

The photography account inside `vera_synth`. Each run picks **9 dead portrait or street photographers**, has Claude write one
prompt in each one's style, generates **3 images per prompt with Kling** (27 total, through
fal.ai pay-as-you-go or Kling's own API), has Claude
judge each set of 5, and saves the **9 winners as a 3×3 grid**.

```
python -m vera run              # a full run (≈27 Kling images + 10 Claude calls)
python -m vera run --dry-run    # same steps with placeholder images and scores, no API calls
python -m vera check            # test the keys
python -m vera list             # the photographer list
```

## Setup (once)

```
cd vera_synth/vera_synth_photo
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env            # then paste your keys into .env
python -m vera check
```

Keys go in `.env` only. Never paste them into a chat or commit them.

- **fal.ai** (recommended): an API key from fal.ai with a few dollars of credit, pasted on `FAL_KEY=`.
  Images then go through fal's Kling image model (`FAL_MODEL`, about $0.03–0.05 per image), with no
  prepaid pack needed. When `FAL_KEY` is set it is used instead of Kling's own API.
- **Kling** (alternative): an *API key* from Kling's developer console (separate from the normal Kling app login),
  pasted on `KLING_API_KEY=`. Older accounts with an access key + secret key pair can use
  `KLING_ACCESS_KEY` and `KLING_SECRET_KEY` instead. API calls are billed from the developer account.
- **Anthropic**: an API key from console.anthropic.com. `ANTHROPIC_MODEL` picks the model.

## Creative direction (applies to every prompt)

`direction.txt` holds one instruction that is added to **all nine prompts** of a run, on top of each
photographer's own style (for example "experimental lighting with colored gels"). Claude also counts it
when judging the images. Edit the file any time; lines starting with `#` are ignored.

```
python -m vera run                                         # uses direction.txt
python -m vera run --direction "soft fog and neon signs"   # this run only
python -m vera run --no-direction                          # plain photographer styles
```

The direction is saved in the run's `prompts.json`, so `--resume` keeps the one the run started with.

## What a run does

1. **Pick photographers.** 9 from `vera/photographers.py`, skipping anyone used in the last 2 runs
   (tracked in `runs/history.json`). Or choose them: `--photographers fan-ho,saul-leiter,...`
2. **Write prompts.** Claude writes one prompt per photographer. It describes the technique (light,
   color, framing, film stock) instead of naming the photographer, uses a different woman each time,
   and adds realism cues (pores, flyaway hairs, unretouched skin) and vertical 9:16 framing.
3. **Generate.** One Kling task per artist with `n=3`: three images, each from a different
   random seed. Three tasks run at a time (`--parallel`).
4. **Judge.** Claude sees each set of 5 and scores every image 0–10 on:

   | criterion | weight |
   |---|---|
   | realism (skin, hair, no plastic look) | 35% |
   | face and hands (no distortion) | 25% |
   | style match with the photographer | 25% |
   | animation-ready (clear face, simple background) | 15% |

   The weighted total picks the winner. Scores and one-line reasons go to `scores.json`.
5. **Grid.** The 9 winners, labeled with name, years and score, saved as `grid_<date>.jpg`.

## Output

```
runs/2026-10-19_1530/
  grid_2026-10-19.jpg       ← open this
  prompts.json              the prompts Claude wrote
  scores.json               every score, reason and winner
  summary.json
  fan-ho/c1.jpg … c3.jpg    the three candidates
  fan-ho/candidates.jpg     the three side by side with scores, winner framed in gold
  fan-ho/task.json          Kling task id
```

## When something fails

If a photographer fails (network, Kling balance, a flagged prompt), the run keeps going with the
others and lists the problem at the end. Fix the cause, then finish it without paying again
for the images that already exist:

```
python -m vera run --resume runs/2026-10-19_1530
```

`python -m vera grid runs/2026-10-19_1530` rebuilds just the grid.

## Settings (`.env`)

| variable | default | |
|---|---|---|
| `FAL_KEY` | | images via fal.ai (used when set) |
| `FAL_MODEL` | `fal-ai/kling-image/o3/text-to-image` | any fal text-to-image model id |
| `KLING_API_KEY` | | images via Kling's own API, needs a prepaid resource pack (or the older `KLING_ACCESS_KEY` + `KLING_SECRET_KEY` pair) |
| `KLING_API_BASE` | `https://api-singapore.klingai.com` | try `https://api.klingai.com` if `check` can't connect |
| `KLING_IMAGE_MODEL` | `kling-v2-1` | any image model your Kling API account offers |
| `ANTHROPIC_API_KEY` | | required |
| `ANTHROPIC_MODEL` | `claude-sonnet-5-5` | |
| `VERA_RUNS_DIR` | `vera_synth/vera_synth_photo/runs` | |

## This account

`account.json` names the account. A finished run queues one image post per winning portrait in `queue/`, spaced `interval_hours` apart (5 hours). Each photo is cropped from 9:16 to 4:5 with a white frame. The caption is hashtags only, including the AI hashtags, and Instagram's AI label is on as well. The photographer's name stays off the caption. A scheduled job publishes one due post at a time.

```
python -m vera account          # what is ready, and what is still missing
python -m vera enqueue runs/2026-10-19_1603
```

Publishing uses `instagram_poster`, pointed at this account's own `.env` and `queue/`:

```
cd ../../instagram_poster
python -m igpost --env-file ../vera_synth/vera_synth_photo/.env check
python -m igpost --env-file ../vera_synth/vera_synth_photo/.env run-queue \
    --queue-dir ../vera_synth/vera_synth_photo/queue --dry-run
```

Drop `--dry-run` only when that post should actually go live. The Instagram token, user id, and public bucket belong to this account; they are not the ones in `instagram_poster/.env`.

## One post every 5 hours

`account.json` sets `interval_hours` to 5. Each new portrait is scheduled 5 hours after the previous one. The Mac job `com.verasynth.photo.post` runs every 5 hours and publishes at most one due post. The computer has to be awake; if it was asleep, one post goes out the next time the job runs.

## Files

```
vera/photographers.py  the photographer list with style notes (all deceased)
vera/fal.py            fal.ai queue API: submit, poll, download (default image source)
vera/kling.py          Kling's own API: auth, image tasks, polling, download
vera/claude.py         Anthropic API: prompt writing and image scoring
vera/pipeline.py       the run, resume logic, offline stand-ins for --dry-run
vera/grid.py           3×3 grid and candidate sheets
vera/cli.py            command line
tests/                 tests with fake HTTP sessions (no keys or network needed)
```

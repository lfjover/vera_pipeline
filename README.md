# Vera pipeline (version 1, Kling only)

Takes a winning image, makes a variant with new lighting and a small pose change
(same face), then turns the pair into a clip using them as start and end frames.

## Setup (once)

```
cd ~/AI/vera-pipeline
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

Open `.env` and paste your Access Key and Secret Key from the Kling developer
console (API keys page). The keys stay on your Mac; `.env` is git-ignored.

## Daily use

1. Drop the winning image into `inbox/`.
2. Make variants (try 2-4 so you can pick the best):
   `python pipeline.py variant inbox/winner.jpg --light red_moody --pose head_turn -n 3`
3. Look at `output/winner/`. Pick the variant where her face matches best.
4. Make the clip:
   `python pipeline.py clip inbox/winner.jpg output/winner/<chosen-variant>.png`

Or do both in one go (it pauses so you can check the variant first):
`python pipeline.py both inbox/winner.jpg --light red_moody --pose head_turn`

See all lighting and pose options: `python pipeline.py presets`
Preview a prompt without spending credits: add `--dry-run`.

## Tuning

Everything lives in `presets.json`: the lighting and pose wording, models and
strength settings.
- Face drifting? Raise `human_fidelity` (max 1.0).
- Variant too similar to the original? Lower `image_fidelity`.
- Want a newer model? Change `image_model` / `video_model` to one your account lists.
  Not every model supports a face reference or an end frame, so if Kling returns
  an error after a change, switch back.

## Results log

Every generation is added to `output/runs.csv`. The columns `face_match`,
`lighting`, `pose_natural` (score 1-5) and `keep` (y/n) are for you to fill in,
so later you can see which lighting and poses work best.

# video_gen

Generate videos with **MiniMax H3** (open weights) from the command line. H3 runs
in ComfyUI on a rented NVIDIA GPU; this tool, on your Mac, fills in a workflow
(prompt, start image, seed, size), runs it, and downloads the MP4 into `output/`.

```
python -m vidgen check                                         # server up? H3 weights there?
python -m vidgen inspect workflows/h3_i2v.json                 # where prompt/image/seed go
python -m vidgen generate workflows/h3_i2v.json \
    -i ../faces_square/DSCF5110_face.jpg \
    -p "she turns to the camera and smiles, golden hour, handheld" \
    --size 768x1344 --count 3                                  # 3 vertical variations
```

Add `--dry-run` to `generate` to check the bindings without touching the server.
Finished clips can go straight to `../instagram_poster` as Reels.

## Why not on the Mac?

H3 is built for CUDA: the int8 checkpoints alone are tens of GB, and the fast
attention kernels are NVIDIA-only. A 16 GB M1 Pro would swap or run out of memory.
A 24 GB+ card (RTX 4090 / L40S / A6000, or a 5090 with 32 GB) on RunPod or
Vast.ai costs well under $1/hour and renders a clip in minutes.

Local (open-weight) limits: base model at a 768-px short edge (768×1344 for 9:16),
about 15 s at 24 fps. 2K output is only on MiniMax's hosted service; upscale separately.

## GPU server setup (once per box)

1. Rent a GPU pod with ComfyUI preinstalled (e.g. a RunPod "ComfyUI" template),
   24 GB VRAM or more, ~100 GB disk.
2. Update ComfyUI to **0.30.0 or newer** (0.34+ for multiframe reference, 0.36+ for FastH3).
3. Open ComfyUI in the browser, go to **Templates → Video → MiniMax H3**
   (Image to Video or Text to Video). The template offers to download its
   missing models from `Comfy-Org/MiniMax-H3` on Hugging Face; accept.
   The default checkpoint is `minimax_h3_fl2va_pruned_int8_convrot.safetensors`
   (`ref2va` for reference-to-video).
4. Run the template once in the browser to confirm it works.
5. **Workflow → Export (API)** and save the file into `video_gen/workflows/`,
   e.g. `h3_i2v.json`. (A normal "Save" gives the UI format, which won't work.)

### Connect from the Mac

Don't expose port 8188 publicly. ComfyUI has no auth. Tunnel it over SSH:

```
ssh -N -L 8188:localhost:8188 root@<pod-ip> -p <ssh-port>
```

and leave `COMFY_URL=http://127.0.0.1:8188` in `.env`. If you use an
authenticated proxy instead, set `COMFY_URL` to it and `COMFY_TOKEN` to its bearer token.

### Mac setup

```
cd video_gen
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m vidgen check
python -m pytest
```

## Bindings: where parameters go

`inspect` prints every node and the guessed target for each parameter:

| parameter   | guessed from |
|-------------|--------------|
| `prompt`    | the one text input whose node title isn't "negative" |
| `negative`  | text input in a node titled "...negative..." |
| `image`     | first `LoadImage` (not titled end/last) |
| `end_image` | `LoadImage` titled "...end..." or "...last..." |
| `seed`      | every `seed` / `noise_seed` input |
| `width`, `height`, `length`, `fps`, `steps` | inputs with those names |

If a guess is wrong or missing (H3 templates may use their own node types), pin
the targets in a sidecar next to the workflow, `workflows/h3_i2v.bindings.json`:

```json
{
  "prompt": "16.text",
  "image": "52.image",
  "seed": ["3.noise_seed"],
  "width": "61.width",
  "height": "61.height",
  "length": "61.length"
}
```

Anything else can be set per run with `--set NODE.INPUT=VALUE`, e.g.
`--set 3.cfg=4.5` or `--set 1.unet_name=minimax_h3_fl2va_pruned_bf16.safetensors`.

## Output

Each clip is saved as `output/<time>_<prompt-slug>_s<seed>.mp4` with a matching
`.json` recording the workflow, seed and parameters, so you can re-run a good one
exactly (`--seed`).

## Licensing

The H3 weights are open, but the sources disagree on commercial use: Comfy's docs
say commercial use of *locally generated* output needs a MiniMax commercial license
(sold through Comfy), while MiniMax's page describes a royalty-free community
license. Check the current license before using clips in paid work.

## Files

```
vidgen/comfy.py     ComfyUI HTTP API: upload, queue, poll history, download
vidgen/workflow.py  API-format workflows, parameter bindings (guessed or sidecar)
vidgen/cli.py       command line
workflows/          your exported H3 workflows (+ optional .bindings.json)
tests/              unit tests with a fake HTTP session (no server needed)
```

Reference: [ComfyUI MiniMax H3 guide](https://docs.comfy.org/tutorials/video/minimax/minimax-h3)

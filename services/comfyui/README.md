# Local pixel-art generation with ComfyUI

HexWorld talks to a local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) server over its HTTP
API (`POST /prompt`, `/history/{id}`, `/view`, `/upload/image`). ComfyUI runs **outside** this repo.

## 1. Install ComfyUI (RTX 5080 / Blackwell)

Blackwell GPUs need a PyTorch build with CUDA 12.8+. The ComfyUI Windows portable release ships one;
otherwise install `torch` from the `cu128` (or newer) index. Put it at `C:\Users\patri\ComfyUI` (or
anywhere) and start it with `--listen 127.0.0.1 --port 8188`.

## 2. Models (all Apache-2.0)

| role | model | where it goes |
|---|---|---|
| text-to-image (anchor + fallback) | **Z-Image Turbo** (6B, 8 steps; FP8 fits 16 GB easily) | `models/diffusion_models/` |
| text encoder | Qwen3-4B text encoder used by Z-Image | `models/text_encoders/` |
| VAE | Z-Image VAE (`ae.safetensors`) | `models/vae/` |
| style | a Z-Image pixel-art LoRA (e.g. "Pixel Art Style" on Civitai) | `models/loras/` |
| stronger edits (optional) | **FLUX.2 [klein] 4B** or Qwen-Image-Edit-2511 (GGUF) | per their ComfyUI docs |

Check exact filenames against the model cards and update the loader nodes in the workflow JSONs.

## 3. Workflows

`workflows/*.json` are **API-format** graphs with placeholders the backend fills in:

| placeholder | value |
|---|---|
| `{{prompt}}`, `{{negative}}` | image prompts built from the tile agent's design + the world style guide |
| `{{seed}}`, `{{width}}`, `{{height}}` | ints (a value that is exactly a placeholder becomes typed) |
| `{{context_image}}` | uploaded canvas: accepted neighbors drawn around the empty target hex |
| `{{mask_image}}` | uploaded mask: white over the target hex |
| `{{ref_image_1..3}}` | uploaded style references (the world's anchor tile) |

- `txt2img_tile.json`: generates the anchor candidates, and any tile with no accepted neighbors.
- `neighbor_inpaint.json`: generates every other tile **into its surroundings**. The model sees
  the real neighbor pixels and only repaints the target hex, so seams continue. Its output is the
  full canvas, and the backend crops the hex back out.

The shipped graphs are a starting point: node names and inputs vary between ComfyUI versions. If one
fails to queue, build the graph in the ComfyUI UI, use **Workflow → Export (API)**, and put the
placeholders back. A FLUX.2 klein / Qwen-Image-Edit graph that wires `{{ref_image_1}}` as a reference
image gives the strongest style lock.

## 4. Point HexWorld at it

```
HEXWORLD_IMAGE=comfyui
HEXWORLD_IMAGE_FALLBACK=stub     # or openai; used automatically if ComfyUI errors (circuit breaker)
```

Every output then goes through `hexworld/art/pixelize.py`: palette-first quantization onto the world's
master palette, mode-pooled down to the tile resolution, then hex-masked. That makes the result true
pixel art regardless of the model. `pip install proper-pixel-art` (extra `pixel`) adds grid recovery
for "fake pixel" diffusion output.

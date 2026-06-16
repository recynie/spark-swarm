from __future__ import annotations

import json
import os
import platform
import sys
import time
from pathlib import Path

import torch
from diffusers import AutoPipelineForText2Image


SPEC_PATH = Path("/workspace/spec.json")
OUTPUT_DIR = Path("/output")


def _device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _dtype(device: str):
    if device == "cuda":
        return torch.float16
    return torch.float32


def _load_pipeline(model_id: str, *, dtype):
    kwargs = {
        "torch_dtype": dtype,
        "use_safetensors": True,
    }
    try:
        return AutoPipelineForText2Image.from_pretrained(
            model_id,
            local_files_only=True,
            **kwargs,
        )
    except Exception as exc:
        print(
            f"Local model cache miss for {model_id}: {exc}. Falling back to Hugging Face Hub.",
            file=sys.stderr,
            flush=True,
        )
        return AutoPipelineForText2Image.from_pretrained(model_id, **kwargs)


def main() -> int:
    spec = json.loads(SPEC_PATH.read_text())
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    images_dir = OUTPUT_DIR / "images"
    images_dir.mkdir(exist_ok=True)

    model_id = os.environ.get("IMAGE_CASE_MODEL_ID", spec["model_id"])
    device = _device()
    start = time.perf_counter()

    pipe = _load_pipeline(model_id, dtype=_dtype(device))
    pipe = pipe.to(device)
    if hasattr(pipe, "set_progress_bar_config"):
        pipe.set_progress_bar_config(disable=True)

    generator_device = "cuda" if device == "cuda" else "cpu"
    generator = torch.Generator(device=generator_device).manual_seed(int(spec["seed"]))
    image = pipe(
        prompt=spec["prompt"],
        negative_prompt=spec["negative_prompt"],
        width=int(spec["width"]),
        height=int(spec["height"]),
        num_inference_steps=int(spec["steps"]),
        guidance_scale=float(spec["guidance_scale"]),
        generator=generator,
    ).images[0]

    image_path = images_dir / f"{spec['name']}.png"
    image.save(image_path)

    elapsed = time.perf_counter() - start
    metadata = {
        "name": spec["name"],
        "title": spec["title"],
        "channel": spec["channel"],
        "model_id": model_id,
        "prompt": spec["prompt"],
        "negative_prompt": spec["negative_prompt"],
        "seed": spec["seed"],
        "width": spec["width"],
        "height": spec["height"],
        "steps": spec["steps"],
        "guidance_scale": spec["guidance_scale"],
        "elapsed_seconds": elapsed,
        "device": device,
        "python": platform.python_version(),
        "torch": torch.__version__,
        "output_image": str(image_path.relative_to(OUTPUT_DIR)),
    }
    (OUTPUT_DIR / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    (OUTPUT_DIR / "preview.html").write_text(_preview_html(metadata), encoding="utf-8")
    print(json.dumps({"generated": metadata["output_image"], "elapsed_seconds": elapsed, "device": device}))
    return 0


def _preview_html(metadata: dict) -> str:
    title = _esc(metadata["title"])
    image = _esc(metadata["output_image"])
    prompt = _esc(metadata["prompt"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ margin: 0; font-family: Arial, sans-serif; color: #202124; background: #f5f5f0; }}
main {{ max-width: 960px; margin: 0 auto; padding: 32px; }}
img {{ width: 100%; max-height: 80vh; object-fit: contain; background: #fff; border: 1px solid #ddd; }}
.meta {{ margin-top: 16px; display: grid; gap: 8px; color: #555; }}
</style>
</head>
<body>
<main>
<h1>{title}</h1>
<img src="{image}" alt="{title}">
<div class="meta">
<div>{_esc(metadata["channel"])} · {_esc(str(metadata["width"]))}x{_esc(str(metadata["height"]))}</div>
<div>{_esc(metadata["model_id"])} · seed {_esc(str(metadata["seed"]))}</div>
<p>{prompt}</p>
</div>
</main>
</body>
</html>
"""


def _esc(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


if __name__ == "__main__":
    raise SystemExit(main())

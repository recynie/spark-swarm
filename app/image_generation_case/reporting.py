from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_campaign_gallery(run_dir: Path, *, campaign_name: str, model_id: str, tasks: list[dict]) -> Path:
    assets = []
    for task in tasks:
        task_dir = run_dir / "artifacts" / task["creative_name"]
        metadata_path = task_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = read_json(metadata_path)
        image = metadata.get("output_image")
        if not image:
            continue
        assets.append(
            {
                "title": metadata["title"],
                "channel": metadata["channel"],
                "image": str((Path("artifacts") / task["creative_name"] / image).as_posix()),
                "size": f"{metadata['width']}x{metadata['height']}",
                "seed": metadata["seed"],
                "elapsed_seconds": metadata["elapsed_seconds"],
                "device": metadata["device"],
                "prompt": metadata["prompt"],
            }
        )

    manifest = {
        "campaign_name": campaign_name,
        "model_id": model_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "assets": assets,
    }
    write_json(run_dir / "campaign-manifest.json", manifest)

    gallery_path = run_dir / "campaign-gallery.html"
    gallery_path.write_text(_gallery_html(manifest), encoding="utf-8")
    return gallery_path


def write_benchmark(run_dir: Path, *, local: dict | None, swarm: dict | None) -> Path:
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "local": local,
        "swarm": swarm,
        "comparison": _comparison(local, swarm),
    }
    path = run_dir / "benchmark.json"
    write_json(path, payload)
    return path


def _comparison(local: dict | None, swarm: dict | None) -> dict | None:
    if not local or not swarm:
        return None
    local_elapsed = local.get("elapsed_seconds")
    swarm_elapsed = swarm.get("elapsed_seconds")
    if not local_elapsed or not swarm_elapsed:
        return None
    return {
        "speedup": local_elapsed / swarm_elapsed,
        "saved_seconds": local_elapsed - swarm_elapsed,
        "local_elapsed_seconds": local_elapsed,
        "swarm_elapsed_seconds": swarm_elapsed,
    }


def _gallery_html(manifest: dict) -> str:
    cards = "\n".join(_asset_card(asset) for asset in manifest["assets"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(manifest["campaign_name"])}</title>
<style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; background: #f4f1ec; color: #202124; font-family: Inter, Arial, sans-serif; }}
header {{ padding: 28px 32px 18px; border-bottom: 1px solid #d8d1c5; background: #fffaf3; }}
h1 {{ margin: 0 0 8px; font-size: clamp(28px, 4vw, 48px); letter-spacing: 0; }}
.sub {{ color: #5f6368; }}
main {{ padding: 24px 32px 40px; display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 18px; }}
.asset {{ background: white; border: 1px solid #ddd5ca; border-radius: 8px; overflow: hidden; }}
.asset img {{ width: 100%; aspect-ratio: 1 / 1; object-fit: cover; display: block; background: #eee; }}
.asset .body {{ padding: 14px; display: grid; gap: 8px; }}
.meta {{ color: #5f6368; font-size: 13px; display: flex; gap: 10px; flex-wrap: wrap; }}
p {{ margin: 0; color: #3c4043; line-height: 1.45; font-size: 14px; }}
</style>
</head>
<body>
<header>
<h1>{_esc(manifest["campaign_name"])}</h1>
<div class="sub">{_esc(manifest["model_id"])} · {len(manifest["assets"])} generated assets</div>
</header>
<main>
{cards}
</main>
</body>
</html>
"""


def _asset_card(asset: dict) -> str:
    return f"""<article class="asset">
<img src="{_esc(asset["image"])}" alt="{_esc(asset["title"])}">
<div class="body">
<h2>{_esc(asset["title"])}</h2>
<div class="meta"><span>{_esc(asset["channel"])}</span><span>{_esc(asset["size"])}</span><span>seed {_esc(str(asset["seed"]))}</span><span>{asset["elapsed_seconds"]:.1f}s</span></div>
<p>{_esc(asset["prompt"])}</p>
</div>
</article>"""


def _esc(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )

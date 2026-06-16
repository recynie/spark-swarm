from __future__ import annotations

import base64
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from string import Template


CASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = CASE_DIR / "static"
RUNS_DIR = CASE_DIR / "runs"
DOCKERFILE_TEMPLATE = CASE_DIR / "docker" / "Dockerfile.template"
GENERATOR_SOURCE = CASE_DIR / "generator.py"

DEFAULT_MODEL_ID = "stabilityai/sd-turbo"
DEFAULT_MASTER_URL = "http://127.0.0.1:8000"
DEFAULT_BASE_IMAGE = "python:3.11-slim"
DEFAULT_IMAGE_COUNT = 12
MAX_IMAGE_COUNT = 24
DEFAULT_PROMPT = (
    "premium product photograph of a compact AI powered travel espresso maker, brushed graphite metal, "
    "fresh espresso crema, modern consumer electronics campaign, realistic"
)
DEFAULT_NEGATIVE_PROMPT = "text, watermark, logo, blurry, deformed, low quality, distorted hands, unreadable labels"
CAMPAIGN_NAME = "Text-to-Image Swarm Studio"


@dataclass(frozen=True)
class CreativeSpec:
    name: str
    title: str
    channel: str
    width: int
    height: int
    seed: int
    steps: int
    guidance_scale: float
    priority: int
    cpu_limit: float
    memory_limit_mb: int
    prompt: str
    negative_prompt: str


@dataclass(frozen=True)
class StylePreset:
    slug: str
    title: str
    prompt: str


STYLE_PRESETS: tuple[StylePreset, ...] = (
    StylePreset("studio", "Studio Hero", "premium studio lighting, clean background, sharp commercial product detail"),
    StylePreset("cinematic", "Cinematic", "cinematic lighting, shallow depth of field, dramatic but realistic composition"),
    StylePreset("editorial", "Editorial", "editorial magazine composition, natural materials, polished lifestyle styling"),
    StylePreset("macro", "Macro Detail", "macro detail shot, tactile surface texture, controlled highlights, high detail"),
    StylePreset("social", "Social Vertical", "social campaign image, energetic framing, natural light, aspirational mood"),
    StylePreset("retail", "Retail Ready", "ecommerce-ready product photography, clear silhouette, neutral surface"),
    StylePreset("outdoor", "Outdoor Use", "outdoor morning light, travel context, realistic environment, premium gear"),
    StylePreset("minimal", "Minimal", "minimal composition, strong negative space, soft shadows, refined color palette"),
    StylePreset("workspace", "Workspace", "modern workspace scene, practical product use, realistic desk lighting"),
    StylePreset("ad-a", "Ad Variant A", "paid ad visual, bold crop, high contrast, immediately readable product shape"),
    StylePreset("ad-b", "Ad Variant B", "paid ad visual, warmer mood, lifestyle context, natural depth"),
    StylePreset("packshot", "Packshot", "packaging and product packshot, crisp edges, catalog quality lighting"),
)


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return (slug or "image-run")[:64].strip("-") or "image-run"


def campaign_id(label: str = CAMPAIGN_NAME) -> str:
    from datetime import datetime, timezone

    return f"{slugify(label)}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"


def build_generation_specs(
    *,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    count: int = DEFAULT_IMAGE_COUNT,
    width: int = 768,
    height: int = 768,
    seed_base: int = 4200,
    steps: int = 4,
    guidance_scale: float = 0.0,
    cpu_limit: float = 4.0,
    memory_limit_mb: int = 16384,
) -> tuple[CreativeSpec, ...]:
    clean_prompt = prompt.strip() or DEFAULT_PROMPT
    clean_negative = negative_prompt.strip() or DEFAULT_NEGATIVE_PROMPT
    image_count = max(1, min(count, MAX_IMAGE_COUNT))
    specs: list[CreativeSpec] = []

    for index in range(image_count):
        style = STYLE_PRESETS[index % len(STYLE_PRESETS)]
        cycle = index // len(STYLE_PRESETS)
        variant_name = f"variant-{index + 1:02d}-{style.slug}"
        if cycle:
            variant_name = f"{variant_name}-{cycle + 1}"
        specs.append(
            CreativeSpec(
                name=variant_name,
                title=style.title,
                channel=f"Variant {index + 1:02d}",
                width=width,
                height=height,
                seed=seed_base + index + 1,
                steps=steps,
                guidance_scale=guidance_scale,
                priority=index + 1,
                cpu_limit=cpu_limit,
                memory_limit_mb=memory_limit_mb,
                prompt=f"{clean_prompt}, {style.prompt}",
                negative_prompt=clean_negative,
            )
        )
    return tuple(specs)


CREATIVES: tuple[CreativeSpec, ...] = build_generation_specs()


def render_task_dockerfile(
    spec: CreativeSpec,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    base_image: str = DEFAULT_BASE_IMAGE,
    deps_preinstalled: bool = False,
) -> str:
    template = Template(DOCKERFILE_TEMPLATE.read_text())
    payload = asdict(spec) | {"model_id": model_id}
    spec_json = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    generator_py = GENERATOR_SOURCE.read_bytes()
    return template.substitute(
        base_image=base_image,
        deps_preinstalled="1" if deps_preinstalled else "0",
        spec_json_b64=base64.b64encode(spec_json).decode("ascii"),
        generator_py_b64=base64.b64encode(generator_py).decode("ascii"),
    )


def campaign_manifest(
    model_id: str,
    *,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    specs: tuple[CreativeSpec, ...] | None = None,
) -> dict:
    creative_specs = specs or CREATIVES
    return {
        "campaign_name": CAMPAIGN_NAME,
        "model_id": model_id,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "creatives": [asdict(spec) for spec in creative_specs],
    }

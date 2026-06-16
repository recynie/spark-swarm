from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from app.image_generation_case.campaign import (
    CAMPAIGN_NAME,
    DEFAULT_BASE_IMAGE,
    DEFAULT_IMAGE_COUNT,
    DEFAULT_MASTER_URL,
    DEFAULT_MODEL_ID,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_PROMPT,
    CreativeSpec,
    build_generation_specs,
    campaign_id,
    campaign_manifest,
    render_task_dockerfile,
    slugify,
    RUNS_DIR,
)
from app.image_generation_case.reporting import build_campaign_gallery, read_json, write_benchmark, write_json
from app.image_generation_case.swarm_client import SwarmClient


FINAL_STATUSES = {"SUCCESS", "FAILED", "CANCELLED"}


def create_run_dir(run_id: str | None = None, *, label: str = CAMPAIGN_NAME) -> Path:
    if run_id:
        run_dir = RUNS_DIR / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        return run_dir

    base_id = campaign_id(label)
    run_dir = RUNS_DIR / base_id
    suffix = 2
    while run_dir.exists():
        run_dir = RUNS_DIR / f"{base_id}-{suffix}"
        suffix += 1
    run_dir.mkdir(parents=True, exist_ok=False)
    return run_dir


def submit_campaign(
    *,
    master_url: str = DEFAULT_MASTER_URL,
    model_id: str = DEFAULT_MODEL_ID,
    base_image: str = DEFAULT_BASE_IMAGE,
    deps_preinstalled: bool = False,
    timeout_seconds: int = 900,
    run_id: str | None = None,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    image_count: int = DEFAULT_IMAGE_COUNT,
    width: int = 768,
    height: int = 768,
    seed_base: int = 4200,
    steps: int = 4,
    guidance_scale: float = 0.0,
) -> dict:
    client = SwarmClient(master_url)
    client.health()
    specs = build_generation_specs(
        prompt=prompt,
        negative_prompt=negative_prompt,
        count=image_count,
        width=width,
        height=height,
        seed_base=seed_base,
        steps=steps,
        guidance_scale=guidance_scale,
    )
    run_dir = create_run_dir(run_id, label=prompt)
    write_json(run_dir / "campaign-input.json", campaign_manifest(model_id, prompt=prompt, negative_prompt=negative_prompt, specs=specs))

    submitted = []
    dockerfiles_dir = run_dir / "dockerfiles"
    dockerfiles_dir.mkdir(exist_ok=True)
    for spec in specs:
        dockerfile_content = render_task_dockerfile(
            spec,
            model_id=model_id,
            base_image=base_image,
            deps_preinstalled=deps_preinstalled,
        )
        (dockerfiles_dir / f"{spec.name}.Dockerfile").write_text(dockerfile_content, encoding="utf-8")
        task = client.submit_task(
            name=f"image-case:{run_dir.name}:{spec.name}",
            dockerfile_content=dockerfile_content,
            priority=spec.priority,
            cpu_limit=spec.cpu_limit,
            memory_limit_mb=spec.memory_limit_mb,
            timeout_seconds=timeout_seconds,
        )
        submitted.append({"creative_name": spec.name, "spec": asdict(spec), "task_id": task["id"], "task": task})

    state = _base_state(
        run_dir=run_dir,
        mode="swarm",
        model_id=model_id,
        base_image=base_image,
        deps_preinstalled=deps_preinstalled,
        prompt=prompt,
        negative_prompt=negative_prompt,
        specs=specs,
        tasks=submitted,
        extra={"master_url": master_url, "status": "SUBMITTED"},
    )
    _persist_state(run_dir, state)
    return _state_with_assets(run_dir, state)


def create_local_generation(
    *,
    model_id: str = DEFAULT_MODEL_ID,
    base_image: str = DEFAULT_BASE_IMAGE,
    deps_preinstalled: bool = False,
    run_id: str | None = None,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    image_count: int = DEFAULT_IMAGE_COUNT,
    width: int = 768,
    height: int = 768,
    seed_base: int = 4200,
    steps: int = 4,
    guidance_scale: float = 0.0,
) -> dict:
    specs = build_generation_specs(
        prompt=prompt,
        negative_prompt=negative_prompt,
        count=image_count,
        width=width,
        height=height,
        seed_base=seed_base,
        steps=steps,
        guidance_scale=guidance_scale,
    )
    run_dir = create_run_dir(run_id, label=f"local-{prompt}") if run_id else create_run_dir(label=f"local-{prompt}")
    write_json(run_dir / "campaign-input.json", campaign_manifest(model_id, prompt=prompt, negative_prompt=negative_prompt, specs=specs))

    tasks = [
        {
            "creative_name": spec.name,
            "spec": asdict(spec),
            "task_id": spec.name,
            "task": {
                "id": spec.name,
                "name": f"local:{run_dir.name}:{spec.name}",
                "status": "PENDING",
                "assigned_host_id": "local",
                "output_files": [],
                "artifact_urls": {},
            },
        }
        for spec in specs
    ]
    state = _base_state(
        run_dir=run_dir,
        mode="local",
        model_id=model_id,
        base_image=base_image,
        deps_preinstalled=deps_preinstalled,
        prompt=prompt,
        negative_prompt=negative_prompt,
        specs=specs,
        tasks=tasks,
        extra={"status": "PENDING"},
    )
    _persist_state(run_dir, state)
    return _state_with_assets(run_dir, state)


def refresh_campaign(run_id: str, *, master_url: str | None = None, download_artifacts: bool = True) -> dict:
    run_dir = RUNS_DIR / run_id
    state = read_json(run_dir / "state.json")
    if state.get("mode") == "local":
        return _state_with_assets(run_dir, state)

    client = SwarmClient(master_url or state["master_url"])
    refreshed = []
    for item in state["tasks"]:
        detail = client.task(item["task_id"])
        next_item = item | {"task": detail}
        refreshed.append(next_item)
        if download_artifacts and detail["status"] == "SUCCESS":
            _download_task_artifacts(client, run_dir, item["creative_name"], detail)

    state["tasks"] = refreshed
    if all(item["task"]["status"] in FINAL_STATUSES for item in refreshed):
        state["status"] = "COMPLETED" if all(item["task"]["status"] == "SUCCESS" for item in refreshed) else "FAILED"
        state["completed_at"] = state.get("completed_at") or time.time()
        if state["status"] == "COMPLETED":
            build_campaign_gallery(run_dir, campaign_name=state["campaign_name"], model_id=state["model_id"], tasks=refreshed)
            state["gallery"] = "campaign-gallery.html"
            state["swarm_metrics"] = _swarm_metrics(state)
            _update_benchmark_if_possible(run_dir, state)
    else:
        state["status"] = "RUNNING"
    _persist_state(run_dir, state)
    return _state_with_assets(run_dir, state)


def refresh_run(run_id: str) -> dict:
    run_dir = RUNS_DIR / run_id
    state = read_json(run_dir / "state.json")
    if state.get("mode") == "swarm":
        return refresh_campaign(run_id)
    return _state_with_assets(run_dir, state)


def read_run_state(run_id: str) -> dict:
    run_dir = RUNS_DIR / run_id
    return _state_with_assets(run_dir, read_json(run_dir / "state.json"))


def wait_for_campaign(run_id: str, *, poll_seconds: float = 2.0, timeout_seconds: int = 3600) -> dict:
    start = time.perf_counter()
    while True:
        state = refresh_campaign(run_id)
        if state["status"] in {"COMPLETED", "FAILED"}:
            return state
        if time.perf_counter() - start > timeout_seconds:
            raise TimeoutError(f"Campaign {run_id} did not complete within {timeout_seconds}s")
        time.sleep(poll_seconds)


def run_local_generation(
    run_id: str,
    *,
    enable_gpu: bool = True,
    model_cache_dir: str | None = None,
) -> dict:
    run_dir = RUNS_DIR / run_id
    state = read_json(run_dir / "state.json")
    state["status"] = "RUNNING"
    state["started_at"] = state.get("started_at") or time.time()
    _persist_state(run_dir, state)

    started = time.perf_counter()
    results = []
    try:
        for item in state["tasks"]:
            spec = CreativeSpec(**item["spec"])
            task = item["task"]
            task["status"] = "BUILDING"
            task["started_at"] = task.get("started_at") or _now_iso()
            _persist_state(run_dir, state)

            output_dir, build_dir = _prepare_local_task_dir(run_dir, spec)
            dockerfile_path = build_dir / "Dockerfile"
            dockerfile_path.write_text(
                render_task_dockerfile(
                    spec,
                    model_id=state["model_id"],
                    base_image=state["base_image"],
                    deps_preinstalled=state["deps_preinstalled"],
                ),
                encoding="utf-8",
            )
            image_tag = f"spark-swarm-image-case-local:{slugify(run_dir.name)}-{spec.name}"

            build_started = time.perf_counter()
            subprocess.run(["docker", "build", "-t", image_tag, str(build_dir)], check=True)
            task["status"] = "RUNNING"
            _persist_state(run_dir, state)

            subprocess.run(_local_run_command(image_tag, output_dir, enable_gpu=enable_gpu, model_cache_dir=model_cache_dir), check=True)
            elapsed = time.perf_counter() - build_started
            artifact_dir = run_dir / "artifacts" / spec.name
            if artifact_dir.exists():
                shutil.rmtree(artifact_dir)
            shutil.copytree(output_dir, artifact_dir)
            task["status"] = "SUCCESS"
            task["completed_at"] = _now_iso()
            task["output_files"] = _output_files(artifact_dir)
            results.append({"creative_name": spec.name, "elapsed_seconds": elapsed, "output_dir": str(output_dir)})
            _persist_state(run_dir, state)
    except Exception as exc:
        state["status"] = "FAILED"
        state["error"] = str(exc)
        state["completed_at"] = time.time()
        for item in state["tasks"]:
            if item["task"]["status"] in {"PENDING", "BUILDING", "RUNNING"}:
                item["task"]["status"] = "FAILED"
                item["task"]["error_message"] = str(exc)
                item["task"]["completed_at"] = _now_iso()
                break
        _persist_state(run_dir, state)
        raise

    elapsed = time.perf_counter() - started
    local_metrics = {
        "run_id": run_dir.name,
        "campaign_name": state["campaign_name"],
        "model_id": state["model_id"],
        "elapsed_seconds": elapsed,
        "tasks": results,
    }
    state["status"] = "COMPLETED"
    state["completed_at"] = time.time()
    state["local_metrics"] = local_metrics
    write_json(run_dir / "local-metrics.json", local_metrics)
    build_campaign_gallery(run_dir, campaign_name=f"{state['campaign_name']} Local", model_id=state["model_id"], tasks=state["tasks"])
    state["gallery"] = "campaign-gallery.html"
    write_benchmark(run_dir, local=local_metrics, swarm=None)
    _persist_state(run_dir, state)
    return local_metrics


def run_local_baseline(
    *,
    model_id: str = DEFAULT_MODEL_ID,
    base_image: str = DEFAULT_BASE_IMAGE,
    deps_preinstalled: bool = False,
    run_id: str | None = None,
    enable_gpu: bool = True,
    model_cache_dir: str | None = None,
    prompt: str = DEFAULT_PROMPT,
    negative_prompt: str = DEFAULT_NEGATIVE_PROMPT,
    image_count: int = DEFAULT_IMAGE_COUNT,
) -> dict:
    state = create_local_generation(
        model_id=model_id,
        base_image=base_image,
        deps_preinstalled=deps_preinstalled,
        run_id=run_id,
        prompt=prompt,
        negative_prompt=negative_prompt,
        image_count=image_count,
    )
    return run_local_generation(state["run_id"], enable_gpu=enable_gpu, model_cache_dir=model_cache_dir)


def compare_runs(*, swarm_run_id: str, local_run_id: str) -> dict:
    swarm_run_dir = RUNS_DIR / swarm_run_id
    local_run_dir = RUNS_DIR / local_run_id
    swarm_state = read_json(swarm_run_dir / "state.json")
    local_metrics = read_json(local_run_dir / "local-metrics.json")
    swarm_key = _comparison_key(swarm_run_dir, state=swarm_state, tasks=swarm_state.get("tasks", []))
    local_key = _comparison_key(local_run_dir, metrics=local_metrics)
    if swarm_key and local_key and swarm_key != local_key:
        raise ValueError("Runs were generated from different prompt or image settings")
    benchmark_path = write_benchmark(swarm_run_dir, local=local_metrics, swarm=swarm_state.get("swarm_metrics"))
    benchmark = read_json(benchmark_path)
    write_json(local_run_dir / "benchmark.json", benchmark)
    return benchmark


def list_runs() -> list[dict]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    runs = []
    for path in sorted(RUNS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_dir():
            continue
        state_path = path / "state.json"
        local_path = path / "local-metrics.json"
        if state_path.exists():
            state = read_json(state_path)
            tasks = state.get("tasks", [])
            assets = _collect_assets(path, tasks)
            benchmark = _read_optional_json(path / "benchmark.json")
            swarm_metrics = state.get("swarm_metrics") or {}
            local_metrics = state.get("local_metrics") or _read_optional_json(local_path) or {}
            runs.append(
                {
                    "run_id": path.name,
                    "type": state.get("mode", "swarm"),
                    "status": state.get("status"),
                    "campaign_name": state.get("campaign_name"),
                    "model_id": state.get("model_id"),
                    "prompt": state.get("prompt"),
                    "image_count": state.get("image_count") or len(tasks),
                    "created_at": state.get("created_at"),
                    "completed_at": state.get("completed_at"),
                    "assets_count": len(assets),
                    "gallery": "campaign-gallery.html" if (path / "campaign-gallery.html").exists() else None,
                    "swarm_elapsed_seconds": swarm_metrics.get("elapsed_seconds"),
                    "local_elapsed_seconds": local_metrics.get("elapsed_seconds"),
                    "has_benchmark": bool((benchmark or {}).get("comparison")),
                    "comparison_key": _comparison_key(path, state=state, tasks=tasks),
                }
            )
        elif local_path.exists():
            metrics = read_json(local_path)
            manifest = _read_optional_json(path / "campaign-input.json") or {}
            creatives = manifest.get("creatives") or []
            tasks = [{"creative_name": item["name"]} for item in creatives if item.get("name")]
            assets = _collect_assets(path, tasks)
            runs.append(
                {
                    "run_id": path.name,
                    "type": "local",
                    "status": "COMPLETED",
                    "campaign_name": metrics.get("campaign_name"),
                    "model_id": metrics.get("model_id"),
                    "prompt": manifest.get("prompt"),
                    "image_count": len(creatives) or len(metrics.get("tasks", [])),
                    "assets_count": len(assets),
                    "local_elapsed_seconds": metrics.get("elapsed_seconds"),
                    "gallery": "campaign-gallery.html" if (path / "campaign-gallery.html").exists() else None,
                    "comparison_key": _comparison_key(path, metrics=metrics),
                }
            )
    return runs


def _comparison_key(
    run_dir: Path,
    *,
    state: dict | None = None,
    metrics: dict | None = None,
    tasks: list[dict] | None = None,
) -> str | None:
    manifest = _read_optional_json(run_dir / "campaign-input.json") or {}
    source = state or metrics or manifest
    creatives = manifest.get("creatives")
    if not creatives and tasks:
        creatives = [item.get("spec", {}) for item in tasks if item.get("spec")]
    if not creatives:
        return None
    payload = {
        "model_id": source.get("model_id") or manifest.get("model_id"),
        "prompt": manifest.get("prompt") or (state or {}).get("prompt"),
        "negative_prompt": manifest.get("negative_prompt") or (state or {}).get("negative_prompt"),
        "creatives": [
            {
                "name": item.get("name"),
                "width": item.get("width"),
                "height": item.get("height"),
                "seed": item.get("seed"),
                "steps": item.get("steps"),
                "guidance_scale": item.get("guidance_scale"),
                "prompt": item.get("prompt"),
                "negative_prompt": item.get("negative_prompt"),
            }
            for item in creatives
        ],
    }
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _base_state(
    *,
    run_dir: Path,
    mode: str,
    model_id: str,
    base_image: str,
    deps_preinstalled: bool,
    prompt: str,
    negative_prompt: str,
    specs: tuple[CreativeSpec, ...],
    tasks: list[dict],
    extra: dict,
) -> dict:
    state = {
        "run_id": run_dir.name,
        "mode": mode,
        "campaign_name": CAMPAIGN_NAME,
        "model_id": model_id,
        "base_image": base_image,
        "deps_preinstalled": deps_preinstalled,
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "image_count": len(specs),
        "created_at": time.time(),
        "tasks": tasks,
        "assets": [],
    }
    state.update(extra)
    return state


def _persist_state(run_dir: Path, state: dict) -> None:
    state["assets"] = _collect_assets(run_dir, state.get("tasks", []))
    write_json(run_dir / "state.json", state)


def _state_with_assets(run_dir: Path, state: dict) -> dict:
    state = dict(state)
    state["assets"] = _collect_assets(run_dir, state.get("tasks", []))
    benchmark_path = run_dir / "benchmark.json"
    if benchmark_path.exists():
        state["benchmark"] = read_json(benchmark_path)
    return state


def _read_optional_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    return read_json(path)


def _collect_assets(run_dir: Path, tasks: list[dict]) -> list[dict]:
    assets = []
    for item in tasks:
        task_dir = run_dir / "artifacts" / item["creative_name"]
        metadata_path = task_dir / "metadata.json"
        if not metadata_path.exists():
            continue
        metadata = read_json(metadata_path)
        image = metadata.get("output_image")
        if not image:
            continue
        assets.append(
            {
                "creative_name": item["creative_name"],
                "title": metadata.get("title", item["creative_name"]),
                "channel": metadata.get("channel", ""),
                "image": str((Path("artifacts") / item["creative_name"] / image).as_posix()),
                "size": f"{metadata.get('width')}x{metadata.get('height')}",
                "seed": metadata.get("seed"),
                "elapsed_seconds": metadata.get("elapsed_seconds"),
                "device": metadata.get("device"),
                "prompt": metadata.get("prompt"),
            }
        )
    return assets


def _download_task_artifacts(client: SwarmClient, run_dir: Path, creative_name: str, task: dict) -> None:
    artifact_urls = task.get("artifact_urls") or {}
    for rel_path, url in artifact_urls.items():
        client.download_artifact(url, run_dir / "artifacts" / creative_name / rel_path)


def _swarm_metrics(state: dict) -> dict:
    started_times = []
    completed_times = []
    task_metrics = []
    for item in state["tasks"]:
        task = item["task"]
        if task.get("started_at"):
            started_times.append(_parse_ts(task["started_at"]))
        if task.get("completed_at"):
            completed_times.append(_parse_ts(task["completed_at"]))
        task_metrics.append(
            {
                "creative_name": item["creative_name"],
                "task_id": task["id"],
                "status": task["status"],
                "assigned_host_id": task.get("assigned_host_id"),
                "started_at": task.get("started_at"),
                "completed_at": task.get("completed_at"),
            }
        )
    elapsed = max(completed_times) - min(started_times) if started_times and completed_times else None
    return {
        "run_id": state["run_id"],
        "campaign_name": state["campaign_name"],
        "model_id": state["model_id"],
        "elapsed_seconds": elapsed,
        "tasks": task_metrics,
    }


def _prepare_local_task_dir(run_dir: Path, spec: CreativeSpec) -> tuple[Path, Path]:
    task_dir = run_dir / "local" / spec.name
    output_dir = task_dir / "output"
    build_dir = task_dir / "build"
    output_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)
    return output_dir, build_dir


def _local_run_command(
    image_tag: str,
    output_dir: Path,
    *,
    enable_gpu: bool,
    model_cache_dir: str | None,
) -> list[str]:
    run_cmd = ["docker", "run", "--rm", "-v", f"{output_dir}:/output"]
    cache_dir = _local_model_cache_dir(model_cache_dir)
    if cache_dir:
        cache_path = Path(cache_dir).expanduser().absolute()
        cache_path.mkdir(parents=True, exist_ok=True)
        run_cmd.extend(["-v", f"{cache_path}:/models"])
        run_cmd.extend(["-e", "HF_HOME=/models/huggingface"])
    if enable_gpu:
        run_cmd.extend(["--gpus", "all"])
    run_cmd.append(image_tag)
    return run_cmd


def _local_model_cache_dir(model_cache_dir: str | None) -> str | None:
    if model_cache_dir:
        return model_cache_dir
    if env_cache_dir := os.environ.get("IMAGE_CASE_MODEL_CACHE_DIR"):
        return env_cache_dir

    shared_agent_cache = Path("/var/lib/spark-swarm/model-cache")
    if shared_agent_cache.exists():
        return str(shared_agent_cache)

    user_cache_parent = Path.home() / ".cache"
    if (user_cache_parent / "huggingface").exists():
        return str(user_cache_parent)

    return str(RUNS_DIR / ".model-cache")


def _output_files(root: Path) -> list[str]:
    return sorted(str(path.relative_to(root)) for path in root.rglob("*") if path.is_file())


def _update_benchmark_if_possible(run_dir: Path, state: dict) -> None:
    local_metrics = None
    benchmark_path = run_dir / "benchmark.json"
    if benchmark_path.exists():
        local_metrics = read_json(benchmark_path).get("local")
    write_benchmark(run_dir, local=local_metrics, swarm=state.get("swarm_metrics"))


def _parse_ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

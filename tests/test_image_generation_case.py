from __future__ import annotations

import base64
import json
import re

from app.image_generation_case import server, workflow
from app.image_generation_case.campaign import (
    CREATIVES,
    DEFAULT_IMAGE_COUNT,
    DEFAULT_MODEL_ID,
    STATIC_DIR,
    build_generation_specs,
    campaign_manifest,
    render_task_dockerfile,
)


def test_campaign_has_prompt_driven_creative_set():
    prompt = "a modular electric kayak photographed for a product launch"
    specs = build_generation_specs(prompt=prompt, count=14)
    manifest = campaign_manifest(DEFAULT_MODEL_ID, prompt=prompt, specs=specs)

    assert manifest["model_id"] == DEFAULT_MODEL_ID
    assert manifest["prompt"] == prompt
    assert len(manifest["creatives"]) == 14
    assert len(CREATIVES) == DEFAULT_IMAGE_COUNT
    assert all(prompt in item["prompt"] for item in manifest["creatives"])
    assert len({item["seed"] for item in manifest["creatives"]}) == 14
    assert len({item["name"] for item in manifest["creatives"]}) == 14


def test_rendered_dockerfile_embeds_diffusers_generator():
    prompt = "architectural render of a quiet library reading lamp"
    spec = build_generation_specs(prompt=prompt, count=1)[0]
    dockerfile = render_task_dockerfile(spec, model_id=DEFAULT_MODEL_ID)

    assert "FROM python:3.11-slim" in dockerfile
    assert "placeholder" not in dockerfile.lower()
    assert "fake" not in dockerfile.lower()

    matches = re.findall(r"base64\.b64decode\('([^']+)'\)", dockerfile)
    assert len(matches) == 2
    spec_json = base64.b64decode(matches[0]).decode("utf-8")
    generator_py = base64.b64decode(matches[1]).decode("utf-8")
    embedded = json.loads(spec_json)
    assert embedded["name"] == spec.name
    assert prompt in embedded["prompt"]
    assert embedded["model_id"] == DEFAULT_MODEL_ID
    assert "AutoPipelineForText2Image.from_pretrained" in generator_py
    assert "local_files_only=True" in generator_py
    assert "Falling back to Hugging Face Hub" in generator_py


def test_local_state_collects_completed_assets(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "RUNS_DIR", tmp_path)
    state = workflow.create_local_generation(prompt="test prompt", image_count=2, run_id="local-test")
    run_dir = tmp_path / state["run_id"]
    first = state["tasks"][0]
    artifact_dir = run_dir / "artifacts" / first["creative_name"]
    (artifact_dir / "images").mkdir(parents=True)
    (artifact_dir / "images" / "result.png").write_bytes(b"png")
    (artifact_dir / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Variant",
                "channel": "Variant 01",
                "output_image": "images/result.png",
                "width": 768,
                "height": 768,
                "seed": 4201,
                "elapsed_seconds": 1.25,
                "device": "cuda",
                "prompt": "test prompt, studio",
            }
        ),
        encoding="utf-8",
    )

    refreshed = workflow.refresh_run(state["run_id"])

    assert refreshed["mode"] == "local"
    assert refreshed["image_count"] == 2
    assert refreshed["assets"] == [
        {
            "creative_name": first["creative_name"],
            "title": "Variant",
            "channel": "Variant 01",
            "image": f"artifacts/{first['creative_name']}/images/result.png",
            "size": "768x768",
            "seed": 4201,
            "elapsed_seconds": 1.25,
            "device": "cuda",
            "prompt": "test prompt, studio",
        }
    ]


def test_run_state_includes_benchmark_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "RUNS_DIR", tmp_path)
    state = workflow.create_local_generation(prompt="test prompt", image_count=1, run_id="local-benchmark")
    run_dir = tmp_path / state["run_id"]
    workflow.write_json(
        run_dir / "benchmark.json",
        {
            "comparison": {
                "speedup": 2.0,
                "saved_seconds": 10.0,
                "local_elapsed_seconds": 20.0,
                "swarm_elapsed_seconds": 10.0,
            }
        },
    )

    refreshed = workflow.refresh_run(state["run_id"])

    assert refreshed["benchmark"]["comparison"]["speedup"] == 2.0


def test_local_run_command_mounts_configured_model_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "model-cache"
    monkeypatch.setenv("IMAGE_CASE_MODEL_CACHE_DIR", str(cache_dir))

    command = workflow._local_run_command(
        "image-tag",
        tmp_path / "output",
        enable_gpu=True,
        model_cache_dir=None,
    )

    assert "-v" in command
    assert f"{cache_dir.absolute()}:/models" in command
    assert "HF_HOME=/models/huggingface" in command
    assert "--gpus" in command


def test_list_runs_exposes_comparison_fields(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "RUNS_DIR", tmp_path)
    state = workflow.create_local_generation(prompt="test prompt", image_count=1, run_id="local-comparison")
    run_dir = tmp_path / state["run_id"]
    workflow.write_json(run_dir / "local-metrics.json", {"elapsed_seconds": 12.5})
    workflow.write_json(run_dir / "benchmark.json", {"comparison": {"speedup": 1.5}})

    runs = workflow.list_runs()

    assert len(runs) == 1
    assert runs[0]["run_id"] == "local-comparison"
    assert runs[0]["type"] == "local"
    assert runs[0]["local_elapsed_seconds"] == 12.5
    assert runs[0]["swarm_elapsed_seconds"] is None
    assert runs[0]["has_benchmark"] is True


def test_product_ui_contains_prompt_flow_and_history_drawer():
    html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")

    assert "Text-to-Image Swarm Studio" in html
    assert 'id="prompt"' in html
    assert 'id="negative-prompt"' in html
    assert 'id="image-count"' in html
    assert "Advanced runtime" in html
    assert "Live Multi-Agent Results" in html
    assert "branch-board" in html
    assert "branchMarkup" in html
    assert "Waiting For Capacity" in html
    assert "currentHosts" in html
    assert "defaultVisibleRun" in html
    assert "r.type === 'swarm' && activeStatuses.includes(r.status)" in html
    assert "assets_count" in html
    assert "High load or low memory" in html
    assert "memoryAvailable < 16384" in html
    assert "Local Sequence" in html
    assert "Final Set" in html
    assert "Performance" in html
    assert "Run Local Match" in html
    assert "startLocalMatch" in html
    assert "activeRunPayload" in html
    assert "comparisonSwarmRunId" in html
    assert "imagePendingText" in html
    assert "statusCounts" in html
    assert "faster with Spark-Swarm" in html
    assert "r.swarm_elapsed_seconds" in html
    assert "r.local_elapsed_seconds" in html
    assert 'id="history-drawer"' in html
    assert html.index('id="live-view"') < html.index('id="final-set"')


def test_server_marks_orphaned_local_run_stale(tmp_path, monkeypatch):
    monkeypatch.setattr(workflow, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(server, "RUNS_DIR", tmp_path)
    server.LOCAL_THREADS.clear()
    state = workflow.create_local_generation(prompt="test prompt", image_count=1, run_id="local-stale")
    run_dir = tmp_path / state["run_id"]
    state["status"] = "RUNNING"
    state["tasks"][0]["task"]["status"] = "RUNNING"
    workflow.write_json(run_dir / "state.json", state)

    runs = server._runs_with_runtime_state()

    assert runs[0]["run_id"] == "local-stale"
    assert runs[0]["status"] == "FAILED"
    assert runs[0]["stale"] is True
    refreshed = workflow.read_json(run_dir / "state.json")
    assert refreshed["status"] == "FAILED"
    assert "background worker" in refreshed["error"]
    assert refreshed["tasks"][0]["task"]["status"] == "FAILED"

# Text-to-Image Swarm Studio

This app is a prompt-driven text-to-image product demo built on spark-swarm. A user enters a prompt, chooses the batch size and generation settings, then runs the same image set either through distributed spark-swarm workers or as a local sequential baseline.

The app is intentionally separate from the core scheduler. It uses the public master API to submit one Dockerized image task per variant, downloads generated artifacts through task artifact URLs, aggregates the final result set, and records a benchmark against local sequential generation.

## Prerequisites

- Docker Engine available to each agent.
- GPU-capable workers for practical generation speed.
- NVIDIA container runtime if `SPARK_SWARM_AGENT_ENABLE_GPU=true`.
- Network access to download the selected Hugging Face model.
- Enough disk space for PyTorch, Diffusers, model weights, and generated artifacts.

Default model:

```text
stabilityai/sd-turbo
```

The app does not generate placeholder images. If model loading or inference fails, the task fails and the UI shows the failed branch.

## Start Spark-Swarm

Start master:

```bash
SPARK_SWARM_ARTIFACT_DIR=/var/lib/spark-swarm/artifacts \
uv run uvicorn master.main:app --host 0.0.0.0 --port 8000
```

Start one or more agents:

```bash
SPARK_SWARM_AGENT_MASTER_URL=http://127.0.0.1:8000 \
SPARK_SWARM_AGENT_HOSTNAME=gpu-worker-1 \
SPARK_SWARM_AGENT_ENABLE_GPU=true \
SPARK_SWARM_AGENT_MODEL_CACHE_DIR=/var/lib/spark-swarm/model-cache \
SPARK_SWARM_AGENT_MAX_ARTIFACT_BYTES=104857600 \
uv run python -m agent.main
```

For the distribution demo, start multiple agents on different worker machines using the same master URL.

## Start The App UI

```bash
IMAGE_CASE_MASTER_URL=http://127.0.0.1:8000 \
IMAGE_CASE_MODEL_ID=stabilityai/sd-turbo \
uv run image-generation-case-ui
```

Open:

```text
http://127.0.0.1:3100
```

The UI supports:

- User-specified prompt and negative prompt.
- Batch count, dimensions, seed base, and inference step settings.
- Spark-Swarm mode with one task per image and branch-style worker visualization.
- Local Sequence mode that renders the same image set one by one.
- Live agent resource display.
- Final result aggregation with generated images and gallery link.
- A history drawer for previous runs.
- Benchmark comparison between distributed and local elapsed time.

## CLI

Render task Dockerfiles without submitting:

```bash
uv run image-generation-case render-dockerfiles \
  --output-dir /tmp/image-case-dockerfiles \
  --prompt "a glass modular desk lamp" \
  --image-count 12
```

Submit a distributed generation batch:

```bash
uv run image-generation-case submit \
  --master-url http://127.0.0.1:8000 \
  --prompt "a compact espresso maker photographed for a premium launch" \
  --image-count 12 \
  --wait
```

Refresh a run:

```bash
uv run image-generation-case refresh <run-id>
```

Run a local sequential baseline:

```bash
IMAGE_CASE_MODEL_CACHE_DIR=/var/lib/spark-swarm/model-cache \
uv run image-generation-case local-baseline \
  --prompt "a compact espresso maker photographed for a premium launch" \
  --image-count 12
```

Compare local and swarm runs:

```bash
uv run image-generation-case compare --swarm-run-id <swarm-run> --local-run-id <local-run>
```

For repeated demos, prebuild a runtime image once and reuse it:

```bash
uv run image-generation-case render-dockerfiles \
  --output-dir /tmp/image-case-dockerfiles
docker build -t spark-swarm-image-case-runtime:sd-turbo \
  -f /tmp/image-case-dockerfiles/variant-01-studio.Dockerfile \
  /tmp/image-case-dockerfiles

uv run image-generation-case submit \
  --master-url http://127.0.0.1:8000 \
  --base-image spark-swarm-image-case-runtime:sd-turbo \
  --deps-preinstalled \
  --image-count 12
```

This only skips repeated dependency installation; generation still uses the real Diffusers model.

## Outputs

Runs are stored under:

```text
app/image_generation_case/runs/<run-id>/
```

Important files:

- `state.json`
- `campaign-input.json`
- `campaign-gallery.html`
- `campaign-manifest.json`
- `benchmark.json`
- `artifacts/<variant>/images/*.png`
- `artifacts/<variant>/metadata.json`

## Completion Checklist

- [x] Case code lives under `app/image_generation_case`.
- [x] Generation uses real Diffusers text-to-image inference.
- [x] Users can provide prompt text and generation settings.
- [x] Distributed mode submits one Dockerfile task per image through spark-swarm.
- [x] Master stores and serves task artifacts.
- [x] Agent uploads real `/output` files to master.
- [x] UI shows branch-style distributed execution and agent resource state.
- [x] UI shows local sequential generation as an ordered stream.
- [x] UI aggregates completed images into a final result set.
- [x] History is isolated in a drawer instead of filling the main workspace.
- [x] Benchmark compares local elapsed time and swarm elapsed time.
- [x] No placeholder or fake image path exists in the generation code.

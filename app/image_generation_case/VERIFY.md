# Verification Notes

Use this file to record evidence from real runs. Do not mark the image case complete unless the evidence shows real model inference, swarm artifact collection, and benchmark comparison.

## Required Evidence

1. Unit tests:

   ```bash
   uv run pytest
   ```

2. Dockerfile rendering:

   ```bash
   uv run image-generation-case render-dockerfiles --output-dir /tmp/image-case-dockerfiles
   ```

3. UI smoke:

   ```bash
   IMAGE_CASE_PORT=3199 uv run image-generation-case-ui
   curl http://127.0.0.1:3199/case/api/state
   ```

4. Swarm artifact smoke with a non-image Dockerfile:

   ```bash
   uv run spark-swarm submit ./app/image_generation_case/smoke_artifact.Dockerfile --name artifact-smoke
   uv run spark-swarm status <task-id>
   ```

5. Real image build:

   ```bash
   docker build -t spark-swarm-image-case-smoke:hero-square /tmp/image-case-dockerfiles -f /tmp/image-case-dockerfiles/hero-square.Dockerfile
   ```

6. Real image inference:

   ```bash
   docker run --rm --gpus all \
     -v /tmp/image-case-output:/output \
     -v /var/lib/spark-swarm/model-cache:/models \
     spark-swarm-image-case-smoke:hero-square
   ```

7. Swarm campaign:

   ```bash
   uv run image-generation-case submit --master-url http://127.0.0.1:8000 --wait
   ```

8. Local baseline:

   ```bash
   uv run image-generation-case local-baseline
   ```

9. Benchmark comparison:

   ```bash
   uv run image-generation-case compare --swarm-run-id <swarm-run> --local-run-id <local-run>
   ```

## Current Session Evidence

- `uv run pytest`: passed, 13 tests.
- Dockerfile rendering: passed, 6 Dockerfiles rendered.
- UI smoke: passed, `/case/api/state` returned JSON and `/` returned HTML.
- Real Docker image build: passed for `hero-square`.
- Real image inference: passed for `hero-square`; generated `/tmp/spark-swarm-image-case-output/images/hero-square.png`, 768x768 PNG, with `metadata.json` reporting `stabilityai/sd-turbo` and `device: cuda`.
- Swarm artifact smoke: passed on temporary master `127.0.0.1:8123`; task `runtime-artifact-smoke` produced `metadata.json` and `result.txt`, and both downloaded successfully through `/api/v1/tasks/{id}/artifacts/...`.

## Remaining Evidence Needed For Full Campaign Completion

- Full six-task swarm image campaign run: passed on temporary master `127.0.0.1:8124` with two current-code local agents. Run ID `ai-travel-espresso-launch-20260615-172649`; 6/6 tasks `SUCCESS`; 6 PNG artifacts downloaded; gallery generated.
- Full six-task local baseline run: passed. Run ID `local-ai-travel-espresso-launch-20260615-172811`; 6/6 images generated sequentially.
- Benchmark comparison: generated. Local sequential elapsed `48.10078276798595s`; swarm elapsed `39.076168060302734s`; speedup `1.2309493268059533x`; saved `9.024614707683213s`.

## External Cluster Note

A campaign submitted to the pre-existing master at `127.0.0.1:8000` failed because remote workers could not reach Docker Hub:

```text
Get "https://registry-1.docker.io/v2/": proxyconnect tcp: dial tcp 127.0.0.1:7890: connect: connection refused
```

This is recorded as an environment/deployment issue, not a fake success path.

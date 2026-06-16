from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.image_generation_case.campaign import (
    DEFAULT_BASE_IMAGE,
    DEFAULT_IMAGE_COUNT,
    DEFAULT_MASTER_URL,
    DEFAULT_MODEL_ID,
    DEFAULT_NEGATIVE_PROMPT,
    DEFAULT_PROMPT,
    build_generation_specs,
    render_task_dockerfile,
)
from app.image_generation_case.workflow import (
    compare_runs,
    refresh_campaign,
    run_local_baseline,
    submit_campaign,
    wait_for_campaign,
)


def main() -> int:
    parser = argparse.ArgumentParser(prog="image-generation-case")
    sub = parser.add_subparsers(dest="command", required=True)

    submit = sub.add_parser("submit")
    submit.add_argument("--master-url", default=DEFAULT_MASTER_URL)
    submit.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    submit.add_argument("--base-image", default=DEFAULT_BASE_IMAGE)
    submit.add_argument("--deps-preinstalled", action="store_true")
    submit.add_argument("--timeout", type=int, default=900)
    submit.add_argument("--wait", action="store_true")
    submit.add_argument("--prompt", default=DEFAULT_PROMPT)
    submit.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    submit.add_argument("--image-count", type=int, default=DEFAULT_IMAGE_COUNT)

    refresh = sub.add_parser("refresh")
    refresh.add_argument("run_id")

    wait = sub.add_parser("wait")
    wait.add_argument("run_id")
    wait.add_argument("--timeout", type=int, default=3600)

    local = sub.add_parser("local-baseline")
    local.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    local.add_argument("--base-image", default=DEFAULT_BASE_IMAGE)
    local.add_argument("--deps-preinstalled", action="store_true")
    local.add_argument("--no-gpu", action="store_true")
    local.add_argument("--model-cache-dir")
    local.add_argument("--prompt", default=DEFAULT_PROMPT)
    local.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    local.add_argument("--image-count", type=int, default=DEFAULT_IMAGE_COUNT)

    compare = sub.add_parser("compare")
    compare.add_argument("--swarm-run-id", required=True)
    compare.add_argument("--local-run-id", required=True)

    render = sub.add_parser("render-dockerfiles")
    render.add_argument("--output-dir", required=True)
    render.add_argument("--model-id", default=DEFAULT_MODEL_ID)
    render.add_argument("--base-image", default=DEFAULT_BASE_IMAGE)
    render.add_argument("--deps-preinstalled", action="store_true")
    render.add_argument("--prompt", default=DEFAULT_PROMPT)
    render.add_argument("--negative-prompt", default=DEFAULT_NEGATIVE_PROMPT)
    render.add_argument("--image-count", type=int, default=DEFAULT_IMAGE_COUNT)

    args = parser.parse_args()
    if args.command == "submit":
        state = submit_campaign(
            master_url=args.master_url,
            model_id=args.model_id,
            base_image=args.base_image,
            deps_preinstalled=args.deps_preinstalled,
            timeout_seconds=args.timeout,
            prompt=args.prompt,
            negative_prompt=args.negative_prompt,
            image_count=args.image_count,
        )
        if args.wait:
            state = wait_for_campaign(state["run_id"])
        print(json.dumps(state, indent=2, ensure_ascii=False))
        return 0
    if args.command == "refresh":
        print(json.dumps(refresh_campaign(args.run_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "wait":
        print(json.dumps(wait_for_campaign(args.run_id, timeout_seconds=args.timeout), indent=2, ensure_ascii=False))
        return 0
    if args.command == "local-baseline":
        print(
            json.dumps(
                run_local_baseline(
                    model_id=args.model_id,
                    base_image=args.base_image,
                    deps_preinstalled=args.deps_preinstalled,
                    enable_gpu=not args.no_gpu,
                    model_cache_dir=args.model_cache_dir,
                    prompt=args.prompt,
                    negative_prompt=args.negative_prompt,
                    image_count=args.image_count,
                ),
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "compare":
        print(json.dumps(compare_runs(swarm_run_id=args.swarm_run_id, local_run_id=args.local_run_id), indent=2, ensure_ascii=False))
        return 0
    if args.command == "render-dockerfiles":
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        specs = build_generation_specs(prompt=args.prompt, negative_prompt=args.negative_prompt, count=args.image_count)
        for spec in specs:
            (output_dir / f"{spec.name}.Dockerfile").write_text(
                render_task_dockerfile(
                    spec,
                    model_id=args.model_id,
                    base_image=args.base_image,
                    deps_preinstalled=args.deps_preinstalled,
                ),
                encoding="utf-8",
            )
        print(json.dumps({"output_dir": str(output_dir), "count": len(specs)}, indent=2))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

"""Configure the RunPod serverless endpoint for cheap LTX-2.5 image-to-video.

Points the worker at the endpoint's RunPod model cache instead of downloading
~40 GB on every cold start, skips the prompt enhancer and the per-boot venv
copy, and keeps scale-to-zero with one worker on 48 GB Ampere GPUs.

    uv run python deploy/runpod/configure_endpoint.py          # show the plan
    uv run python deploy/runpod/configure_endpoint.py --apply  # change RunPod

Reads RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID from the environment or ./.env.
The endpoint's model cache (Lightricks/LTX-2.5 plus a Hugging Face token) is
set in the RunPod console; the REST API cannot configure it.
"""

import argparse
import json
import os
import sys
from pathlib import Path

import httpx

API = "https://rest.runpod.io/v1"
ROOT = Path(__file__).resolve().parents[2]
START_SCRIPT = Path(__file__).with_name("start-cached.sh").read_text(encoding="utf-8")
SECRET_MARKERS = ("TOKEN", "KEY", "SECRET", "PASSWORD")

WORKER_ENV = {
    "RUN_MODE": "worker",
    # Persisting copies the image's venv and ComfyUI into /workspace on every
    # boot (billed), and /runpod-volume is the model cache, not a volume.
    "PERSIST_WORKSPACE": "false",
    "LTX25_PRELOAD_VARIANT": "distilled-int8",
    # The MCP client's LLM writes the prompt, so skip the 10 GB enhancer.
    "LTX25_PRELOAD_PROMPT_ENHANCER": "false",
    "LTX_FRONTEND_ENABLED": "false",
    "COMFY_LOG_LEVEL": "INFO",
}
ENDPOINT_SETTINGS = {
    # The image ships PyTorch for CUDA 13.0. On an older driver its GPU check
    # fails only after the bootstrap has already run on billed time.
    "allowedCudaVersions": ["13.0"],
    "minCudaVersion": "13.0",
    # Cheapest 48 GB tier; the INT8 weights run on Ampere tensor cores.
    "gpuTypeIds": ["NVIDIA A40", "NVIDIA RTX A6000"],
    "gpuCount": 1,
    "workersMin": 0,
    "workersMax": 1,
    "flashboot": True,
}


def load_settings() -> dict:
    values = {}
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and not line.lstrip().startswith("#"):
                values[key.strip()] = value.strip()
    values.update({k: v for k, v in os.environ.items() if k.startswith("RUNPOD_")})
    return values


def redact(env: dict) -> dict:
    return {
        key: "<redacted>" if any(m in key for m in SECRET_MARKERS) else value
        for key, value in env.items()
    }


def call(client: httpx.Client, method: str, path: str, **kwargs):
    response = client.request(method, path, **kwargs)
    if response.is_error:
        sys.exit(f"{method} {path} failed with HTTP {response.status_code}: "
                 f"{response.text[:500]}")
    return response.json()


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--apply", action="store_true", help="change RunPod (default: dry run)"
    )
    arguments = parser.parse_args()

    settings = load_settings()
    key = settings.get("RUNPOD_API_KEY")
    endpoint_id = settings.get("RUNPOD_ENDPOINT_ID")
    if not key or not endpoint_id:
        sys.exit("Set RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID in the environment or .env")

    client = httpx.Client(
        base_url=API, headers={"Authorization": f"Bearer {key}"}, timeout=30
    )
    endpoint = call(client, "GET", f"/endpoints/{endpoint_id}")
    templates = call(
        client, "GET", "/templates", params={"includeEndpointBoundTemplates": "true"}
    )
    template = next(t for t in templates if t["id"] == endpoint["templateId"])

    env = template.get("env") or {}
    secrets = {k: v for k, v in env.items() if any(m in k for m in SECRET_MARKERS)}
    template_patch = {
        "env": WORKER_ENV | secrets,
        "dockerStartCmd": ["bash", "-c", START_SCRIPT],
    }

    print(f"Endpoint {endpoint_id} ({endpoint['name']}), template {template['id']}")
    print("Current template env:", json.dumps(redact(env), indent=2))
    print("Current start command:", template.get("dockerStartCmd"))
    print("New template env:", json.dumps(redact(template_patch["env"]), indent=2))
    print("New start command: bash -c <deploy/runpod/start-cached.sh>")
    for name, value in ENDPOINT_SETTINGS.items():
        print(f"  {name}: {endpoint.get(name)!r} -> {value!r}")
    print(
        f"  unchanged: idleTimeout={endpoint['idleTimeout']} s, "
        f"executionTimeoutMs={endpoint['executionTimeoutMs']}, "
        f"model cache env={sorted(endpoint.get('env') or {})}"
    )

    if not arguments.apply:
        print("\nDry run. Rerun with --apply to change RunPod.")
        return

    call(client, "PATCH", f"/templates/{template['id']}", json=template_patch)
    call(client, "PATCH", f"/endpoints/{endpoint_id}", json=ENDPOINT_SETTINGS)

    updated = call(client, "GET", f"/endpoints/{endpoint_id}")
    print("\nApplied. Endpoint is now version", updated.get("version"))
    for name in ENDPOINT_SETTINGS:
        print(f"  {name}: {updated.get(name)!r}")


if __name__ == "__main__":
    main()

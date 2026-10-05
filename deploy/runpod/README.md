# RunPod serverless endpoint

The video backend runs Lightricks' LTX-2.5 (22B distilled, INT8) in ComfyUI on a
RunPod serverless endpoint built from the RunPod Hub template
[vavo/LTX2.5-serverless](https://github.com/vavo/LTX2.5-serverless). The MCP
server submits a ComfyUI workflow plus the image to `/run`, then polls
`/status` and saves the returned MP4.

## What costs money

RunPod bills **worker time**, about $0.00034/s on the 48 GB Ampere tier (A40 or
RTX A6000), from container start until the worker scales down. Output length
is irrelevant; a five-second clip costs whatever cold start + render take.

| Billed phase | Before | After `configure_endpoint.py` |
| --- | --- | --- |
| Model download | ~40–50 GB from Hugging Face on every cold start | none: linked from RunPod's model cache (download not billed) |
| Workspace seeding | copies the venv and ComfyUI into `/workspace` every boot | skipped (`PERSIST_WORKSPACE=false`) |
| Prompt enhancer | 10 GB Gemma model downloaded and run | removed; the VM's LLM writes the prompt |
| Wrong CUDA host | CUDA 12.8 hosts fail the GPU check after the bootstrap | only CUDA 13.0 hosts (`allowedCudaVersions`) |
| Idle | — | 2 s idle timeout, 0 minimum workers, 1 maximum |

The render itself is kept small too: 1024x576 (sampled at 512x288 and
latent-upscaled), 121 frames at 24 fps, 8 + 3 distilled steps, no audio decode.
Set `RUNPOD_RESOLUTION=1280x704` on the VM for sharper, slower renders.

Measured cost: see the table in the repository readme.

## Configure the endpoint

The model cache itself (Model = `Lightricks/LTX-2.5` plus a Hugging Face token
with the LTX-2.5 license accepted) is set in the RunPod console under the
endpoint's settings. The REST API cannot set it. Everything else is scripted:

```bash
# RUNPOD_API_KEY and RUNPOD_ENDPOINT_ID in the environment or the repo's .env
uv run python deploy/runpod/configure_endpoint.py          # prints the plan
uv run python deploy/runpod/configure_endpoint.py --apply  # changes RunPod
```

It edits the endpoint's own template in place: start command
[`start-cached.sh`](start-cached.sh) and a lean environment (the Hugging Face
token is carried over, never printed), and pins CUDA 13.0, 0–1 workers and
the 48 GB GPUs. The idle and execution timeouts are left as configured.

`start-cached.sh` links the five model files the workflow uses from
`/runpod-volume/huggingface-cache/hub/models--Lightricks--LTX-2.5/snapshots/<rev>/`
into `/comfyui/models`, then runs the image's normal `/start.sh`. The image's
bootstrap skips any file that already exists, and still downloads anything
missing from the cache, so a cache miss is slower but not broken.

## Spend controls in the MCP backend

- One RunPod job at a time; `create_video` refuses while a job is queued or
  running, or while the endpoint reports any queued/running job.
- `RUNPOD_MAX_JOBS_PER_DAY` (default 10) submissions per 24 hours.
- Each request carries `executionTimeout` (10 min) and `ttl` (30 min), so a job
  stuck in the queue expires instead of starting hours later.
- `cancel_video` cancels a queued or running job.
- A background watcher saves finished videos even if no client polls; RunPod
  deletes results 30 minutes after completion.

## Rollback

The original Hub settings were: start command empty, `PERSIST_WORKSPACE=true`,
`LTX25_PRELOAD_PROMPT_ENHANCER=true`, `COMFY_LOG_LEVEL=DEBUG`,
`AWS_DEFAULT_REGION=us-east-1`, `allowedCudaVersions=["13.0","12.8"]`,
`minCudaVersion=12.8`. Restore them in the console (Manage → Edit endpoint).

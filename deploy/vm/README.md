# Oracle VM: MCP server and agent

The web app can now run on this same VM. Its queue worker uses the agent's
durable `/jobs` API and retrieves finished videos through authenticated agent
downloads. Deployment instructions and web/worker systemd units are in
[web/README.md](web/README.md). `/chat` remains available for existing clients.

The always-on VM (Ubuntu 24.04, ARM64, reachable over Tailscale) runs the MCP
and agent services. The agent calls OpenRouter for planning. Nothing on the VM
needs a GPU; video generation happens on the RunPod endpoint described in
[../runpod/README.md](../runpod/README.md).

| Service | Folder on the VM | Listens on | Role |
| --- | --- | --- | --- |
| `aivideo-mcp` | `~/ai-video-mcp` | 127.0.0.1:8001 | FastMCP server, this repo's `video_mcp` package |
| `aivideo-agent` | `~/mcp-agent` | 127.0.0.1:8100 | `/chat` and `/jobs` APIs: OpenRouter plans MCP calls |

The files in [mcp/](mcp/) and [agent/](agent/) are the VM copies of each
service's `pyproject.toml`, `uv.lock`, launcher and unit file. The VM runs
Python 3.12, so `video_mcp` must stay 3.12-compatible even though this repo's
own `pyproject.toml` targets 3.14.

## Request flow

```text
POST /chat {prompt, image_base64}             (agent, bearer token)
  -> register_image_base64                    (MCP: validate, crop to 16:9, 1280x720 JPEG)
  -> OpenRouter returns create_video(plan)    (MCP: spend checks, then RunPod /run)
  -> agent polls get_video_status every 5 s   (no LLM turns while waiting)
  -> get_video_result                         (data/outputs/<job_id>.mp4 + download URL)
```

The MCP server also polls active jobs itself, so a video finishes and is saved
even if the agent request times out.

## Configuration

`~/ai-video-mcp/.env` (mode 600):

```dotenv
VIDEO_BACKEND=runpod            # demo | comfy | runpod
RUNPOD_API_KEY=...
RUNPOD_ENDPOINT_ID=...
RUNPOD_RESOLUTION=1024x576      # sides divisible by 64; 1280x704 is sharper and slower
RUNPOD_MAX_JOBS_PER_DAY=10
RUNPOD_EXECUTION_TIMEOUT_SECONDS=600
RUNPOD_JOB_TTL_SECONDS=1800
PUBLIC_BASE_URL=http://127.0.0.1:8001
AI_VIDEO_DEMO_FILE=/home/ubuntu/ai-video-mcp/data/demo/prepared-demo.mp4
```

Optional: `RUNPOD_PRICE_PER_SECOND` and `RUNPOD_EXPECTED_SECONDS` feed
`estimate_video_cost`; `RUNPOD_POLL_SECONDS` sets the background poll interval.

For the agent's OpenRouter key, model and VM commands, follow
[openrouter.md](openrouter.md). Keep `AGENT_REQUEST_TIMEOUT_SECONDS=1800` if
the `/chat` endpoint waits through a RunPod cold start.

Switch back to the free prepared demo at any time with `VIDEO_BACKEND=demo`
and `sudo systemctl restart aivideo-mcp`.

## Deploy code changes

From the repository root on the PC:

```bash
deploy/vm/deploy.sh ubuntu@<vm-tailscale-ip> /path/to/ssh-key.key
```

It backs up the VM's current code, copies `video_mcp/` and the agent, and
restarts both services. It never touches the `.env` files.

## Generate a video

On the VM:

```bash
cd ~/mcp-agent
.venv/bin/python check-agent.py \
  --image ~/ai-video-mcp/data/incoming/photo.png \
  --prompt 'Create a 5 second 16:9 video from the uploaded image: the character walks along the path, the camera tracks backward.'
```

The answer includes `video_url`; the file is
`~/ai-video-mcp/data/outputs/<job_id>.mp4`. Copy it to the PC with:

```bash
scp -i /path/to/ssh-key.key ubuntu@<vm-tailscale-ip>:ai-video-mcp/data/outputs/<job_id>.mp4 .
```

Per-job cost and timing records are in `~/ai-video-mcp/data/runpod/<job_id>.json`.

## Health checks

```bash
curl http://127.0.0.1:8001/healthz          # MCP + RunPod queue/workers (free)
cd ~/mcp-agent && .venv/bin/python check-agent.py   # agent + OpenRouter + MCP tools
journalctl -u aivideo-mcp -n 50 --no-pager
```

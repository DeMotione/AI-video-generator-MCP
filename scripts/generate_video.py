"""Make a five-second video from a local image, using the VM and RunPod.

    uv run python scripts/generate_video.py data/incoming/photo.png "PROMPT"
    uv run python scripts/generate_video.py data/incoming/photo.png "PROMPT" --agent
    uv run python scripts/generate_video.py --job JOB_ID

The default calls the VM's MCP tools directly: fastest, and the only paid part
is the RunPod render. --agent sends the request through the Gemma agent
instead (the full LLM path; Gemma takes several minutes on the VM's CPU).
--job downloads a finished job, or reports its status.

Videos are saved to data/outputs/<job_id>.mp4. Reads VM_HOST (user@host) and
VM_SSH_KEY from the environment or the repository's .env.
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MCP_PYTHON = "/home/ubuntu/ai-video-mcp/.venv/bin/python"
AGENT_PYTHON = "/home/ubuntu/mcp-agent/.venv/bin/python"
INCOMING = "ai-video-mcp/data/incoming"
OUTPUTS = "ai-video-mcp/data/outputs"

# Each snippet runs on the VM and prints one JSON object per line.
DIRECT = """
import asyncio, json, sys
from fastmcp import Client
from fastmcp.exceptions import ToolError

def emit(**fields):
    print(json.dumps(fields), flush=True)

async def main(filename, prompt):
    async with Client("http://127.0.0.1:8001/mcp", timeout=180) as client:
        async def tool(name, **arguments):
            return (await client.call_tool(name, arguments)).structured_content
        asset = await tool("register_image", filename=filename)
        plan = {"asset_id": asset["asset_id"], "prompt": prompt}
        estimate = await tool("estimate_video_cost", plan=plan)
        emit(event="estimate", usd=estimate["estimated_cost"], basis=estimate["basis"])
        job = await tool("create_video", plan=plan)
        emit(event="submitted", job_id=job["job_id"], status=job["status"],
             message=job["message"])
        while job["status"] in ("queued", "running"):
            await asyncio.sleep(10)
            job = await tool("get_video_status", job_id=job["job_id"])
            emit(event="status", status=job["status"], message=job["message"])
        emit(event="done", job_id=job["job_id"], status=job["status"],
             message=job["message"])

try:
    asyncio.run(main(sys.argv[1], sys.argv[2]))
except ToolError as exc:
    emit(event="error", message=str(exc))
"""

AGENT = """
import base64, json, sys
import httpx
from dotenv import dotenv_values

settings = dotenv_values("/home/ubuntu/mcp-agent/.env")
image = base64.b64encode(open(sys.argv[1], "rb").read()).decode()
print(json.dumps({"event": "status", "status": "asking the agent",
                  "message": "Gemma is planning; this takes several minutes."}),
      flush=True)
response = httpx.post(
    "http://127.0.0.1:8100/chat",
    json={"prompt": sys.argv[2], "image_base64": image},
    headers={"Authorization": "Bearer " + settings["AGENT_API_TOKEN"]},
    timeout=float(settings.get("AGENT_REQUEST_TIMEOUT_SECONDS") or 1800) + 60,
)
data = response.json()
job_id = next(
    (item["data"].get("job_id") for item in data.get("tool_results", [])
     if item["tool_name"] == "create_video" and not item["is_error"]
     and isinstance(item["data"], dict)),
    None,
)
print(json.dumps({"event": "agent", "http": response.status_code,
                  "status": data.get("status"), "job_id": job_id,
                  "message": data.get("answer") or data.get("detail")}),
      flush=True)
"""

STATUS = """
import asyncio, json, sys
from fastmcp import Client
from fastmcp.exceptions import ToolError

async def main(job_id):
    async with Client("http://127.0.0.1:8001/mcp", timeout=180) as client:
        job = (await client.call_tool("get_video_status", {"job_id": job_id}))
        job = job.structured_content
        print(json.dumps({"event": "done", "job_id": job["job_id"],
                          "status": job["status"], "message": job["message"]}))

try:
    asyncio.run(main(sys.argv[1]))
except ToolError as exc:
    print(json.dumps({"event": "error", "message": str(exc)}))
"""


def load_settings() -> dict:
    values = {}
    env_file = ROOT / ".env"
    if env_file.is_file():
        for line in env_file.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and not line.lstrip().startswith("#"):
                values[key.strip()] = value.strip().strip('"')
    values.update({k: v for k, v in os.environ.items() if k.startswith("VM_")})
    return values


class Vm:
    def __init__(self, host: str, key: str):
        self.host = host
        self.options = ["-i", key, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20"]

    def upload(self, local: Path, remote: str):
        subprocess.run(
            ["scp", "-q", *self.options, str(local), f"{self.host}:{remote}"],
            check=True,
        )

    def download(self, remote: str, local: Path):
        subprocess.run(
            ["scp", "-q", *self.options, f"{self.host}:{remote}", str(local)],
            check=True,
        )

    def run(self, python: str, snippet: str, *arguments: str):
        """Run a Python snippet on the VM, yielding each JSON line it prints."""
        command = " ".join(shlex.quote(part) for part in (python, "-", *arguments))
        process = subprocess.Popen(
            ["ssh", *self.options, self.host, command],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        process.stdin.write(snippet)
        process.stdin.close()
        for line in process.stdout:
            line = line.strip()
            if line.startswith("{"):
                yield json.loads(line)
        if process.wait():
            sys.exit(f"The remote step failed (exit code {process.returncode}).")


def fetch(vm: Vm, event: dict) -> int:
    print(f"[{event['status']}] {event['message']}")
    if event["status"] != "completed":
        return 1
    output = ROOT / "data" / "outputs" / f"{event['job_id']}.mp4"
    output.parent.mkdir(parents=True, exist_ok=True)
    vm.download(f"{OUTPUTS}/{event['job_id']}.mp4", output)
    print(f"Saved {output}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image", nargs="?", type=Path, help="JPEG, PNG or WebP, ~16:9")
    parser.add_argument("prompt", nargs="?", help="what should happen in the video")
    parser.add_argument("--agent", action="store_true", help="go through Gemma")
    parser.add_argument("--job", help="download or check an existing job")
    arguments = parser.parse_args()

    settings = load_settings()
    if not settings.get("VM_HOST") or not settings.get("VM_SSH_KEY"):
        parser.error("set VM_HOST and VM_SSH_KEY in the environment or .env")
    vm = Vm(settings["VM_HOST"], settings["VM_SSH_KEY"])

    if arguments.job:
        for event in vm.run(MCP_PYTHON, STATUS, arguments.job):
            if event["event"] == "error":
                sys.exit(event["message"])
            return fetch(vm, event)
        return 1

    if not arguments.image or not arguments.prompt:
        parser.error("give an image and a prompt, or --job JOB_ID")
    if not arguments.image.is_file():
        parser.error(f"{arguments.image} does not exist")

    filename = arguments.image.name
    print(f"Uploading {arguments.image} to the VM...")
    vm.upload(arguments.image, f"{INCOMING}/{filename}")

    if arguments.agent:
        remote = f"/home/ubuntu/{INCOMING}/{filename}"
        snippet, python, script_args = AGENT, AGENT_PYTHON, (remote, arguments.prompt)
    else:
        snippet, python, script_args = DIRECT, MCP_PYTHON, (filename, arguments.prompt)

    job_id = None
    for event in vm.run(python, snippet, *script_args):
        kind = event["event"]
        if kind == "estimate":
            print(f"Estimated RunPod cost: ${event['usd']:.3f} ({event['basis']})")
        elif kind == "submitted":
            job_id = event["job_id"]
            print(f"Submitted job {job_id}: {event['message']}")
        elif kind == "status":
            print(f"  {event['status']}: {event['message']}")
        elif kind == "error":
            sys.exit(f"Stopped: {event['message']}")
        elif kind == "agent":
            print(f"Agent ({event['status']}): {event['message']}")
            job_id = event["job_id"]
        elif kind == "done":
            return fetch(vm, event)

    if job_id:
        # The agent returned; fetch the job's final state from the MCP server.
        for event in vm.run(MCP_PYTHON, STATUS, job_id):
            return fetch(vm, event) if event["event"] == "done" else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())

import asyncio
from contextlib import contextmanager
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from pydantic import ValidationError
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse

from video_mcp.models import (
    GenerationPlan,
    ImageAsset,
    VideoEstimate,
    VideoJob,
    VideoResult,
)
from video_mcp.video import ComfyBackend, VideoServiceError


mcp = FastMCP("AI Video Generator")
backend = ComfyBackend()


@contextmanager
def tool_errors():
    try:
        yield
    except ValidationError as exc:
        message = "; ".join(
            f"{'.'.join(map(str, item['loc']))}: {item['msg']}"
            for item in exc.errors()
        )
        raise ToolError(message) from exc
    except (VideoServiceError, OSError, ValueError, KeyError) as exc:
        raise ToolError(str(exc)) from exc


@mcp.tool(annotations={"readOnlyHint": True})
def list_video_models() -> list[dict]:
    """List supported generation models and the single available preset."""
    return [{
        "model": "ltx-2-5-fast",
        "duration": 5,
        "aspect_ratio": "16:9",
        "resolution": "1280x720",
        "audio": "silent",
        "generated_seconds": 6,
        "estimated_usd": 0.54,
    }]


@mcp.tool
def register_image(filename: str) -> ImageAsset:
    """Register a static JPEG, PNG or WebP from the PC's data/incoming folder.

    Requires 16:9, at least 320x180, dimensions up to 4096px, and at most
    10 MiB. Returns the asset_id needed in a generation plan.
    """
    with tool_errors():
        return backend.register_image(filename)


@mcp.tool(annotations={"readOnlyHint": True})
def estimate_video_cost(plan: GenerationPlan) -> VideoEstimate:
    """Validate an asset and plan, then estimate cost without generation."""
    with tool_errors():
        return backend.estimate(plan)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": False})
def create_video(plan: GenerationPlan) -> VideoJob:
    """Submit one paid image-to-video job.

    Returns a job immediately. Poll queued/running jobs every five seconds.
    For unknown status, inspect ComfyUI before submitting another job.
    """
    with tool_errors():
        return backend.create(plan)


@mcp.tool(annotations={"readOnlyHint": True})
def get_video_status(job_id: UUID) -> VideoJob:
    """Check queued, running, completed, failed or unknown job status."""
    with tool_errors():
        return backend.status(job_id)


@mcp.tool(annotations={"readOnlyHint": True})
def get_video_result(job_id: UUID) -> VideoResult:
    """Return the completed video's PC path and configured download URL."""
    with tool_errors():
        return backend.result(job_id)


@mcp.custom_route("/videos/{job_id}.mp4", methods=["GET"])
async def download_video(request: Request):
    try:
        result = await asyncio.to_thread(
            backend.result, UUID(request.path_params["job_id"])
        )
    except (VideoServiceError, ValueError, OSError):
        return JSONResponse({"error": "Video unavailable"}, status_code=404)

    return FileResponse(
        result.video_path,
        media_type="video/mp4",
        filename=f"{result.job_id}.mp4",
    )


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)
import asyncio
import base64
import binascii
import os
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
from video_mcp.runpod import RunPodBackend
from video_mcp.video import (
    MAX_IMAGE_BYTES,
    ComfyBackend,
    DemoBackend,
    VideoServiceError,
)


mcp = FastMCP("AI Video Generator")

BACKENDS = {"demo": DemoBackend, "comfy": ComfyBackend, "runpod": RunPodBackend}
backend = BACKENDS[os.getenv("VIDEO_BACKEND", "comfy")]()
if isinstance(backend, RunPodBackend):
    backend.start_watcher()


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
    return [backend.describe()]


@mcp.tool
def register_image(filename: str) -> ImageAsset:
    """Register a static JPEG, PNG or WebP from the server's data/incoming folder.

    Requires 16:9 (within 2%; the surplus is center-cropped), at least
    320x180, dimensions up to 4096px, and at most 10 MiB. Returns the
    asset_id needed in a generation plan.
    """
    with tool_errors():
        return backend.register_image(filename)


@mcp.tool
def register_image_base64(image_base64: str) -> ImageAsset:
    """Register uploaded JPEG, PNG or WebP bytes encoded as raw base64.

    Use this when the image is not already on the server's disk, such as
    from a remote agent. Same rules as register_image: static 16:9, at
    least 320x180, up to 4096px, and at most 10 MiB once decoded.
    """
    with tool_errors():
        if len(image_base64) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
            raise VideoServiceError("Encoded image exceeds the 10 MiB limit.")
        try:
            content = base64.b64decode(image_base64, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise VideoServiceError("Image is not valid base64.") from exc
        return backend.register_image_bytes(content)


@mcp.tool(annotations={"readOnlyHint": True})
def estimate_video_cost(plan: GenerationPlan) -> VideoEstimate:
    """Validate an asset and plan, then estimate cost without generation."""
    with tool_errors():
        return backend.estimate(plan)


@mcp.tool(annotations={"readOnlyHint": False, "idempotentHint": False})
def create_video(plan: GenerationPlan) -> VideoJob:
    """Submit one paid image-to-video job.

    Returns a job immediately. Poll queued/running jobs every five seconds.
    For unknown status, inspect the provider's queue before submitting
    another job.
    """
    with tool_errors():
        return backend.create(plan)


@mcp.tool(annotations={"readOnlyHint": True})
def get_video_status(job_id: UUID) -> VideoJob:
    """Check queued, running, completed, failed, cancelled or unknown status."""
    with tool_errors():
        return backend.status(job_id)


@mcp.tool(annotations={"readOnlyHint": True})
def get_video_result(job_id: UUID) -> VideoResult:
    """Return the completed video's server path and configured download URL."""
    with tool_errors():
        return backend.result(job_id)


@mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
def cancel_video(job_id: UUID) -> VideoJob:
    """Cancel a queued or running job so it stops using paid GPU time.

    Worker time already used is still billed.
    """
    with tool_errors():
        return backend.cancel(job_id)


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


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_request: Request):
    detail = {}
    try:
        if isinstance(backend, DemoBackend):
            backend._validate_demo_file()
        elif isinstance(backend, RunPodBackend):
            # RunPod's health route is free and does not start a worker.
            detail = {"runpod": await asyncio.to_thread(backend.health)}
    except VideoServiceError as exc:
        return JSONResponse(
            {"status": "not_ready", "detail": str(exc)}, status_code=503
        )

    return JSONResponse(
        {"status": "ready", "backend": backend.describe()["backend"]} | detail
    )


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8001)
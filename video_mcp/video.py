import hashlib
import io
import os
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from PIL import Image, ImageOps

from video_mcp.models import (
    GenerationPlan,
    ImageAsset,
    JobStatus,
    VideoEstimate,
    VideoJob,
    VideoResult,
)


PRESET = "ltx25-fast-5s-16x9-v1"
MAX_IMAGE_BYTES = 10 * 1024 * 1024


class VideoServiceError(Exception):
    pass


class ComfyBackend:
    def __init__(self, root: Path | None = None):
        self.root = root or Path(__file__).resolve().parents[1] / "data"
        self.comfy_url = os.getenv(
            "COMFY_URL", "http://127.0.0.1:8188"
        ).rstrip("/")
        self.public_url = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

        for folder in ("incoming", "assets", "jobs", "outputs"):
            (self.root / folder).mkdir(parents=True, exist_ok=True)

    def _write(self, path: Path, content: bytes):
        temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
        temporary.write_bytes(content)
        temporary.replace(path)

    def _save(self, folder, identifier, model):
        self._write(
            self.root / folder / f"{identifier}.json",
            model.model_dump_json(indent=2).encode(),
        )

    def _load(self, folder, identifier, model):
        identifier = UUID(str(identifier))
        path = self.root / folder / f"{identifier}.json"
        if not path.is_file():
            raise VideoServiceError(f"Unknown {folder} ID: {identifier}")
        return model.model_validate_json(path.read_text())

    def _request(self, method, path, **kwargs):
        try:
            response = httpx.request(
                method,
                f"{self.comfy_url}{path}",
                timeout=30,
                **kwargs,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as exc:
            raise VideoServiceError(
                f"ComfyUI returned HTTP {exc.response.status_code}."
            ) from exc
        except httpx.RequestError as exc:
            raise VideoServiceError(
                "Cannot reach ComfyUI. Check COMFY_URL and the desktop app."
            ) from exc

    def register_image(self, filename: str) -> ImageAsset:
        incoming = (self.root / "incoming").resolve()
        path = (incoming / filename).resolve()

        if (
            not filename
            or "/" in filename
            or "\\" in filename
            or not path.is_relative_to(incoming)
            or not path.is_file()
        ):
            raise VideoServiceError(
                "Use a filename from data/incoming, such as photo.jpg."
            )

        with path.open("rb") as source:
            raw = source.read(MAX_IMAGE_BYTES + 1)

        if len(raw) > MAX_IMAGE_BYTES:
            raise VideoServiceError("Image exceeds 10 MiB.")

        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValueError("Use JPEG, PNG or WebP.")
                if getattr(source, "n_frames", 1) != 1:
                    raise ValueError("Animated images are unsupported.")
                if max(source.size) > 4096:
                    raise ValueError("Maximum image dimension is 4096 pixels.")

                frame = ImageOps.exif_transpose(source)
                width, height = frame.size

                if width < 320 or height < 180:
                    raise ValueError("Minimum image size is 320×180.")
                if width * 9 != height * 16:
                    raise ValueError("This preset requires a 16:9 image.")

                rgba = frame.convert("RGBA")
                rgb = Image.new("RGB", rgba.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))

                normalized = io.BytesIO()
                rgb.resize(
                    (1280, 720), Image.Resampling.LANCZOS
                ).save(normalized, format="JPEG", quality=90)
        except (OSError, ValueError, Image.DecompressionBombError) as exc:
            raise VideoServiceError(f"Invalid image: {exc}") from exc

        content = normalized.getvalue()
        asset = ImageAsset(
            asset_id=uuid4(),
            size_bytes=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        self._write(
            self.root / "assets" / f"{asset.asset_id}.jpg", content
        )
        self._save("assets", asset.asset_id, asset)
        return asset

    def validate_plan(self, plan):
        if isinstance(plan, GenerationPlan):
            plan = plan.model_dump()
        plan = GenerationPlan.model_validate(plan)

        asset = self._load("assets", plan.asset_id, ImageAsset)
        content = (
            self.root / "assets" / f"{asset.asset_id}.jpg"
        ).read_bytes()

        if (
            len(content) != asset.size_bytes
            or hashlib.sha256(content).hexdigest() != asset.sha256
        ):
            raise VideoServiceError("Image changed. Register it again.")

        return plan, asset, content

    def estimate(self, plan: GenerationPlan) -> VideoEstimate:
        self.validate_plan(plan)
        return VideoEstimate()

    def create(self, plan: GenerationPlan) -> VideoJob:
        plan, asset, content = self.validate_plan(plan)

        health = self._request("GET", "/avg/health").json()
        if not health.get("ready") or health.get("preset") != PRESET:
            raise VideoServiceError(
                f"ComfyUI node is not ready: {health.get('missing', [])}"
            )

        uploaded = self._request(
            "POST",
            "/upload/image",
            files={
                "image": (
                    f"{asset.asset_id}.jpg",
                    content,
                    "image/jpeg",
                )
            },
            data={"overwrite": "false"},
        ).json()

        image_name = "/".join(
            part for part in (
                uploaded.get("subfolder", ""),
                uploaded["name"],
            ) if part
        )

        job = VideoJob(
            job_id=uuid4(),
            plan=plan,
            status=JobStatus.UNKNOWN,
            message="Submission outcome is not yet recorded.",
        )
        self._save("jobs", job.job_id, job)

        workflow = {
            "1": {
                "class_type": "LoadImage",
                "inputs": {"image": image_name},
            },
            "2": {
                "class_type": "AVG_LTX25",
                "inputs": {
                    "image": ["1", 0],
                    "prompt": plan.prompt,
                    "request_id": str(job.job_id),
                },
            },
        }

        try:
            submitted = self._request(
                "POST",
                "/prompt",
                json={
                    "prompt": workflow,
                    "client_id": str(job.job_id),
                },
            ).json()
            if submitted.get("node_errors"):
                raise VideoServiceError("ComfyUI rejected the workflow.")

            job = job.model_copy(update={
                "comfy_id": submitted["prompt_id"],
                "status": JobStatus.QUEUED,
                "progress": 0,
                "message": "Queued in ComfyUI.",
            })
        except (VideoServiceError, ValueError, KeyError):
            job = job.model_copy(update={
                "message": (
                    "Submission outcome is unknown. Inspect the ComfyUI "
                    "queue/history before creating another job."
                )
            })

        self._save("jobs", job.job_id, job)
        return job

    def status(self, job_id: UUID) -> VideoJob:
        job = self._load("jobs", job_id, VideoJob)
        if job.status in {
            JobStatus.COMPLETED,
            JobStatus.FAILED,
            JobStatus.UNKNOWN,
        }:
            return job

        queue = self._request("GET", "/queue").json()
        history = self._request(
            "GET", f"/history/{job.comfy_id}"
        ).json().get(job.comfy_id)

        if history:
            state = history.get("status", {})

            if state.get("status_str") == "error":
                job = job.model_copy(update={
                    "status": JobStatus.FAILED,
                    "progress": None,
                    "message": (
                        "Workflow failed. Generation may already be billed; "
                        "inspect ComfyUI before retrying."
                    ),
                })
            elif state.get("completed"):
                outputs = history.get("outputs", {}).get("2", {})
                videos = outputs.get("avg_video", [])
                expected = f"{job.job_id}.mp4"

                if (
                    len(videos) != 1
                    or videos[0].get("filename") != expected
                    or videos[0].get("subfolder") != "avg"
                ):
                    raise VideoServiceError(
                        "Completed workflow has no expected video output."
                    )

                response = self._request(
                    "GET",
                    "/view",
                    params={
                        "filename": expected,
                        "subfolder": "avg",
                        "type": "output",
                    },
                )
                self._write(
                    self.root / "outputs" / expected, response.content
                )
                job = job.model_copy(update={
                    "status": JobStatus.COMPLETED,
                    "progress": 100,
                    "message": "Five-second video is ready.",
                })
        elif any(
            entry[1] == job.comfy_id
            for entry in queue.get("queue_running", [])
        ):
            job = job.model_copy(update={
                "status": JobStatus.RUNNING,
                "progress": None,
                "message": "Generating or finishing the video.",
            })
        elif any(
            entry[1] == job.comfy_id
            for entry in queue.get("queue_pending", [])
        ):
            job = job.model_copy(update={
                "status": JobStatus.QUEUED,
                "progress": 0,
                "message": "Waiting in the ComfyUI queue.",
            })
        else:
            job = job.model_copy(update={
                "status": JobStatus.UNKNOWN,
                "progress": None,
                "message": (
                    "Job is missing from ComfyUI queue/history. "
                    "Inspect ComfyUI before resubmitting."
                ),
            })

        self._save("jobs", job.job_id, job)
        return job

    def result(self, job_id: UUID) -> VideoResult:
        job = self.status(job_id)
        if job.status != JobStatus.COMPLETED:
            raise VideoServiceError(f"Job is {job.status.value}.")

        path = self.root / "outputs" / f"{job.job_id}.mp4"
        if not path.is_file():
            raise VideoServiceError("The saved video is missing.")

        return VideoResult(
            job_id=job.job_id,
            video_path=str(path.resolve()),
            video_url=(
                f"{self.public_url}/videos/{job.job_id}.mp4"
                if self.public_url else None
            ),
        )
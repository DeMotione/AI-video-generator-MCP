import hashlib
import io
from pathlib import Path
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from video_mcp.models import GenerationPlan, JobStatus
from video_mcp.video import ComfyBackend, VideoServiceError


def test_image_registration_normalizes_and_persists_asset(backend, asset, comfy):
    path = backend.root / "assets" / f"{asset.asset_id}.jpg"
    content = path.read_bytes()

    with Image.open(io.BytesIO(content)) as image:
        assert image.format == "JPEG"
        assert image.size == (1280, 720)

    assert asset.size_bytes == len(content)
    assert asset.sha256 == hashlib.sha256(content).hexdigest()
    assert (backend.root / "assets" / f"{asset.asset_id}.json").is_file()
    assert comfy.calls == []


@pytest.mark.parametrize("filename", [
    "../outside.png",
    "..\\outside.png",
    "missing.png",
    "",
])
def test_invalid_image_paths_are_rejected(backend, comfy, filename):
    with pytest.raises(VideoServiceError):
        backend.register_image(filename)

    assert comfy.calls == []


def test_corrupt_image_is_rejected(backend, comfy):
    (backend.root / "incoming" / "broken.png").write_bytes(b"not an image")

    with pytest.raises(VideoServiceError, match="Invalid image"):
        backend.register_image("broken.png")

    assert comfy.calls == []


@pytest.mark.parametrize("size", [(360, 640), (640, 640), (160, 90)])
def test_unsupported_image_dimensions_are_rejected(backend, comfy, size):
    Image.new("RGB", size).save(backend.root / "incoming" / "invalid.png")

    with pytest.raises(VideoServiceError):
        backend.register_image("invalid.png")

    assert comfy.calls == []


def test_oversized_image_is_rejected_before_decoding(backend, comfy):
    path = backend.root / "incoming" / "large.png"
    with path.open("wb") as stream:
        stream.truncate(10 * 1024 * 1024 + 1)

    with pytest.raises(VideoServiceError, match="10 MiB"):
        backend.register_image("large.png")

    assert comfy.calls == []


@pytest.mark.parametrize("changes", [
    {"duration": 6},
    {"duration": "5"},
    {"duration": 5.0},
    {"aspect_ratio": "9:16"},
    {"model": "unsupported"},
    {"audio": "enabled"},
    {"prompt": "   "},
    {"unexpected": True},
])
def test_invalid_plan_never_dispatches(backend, comfy, plan, changes):
    with pytest.raises(ValidationError):
        backend.create(plan.model_dump() | changes)

    assert comfy.calls == []
    assert list((backend.root / "jobs").glob("*.json")) == []


def test_unknown_asset_never_dispatches(backend, comfy):
    plan = GenerationPlan(asset_id=uuid4(), prompt="Slow zoom.")

    with pytest.raises(VideoServiceError, match="Unknown assets ID"):
        backend.create(plan)

    assert comfy.calls == []


def test_tampered_asset_never_dispatches(backend, comfy, plan):
    path = backend.root / "assets" / f"{plan.asset_id}.jpg"
    path.write_bytes(b"changed")

    with pytest.raises(VideoServiceError, match="changed"):
        backend.create(plan)

    assert comfy.calls == []


def test_estimation_does_not_dispatch(backend, comfy, plan):
    estimate = backend.estimate(plan)

    assert estimate.estimated_cost == pytest.approx(0.54)
    assert estimate.generated_seconds == 6
    assert estimate.delivered_seconds == 5
    assert comfy.calls == []


def test_unready_node_prevents_upload_and_submission(backend, comfy, plan):
    comfy.health.update(ready=False, missing=["ffmpeg"])

    with pytest.raises(VideoServiceError, match="not ready"):
        backend.create(plan)

    assert [(method, path) for method, path, _ in comfy.calls] == [
        ("GET", "/avg/health")
    ]
    assert comfy.jobs == {}


def test_create_submits_image_and_workflow(backend, comfy, plan):
    job = backend.create(plan)
    payload = comfy.jobs[job.comfy_id]["payload"]
    graph = payload["prompt"]

    assert job.status is JobStatus.QUEUED
    assert job.progress == 0
    assert job.plan == plan
    assert graph["1"]["class_type"] == "LoadImage"
    assert graph["1"]["inputs"]["image"] == f"avg-input/{plan.asset_id}.jpg"
    assert graph["2"]["class_type"] == "AVG_LTX25"
    assert graph["2"]["inputs"] == {
        "image": ["1", 0],
        "prompt": plan.prompt,
        "request_id": str(job.job_id),
    }
    assert payload["client_id"] == str(job.job_id)
    assert comfy.uploads[f"{plan.asset_id}.jpg"]["mime_type"] == "image/jpeg"


def test_full_job_lifecycle(backend, comfy, plan):
    job = backend.create(plan)

    assert backend.status(job.job_id).status is JobStatus.QUEUED

    comfy.jobs[job.comfy_id]["state"] = "running"
    running = backend.status(job.job_id)

    assert running.status is JobStatus.RUNNING
    assert running.progress is None

    comfy.jobs[job.comfy_id]["state"] = "completed"
    completed = backend.status(job.job_id)

    assert completed.status is JobStatus.COMPLETED
    assert completed.progress == 100

    result = backend.result(job.job_id)

    assert result.status == "completed"
    assert result.duration == 5
    assert result.aspect_ratio == "16:9"
    assert Path(result.video_path).read_bytes() == comfy.video_bytes
    assert result.video_url == f"https://video.test/videos/{job.job_id}.mp4"


def test_result_is_unavailable_before_completion(backend, comfy, plan):
    job = backend.create(plan)

    with pytest.raises(VideoServiceError, match="queued"):
        backend.result(job.job_id)

    comfy.jobs[job.comfy_id]["state"] = "running"

    with pytest.raises(VideoServiceError, match="running"):
        backend.result(job.job_id)


@pytest.mark.parametrize("operation", ["status", "result"])
def test_unknown_job_is_rejected(backend, comfy, operation):
    with pytest.raises(VideoServiceError, match="Unknown jobs ID"):
        getattr(backend, operation)(uuid4())

    assert comfy.calls == []


def test_failed_workflow_has_no_result(backend, comfy, plan):
    job = backend.create(plan)
    comfy.jobs[job.comfy_id]["state"] = "failed"

    assert backend.status(job.job_id).status is JobStatus.FAILED

    with pytest.raises(VideoServiceError, match="failed"):
        backend.result(job.job_id)

    assert not (backend.root / "outputs" / f"{job.job_id}.mp4").exists()


def test_missing_workflow_becomes_unknown(backend, comfy, plan):
    job = backend.create(plan)
    del comfy.jobs[job.comfy_id]

    status = backend.status(job.job_id)

    assert status.status is JobStatus.UNKNOWN
    assert status.progress is None


def test_lost_submission_response_does_not_resubmit(backend, comfy, plan):
    comfy.accept_then_timeout = True
    job = backend.create(plan)

    assert job.status is JobStatus.UNKNOWN
    assert job.comfy_id is None
    assert len(comfy.jobs) == 1

    call_count = len(comfy.calls)

    assert backend.status(job.job_id).status is JobStatus.UNKNOWN

    with pytest.raises(VideoServiceError, match="unknown"):
        backend.result(job.job_id)

    assert len(comfy.calls) == call_count
    assert len(comfy.jobs) == 1


def test_completed_workflow_requires_expected_output(backend, comfy, plan):
    job = backend.create(plan)
    comfy.jobs[job.comfy_id]["history"] = {
        "status": {"completed": True, "status_str": "success"},
        "outputs": {
            "2": {
                "avg_video": [{
                    "filename": "unexpected.mp4",
                    "subfolder": "avg",
                    "type": "output",
                }]
            }
        },
    }

    with pytest.raises(VideoServiceError, match="expected video output"):
        backend.status(job.job_id)

    assert not any(path == "/view" for _, path, _ in comfy.calls)


def test_jobs_survive_backend_restart(backend, comfy, plan):
    job = backend.create(plan)
    restarted = ComfyBackend(root=backend.root)

    assert restarted.status(job.job_id).plan == plan

    comfy.jobs[job.comfy_id]["state"] = "completed"
    result = restarted.result(job.job_id)
    call_count = len(comfy.calls)

    restarted_again = ComfyBackend(root=backend.root)

    assert restarted_again.result(job.job_id) == result
    assert len(comfy.calls) == call_count


def test_jobs_remain_independent(backend, comfy, plan):
    first = backend.create(plan)
    second = backend.create(plan)

    assert first.job_id != second.job_id
    assert first.comfy_id != second.comfy_id

    comfy.jobs[first.comfy_id]["state"] = "completed"
    comfy.jobs[second.comfy_id]["state"] = "running"

    assert backend.status(first.job_id).status is JobStatus.COMPLETED
    assert backend.status(second.job_id).status is JobStatus.RUNNING
import asyncio
import base64
import io
import json
import struct
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from PIL import Image
from pydantic import TypeAdapter

import video_mcp.video as video_module
from video_mcp.models import GenerationPlan, JobStatus, VideoJob
from video_mcp.runpod import WORKFLOW, RunPodBackend, parse_resolution, probe_mp4
from video_mcp.video import VideoServiceError

ENDPOINT = "endpoint123"


def box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I4s", 8 + len(payload), kind) + payload


def fake_mp4(width=1024, height=576, milliseconds=5042) -> bytes:
    mvhd = box(b"mvhd", bytes(12) + struct.pack(">II", 1000, milliseconds) + bytes(80))
    tkhd = box(b"tkhd", bytes(76) + struct.pack(">II", width << 16, height << 16))
    moov = box(b"moov", mvhd + box(b"trak", tkhd))
    ftyp = box(b"ftyp", b"isom\x00\x00\x02\x00isomiso2")
    return ftyp + box(b"mdat", bytes(32)) + moov


class RunPodStub:
    def __init__(self):
        self.calls = []
        self.runs = []
        self.jobs = {}
        self.queue = {"inQueue": 0, "inProgress": 0}
        self.run_status = 200
        self.run_error = None

    def request(self, method, url, **kwargs):
        request = httpx.Request(method, url)
        path = request.url.path
        self.calls.append((method, path))
        assert kwargs["headers"]["Authorization"] == "Bearer test-key"
        assert path.startswith(f"/v2/{ENDPOINT}/")
        route = path.removeprefix(f"/v2/{ENDPOINT}/")

        def respond(payload, status=200):
            return httpx.Response(status, json=payload, request=request)

        if method == "GET" and route == "health":
            return respond({"jobs": self.queue, "workers": {"idle": 1}})

        if method == "POST" and route == "run":
            if self.run_error:
                raise self.run_error
            if self.run_status != 200:
                return respond({"error": "rejected"}, self.run_status)
            identifier = f"rp-{len(self.runs) + 1}"
            self.runs.append(kwargs["json"])
            self.jobs[identifier] = {"id": identifier, "status": "IN_QUEUE"}
            return respond({"id": identifier, "status": "IN_QUEUE"})

        if method == "GET" and route.startswith("status/"):
            job = self.jobs.get(route.removeprefix("status/"))
            return respond(job) if job else respond({"error": "not found"}, 404)

        if method == "POST" and route.startswith("cancel/"):
            job = self.jobs[route.removeprefix("cancel/")]
            if job["status"] in {"IN_QUEUE", "IN_PROGRESS"}:
                job["status"] = "CANCELLED"
            return respond({"id": job["id"], "status": job["status"]})

        raise AssertionError(f"Unexpected request: {method} {url}")

    def complete(self, identifier, video=None, **extra):
        encoded = base64.b64encode(video or fake_mp4()).decode()
        self.jobs[identifier] = {
            "id": identifier,
            "status": "COMPLETED",
            "delayTime": 61000,
            "executionTime": 95000,
            "output": {
                "status": "success",
                "output": {
                    "images": [{
                        "filename": "avg/clip_00001_.mp4",
                        "type": "base64",
                        "data": encoded,
                        "media_type": "video/mp4",
                    }]
                },
            },
        } | extra


@pytest.fixture
def runpod(monkeypatch):
    stub = RunPodStub()
    monkeypatch.setattr(httpx, "request", stub.request)
    return stub


@pytest.fixture
def backend(tmp_path, monkeypatch, runpod):
    monkeypatch.setenv("RUNPOD_API_KEY", "test-key")
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", ENDPOINT)
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://video.test")
    for name in (
        "RUNPOD_RESOLUTION",
        "RUNPOD_MAX_JOBS_PER_DAY",
        "RUNPOD_PRICE_PER_SECOND",
        "RUNPOD_EXPECTED_SECONDS",
        "RUNPOD_EXECUTION_TIMEOUT_SECONDS",
        "RUNPOD_JOB_TTL_SECONDS",
    ):
        monkeypatch.delenv(name, raising=False)
    return RunPodBackend(root=tmp_path / "data")


@pytest.fixture
def plan(backend):
    Image.new("RGB", (1672, 941), "green").save(backend.root / "incoming" / "photo.png")
    asset = backend.register_image("photo.png")
    return GenerationPlan(
        asset_id=asset.asset_id, prompt="The apple walks along the path."
    )


def test_near_16x9_photo_is_center_cropped_and_normalized(backend, plan):
    content = (backend.root / "assets" / f"{plan.asset_id}.jpg").read_bytes()

    with Image.open(io.BytesIO(content)) as image:
        assert image.size == (1280, 720)


def test_aspect_ratio_far_from_16x9_is_still_rejected(backend):
    Image.new("RGB", (1600, 1200)).save(backend.root / "incoming" / "four-three.png")

    with pytest.raises(VideoServiceError, match="16:9"):
        backend.register_image("four-three.png")


def test_estimate_is_local_and_reports_five_generated_seconds(backend, runpod, plan):
    estimate = backend.estimate(plan)

    assert estimate.generated_seconds == 5
    assert estimate.estimated_cost == pytest.approx(150 * 0.00034, abs=0.001)
    assert runpod.calls == []


def test_create_submits_trimmed_workflow_once(backend, runpod, plan):
    job = backend.create(plan)
    payload = runpod.runs[0]
    workflow = payload["input"]["workflow"]
    image = payload["input"]["images"][0]

    assert job.status is JobStatus.QUEUED
    assert job.provider_job_id == "rp-1"
    assert len(runpod.runs) == 1
    assert workflow["398:376"]["inputs"]["value"] == plan.prompt
    assert workflow["395"]["inputs"]["image"] == image["name"] == f"{plan.asset_id}.jpg"
    assert workflow["398:372"]["inputs"]["value"] == 1024
    assert workflow["398:360"]["inputs"]["value"] == 576
    assert workflow["398:362"]["inputs"]["value"] == 5
    assert workflow["398:361"]["inputs"]["value"] == 24
    assert workflow["398:351"]["inputs"]["resize_type.longer_size"] == 1024
    assert workflow["75"]["inputs"]["filename_prefix"] == f"avg/{job.job_id}"
    assert "audio" not in workflow["398:370"]["inputs"]
    assert not {"398:380", "398:393"} & workflow.keys()
    assert payload["policy"] == {"executionTimeout": 600_000, "ttl": 1_800_000}

    asset = (backend.root / "assets" / f"{plan.asset_id}.jpg").read_bytes()
    encoded = base64.b64encode(asset).decode()
    assert image["image"] == "data:image/jpeg;base64," + encoded


def test_shared_template_is_not_mutated(backend, runpod, plan):
    before = json.dumps(WORKFLOW, sort_keys=True)
    backend.create(plan)

    assert json.dumps(WORKFLOW, sort_keys=True) == before


def test_every_workflow_link_resolves():
    for node in WORKFLOW.values():
        for value in node["inputs"].values():
            if isinstance(value, list) and isinstance(value[0], str):
                assert value[0] in WORKFLOW


def test_full_lifecycle_saves_validated_video(backend, runpod, plan):
    job = backend.create(plan)

    assert backend.status(job.job_id).status is JobStatus.QUEUED

    runpod.jobs["rp-1"]["status"] = "IN_PROGRESS"
    assert backend.status(job.job_id).status is JobStatus.RUNNING

    video = fake_mp4()
    runpod.complete("rp-1", video)
    completed = backend.status(job.job_id)

    assert completed.status is JobStatus.COMPLETED
    assert completed.progress == 100
    assert "1024x576" in completed.message
    assert "5.04 s" in completed.message

    result = backend.result(job.job_id)
    assert Path(result.video_path).read_bytes() == video
    assert result.video_url == f"https://video.test/videos/{job.job_id}.mp4"

    record = json.loads((backend.root / "runpod" / f"{job.job_id}.json").read_text())
    assert record["provider_job_id"] == "rp-1"
    assert record["final_status"] == "completed"
    assert record["execution_ms"] == 95000
    assert len(record["seeds"]) == 2

    calls = len(runpod.calls)
    assert backend.status(job.job_id).status is JobStatus.COMPLETED
    assert len(runpod.calls) == calls


def test_worker_error_marks_job_failed(backend, runpod, plan):
    job = backend.create(plan)
    runpod.jobs["rp-1"] = {
        "id": "rp-1",
        "status": "COMPLETED",
        "output": {"status": "error", "error": "CUDA out of memory"},
    }

    failed = backend.status(job.job_id)

    assert failed.status is JobStatus.FAILED
    assert "CUDA out of memory" in failed.message
    assert not (backend.root / "outputs" / f"{job.job_id}.mp4").exists()


def test_invalid_video_is_kept_but_not_reported_complete(backend, runpod, plan):
    job = backend.create(plan)
    runpod.complete("rp-1", b"not a video")

    failed = backend.status(job.job_id)

    assert failed.status is JobStatus.FAILED
    assert (backend.root / "outputs" / f"{job.job_id}.unverified.mp4").exists()
    with pytest.raises(VideoServiceError, match="failed"):
        backend.result(job.job_id)


@pytest.mark.parametrize("state", ["FAILED", "TIMED_OUT"])
def test_provider_failure_is_reported(backend, runpod, plan, state):
    job = backend.create(plan)
    runpod.jobs["rp-1"] = {"id": "rp-1", "status": state, "error": "worker exited"}

    failed = backend.status(job.job_id)

    assert failed.status is JobStatus.FAILED
    assert "worker exited" in failed.message


def test_active_job_blocks_a_second_paid_submission(backend, runpod, plan):
    first = backend.create(plan)

    with pytest.raises(VideoServiceError, match=str(first.job_id)):
        backend.create(plan)

    assert len(runpod.runs) == 1


def test_busy_endpoint_blocks_submission(backend, runpod, plan):
    runpod.queue = {"inQueue": 1, "inProgress": 0}

    with pytest.raises(VideoServiceError, match="already has 1"):
        backend.create(plan)

    assert runpod.runs == []


def test_daily_limit_blocks_submission(backend, runpod, plan, monkeypatch):
    monkeypatch.setenv("RUNPOD_MAX_JOBS_PER_DAY", "1")
    limited = RunPodBackend(root=backend.root)
    job = limited.create(plan)
    runpod.complete("rp-1")
    limited.status(job.job_id)

    with pytest.raises(VideoServiceError, match="Daily RunPod limit"):
        limited.create(plan)

    assert len(runpod.runs) == 1


def test_jobs_older_than_a_day_do_not_count(backend, runpod, plan, monkeypatch):
    monkeypatch.setenv("RUNPOD_MAX_JOBS_PER_DAY", "1")
    limited = RunPodBackend(root=backend.root)
    old = VideoJob(
        job_id=uuid4(),
        plan=plan,
        status=JobStatus.COMPLETED,
        provider_job_id="rp-old",
        created_at=datetime.now(UTC) - timedelta(days=2),
    )
    limited._save("jobs", old.job_id, old)

    assert limited.create(plan).status is JobStatus.QUEUED


def test_rejected_submission_is_failed_and_not_billed(backend, runpod, plan):
    runpod.run_status = 401

    job = backend.create(plan)

    assert job.status is JobStatus.FAILED
    assert "nothing was billed" in job.message
    assert job.provider_job_id is None


def test_lost_submission_response_is_unknown_without_retry(backend, runpod, plan):
    runpod.run_error = httpx.ReadTimeout("lost")

    job = backend.create(plan)

    assert job.status is JobStatus.UNKNOWN
    assert backend.status(job.job_id).status is JobStatus.UNKNOWN
    assert [call for call in runpod.calls if call[1].endswith("/run")] == [
        ("POST", f"/v2/{ENDPOINT}/run")
    ]


def test_expired_provider_job_becomes_unknown(backend, runpod, plan):
    job = backend.create(plan)
    del runpod.jobs["rp-1"]

    assert backend.status(job.job_id).status is JobStatus.UNKNOWN


def test_cancel_stops_an_active_job(backend, runpod, plan):
    job = backend.create(plan)

    cancelled = backend.cancel(job.job_id)

    assert cancelled.status is JobStatus.CANCELLED
    assert ("POST", f"/v2/{ENDPOINT}/cancel/rp-1") in runpod.calls


def test_cancel_after_completion_keeps_the_video(backend, runpod, plan):
    job = backend.create(plan)
    runpod.complete("rp-1")

    with pytest.raises(VideoServiceError, match="completed"):
        backend.cancel(job.job_id)

    assert backend.result(job.job_id).video_path.endswith(f"{job.job_id}.mp4")


def test_missing_configuration_fails_before_dispatch(tmp_path, monkeypatch, runpod):
    monkeypatch.delenv("RUNPOD_API_KEY", raising=False)
    monkeypatch.setenv("RUNPOD_ENDPOINT_ID", ENDPOINT)
    backend = RunPodBackend(root=tmp_path / "data")
    Image.new("RGB", (640, 360)).save(backend.root / "incoming" / "photo.png")
    asset = backend.register_image("photo.png")

    with pytest.raises(VideoServiceError, match="RUNPOD_API_KEY"):
        backend.create(GenerationPlan(asset_id=asset.asset_id, prompt="Zoom."))

    assert runpod.calls == []


@pytest.mark.parametrize("value", ["1024x576", "1280x704", "768x448"])
def test_supported_resolutions(value):
    width, height = parse_resolution(value)

    assert f"{width}x{height}" == value


@pytest.mark.parametrize(
    "value", ["1280x720", "576x1024", "1024", "4096x2304", "640x640"]
)
def test_unsupported_resolutions(value):
    with pytest.raises(ValueError):
        parse_resolution(value)


def test_probe_reads_duration_and_size():
    assert probe_mp4(fake_mp4(1280, 704, 5000)) == (5.0, 1280, 704)


@pytest.mark.parametrize("content", [b"", b"plain text", fake_mp4()[:40]])
def test_probe_rejects_non_mp4(content):
    with pytest.raises(ValueError):
        probe_mp4(content)


def test_list_models_describes_runpod_without_network(backend, runpod, monkeypatch):
    monkeypatch.setattr(
        video_module, "__file__", str(backend.root.parent / "video_mcp" / "video.py")
    )
    from video_mcp import server

    monkeypatch.setattr(server, "backend", backend)

    async def invoke():
        async with Client(server.mcp) as client:
            result = await client.call_tool("list_video_models", {})
            return TypeAdapter(Any).dump_python(result.data, mode="json")

    data = asyncio.run(invoke())
    models = data["result"] if isinstance(data, dict) else data

    assert models[0]["backend"] == "runpod"
    assert models[0]["resolution"] == "1024x576"
    assert models[0]["generated_seconds"] == 5
    assert runpod.calls == []


def test_asset_digest_is_checked_before_dispatch(backend, runpod, plan):
    path = backend.root / "assets" / f"{plan.asset_id}.jpg"
    path.write_bytes(b"changed")

    with pytest.raises(VideoServiceError, match="changed"):
        backend.create(plan)

    assert runpod.runs == []

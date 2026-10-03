import base64
import io
from uuid import uuid4

import pytest
from PIL import Image

from video_mcp.models import JobStatus
from video_mcp.video import DemoBackend, VideoServiceError

FTYP = b"\x00\x00\x00\x18ftypisom" + b"\x00" * 48


def _png(width=1280, height=720):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), "teal").save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture
def demo(tmp_path, monkeypatch):
    prepared = tmp_path / "prepared-demo.mp4"
    prepared.write_bytes(FTYP)
    monkeypatch.setenv("AI_VIDEO_DEMO_FILE", str(prepared))
    monkeypatch.setenv("AI_VIDEO_DEMO_DELAY_SECONDS", "0")
    return DemoBackend(root=tmp_path / "data")


def _plan(backend):
    asset = backend.register_image_bytes(_png())
    return {"asset_id": str(asset.asset_id), "prompt": "A waving apple."}


def test_register_image_bytes_accepts_valid_png(demo):
    asset = demo.register_image_bytes(_png())
    assert asset.width == 1280 and asset.height == 720


def test_register_image_bytes_rejects_empty(demo):
    with pytest.raises(VideoServiceError, match="empty"):
        demo.register_image_bytes(b"")


def test_register_image_bytes_rejects_non_16x9(demo):
    with pytest.raises(VideoServiceError, match="16:9"):
        demo.register_image_bytes(_png(1000, 1000))


def test_register_image_bytes_rejects_garbage(demo):
    with pytest.raises(VideoServiceError, match="Invalid image"):
        demo.register_image_bytes(b"not an image at all")


def test_estimate_is_free_and_labelled(demo):
    estimate = demo.estimate(_plan(demo))
    assert estimate.estimated_cost == 0
    assert "demonstration" in estimate.basis.lower()


def test_create_copies_prepared_file_and_completes(demo):
    job = demo.create(_plan(demo))
    assert job.status is JobStatus.QUEUED
    assert "not generated" in job.message

    settled = demo.status(job.job_id)
    assert settled.status is JobStatus.COMPLETED
    assert settled.progress == 100

    result = demo.result(job.job_id)
    assert result.video_path.endswith(f"{job.job_id}.mp4")


def test_missing_prepared_file_is_reported(demo):
    demo.demo_file.unlink()
    with pytest.raises(VideoServiceError, match="missing"):
        demo.create(_plan(demo))


def test_non_mp4_prepared_file_is_rejected(demo):
    demo.demo_file.write_bytes(b"this is not an mp4")
    with pytest.raises(VideoServiceError, match="not a valid MP4"):
        demo.create(_plan(demo))


def test_unknown_job_is_reported(demo):
    with pytest.raises(VideoServiceError, match="Unknown"):
        demo.status(uuid4())


def test_base64_round_trip_matches_direct_bytes(demo):
    raw = _png()
    encoded = base64.b64encode(raw).decode()
    assert base64.b64decode(encoded, validate=True) == raw
    assert demo.register_image_bytes(base64.b64decode(encoded)).width == 1280

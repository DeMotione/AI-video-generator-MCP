from uuid import uuid4

import pytest
from pydantic import field_validator


from video_mcp.models import (
    GenerationPlan,
    ImageAsset,
    JobStatus,
    VideoJob,
    VideoResult,
)


@pytest.fixture
def plan_data():
    return {
        "asset_id": uuid4(),
        "prompt": "A futuristic city.",
    }


def test_plan_defaults(plan_data):
    plan = GenerationPlan(**plan_data)

    assert plan.duration == 5
    assert plan.aspect_ratio == "16:9"
    assert plan.model == "ltx-2-5-fast"
    assert plan.audio == "silent"


@pytest.mark.parametrize(
    "duration",
    [0, 1, 4, 6, 10, 60, True, False, 5.0, "5", None],
)
def test_unsupported_duration_is_rejected(plan_data, duration):
    with pytest.raises(field_validator):
        GenerationPlan(**{**plan_data, "duration": duration})


@pytest.mark.parametrize("ratio", ["9:16", "1:1", "4:3", "21:9", ""])
def test_unsupported_orientation_is_rejected(plan_data, ratio):
    with pytest.raises(field_validator):
        GenerationPlan(**{**plan_data, "aspect_ratio": ratio})


@pytest.mark.parametrize(
    "changes",
    [
        {"model": "unsupported-model"},
        {"audio": "enabled"},
        {"provider_duration": 6},
        {"unexpected": True},
    ],
)
def test_unsupported_options_are_rejected(plan_data, changes):
    with pytest.raises(field_validator):
        GenerationPlan(**{**plan_data, **changes})


@pytest.mark.parametrize("prompt", ["", "   ", "\n\t", "a" * 2001])
def test_invalid_prompt_is_rejected(plan_data, prompt):
    with pytest.raises(field_validator):
        GenerationPlan(**{**plan_data, "prompt": prompt})


def test_prompt_whitespace_is_trimmed(plan_data):
    plan = GenerationPlan(**{**plan_data, "prompt": "  A city.  "})

    assert plan.prompt == "A city."


def test_prompt_at_length_limit_is_accepted(plan_data):
    plan = GenerationPlan(**{**plan_data, "prompt": "a" * 2000})

    assert len(plan.prompt) == 2000


def test_asset_id_is_required():
    with pytest.raises(field_validator):
        GenerationPlan(prompt="A city.")


def test_invalid_asset_id_is_rejected(plan_data):
    with pytest.raises(field_validator):
        GenerationPlan(**{**plan_data, "asset_id": "invalid"})


def test_plan_is_immutable(plan_data):
    plan = GenerationPlan(**plan_data)

    with pytest.raises(field_validator):
        plan.duration = 6


def test_image_asset_defaults():
    asset = ImageAsset(
        asset_id=uuid4(),
        size_bytes=100,
        sha256="a" * 64,
    )

    assert asset.mime_type == "image/jpeg"
    assert asset.width == 1280
    assert asset.height == 720


@pytest.mark.parametrize(
    "changes",
    [
        {"width": 1920},
        {"height": 1080},
        {"mime_type": "image/png"},
        {"size_bytes": 0},
        {"sha256": "invalid"},
        {"unexpected": True},
    ],
)
def test_invalid_asset_metadata_is_rejected(changes):
    data = {
        "asset_id": uuid4(),
        "size_bytes": 100,
        "sha256": "a" * 64,
    }

    with pytest.raises(field_validator):
        ImageAsset(**{**data, **changes})


def test_job_json_round_trip(plan_data):
    job = VideoJob(
        job_id=uuid4(),
        plan=GenerationPlan(**plan_data),
        status=JobStatus.QUEUED,
        progress=0,
    )

    restored = VideoJob.model_validate_json(job.model_dump_json())

    assert restored == job
    assert restored.status is JobStatus.QUEUED
    assert restored.created_at.utcoffset().total_seconds() == 0


@pytest.mark.parametrize("progress", [-1, 101])
def test_invalid_job_progress_is_rejected(plan_data, progress):
    with pytest.raises(field_validator):
        VideoJob(
            job_id=uuid4(),
            plan=GenerationPlan(**plan_data),
            status=JobStatus.RUNNING,
            progress=progress,
        )


def test_running_job_can_have_unknown_progress(plan_data):
    job = VideoJob(
        job_id=uuid4(),
        plan=GenerationPlan(**plan_data),
        status=JobStatus.RUNNING,
        progress=None,
    )

    assert job.progress is None


def test_completed_result_defaults():
    result = VideoResult(
        job_id=uuid4(),
        video_path="outputs/video.mp4",
    )

    assert result.status == "completed"
    assert result.duration == 5
    assert result.aspect_ratio == "16:9"


@pytest.mark.parametrize("status", ["queued", "running", "failed", "unknown"])
def test_result_requires_completed_status(status):
    with pytest.raises(field_validator):
        VideoResult(
            job_id=uuid4(),
            status=status,
            video_path="outputs/video.mp4",
        )
from uuid import uuid4

import pytest
from PIL import Image
from pydantic import ValidationError

from video_mcp.models import GenerationPlan
from video_mcp.video import ComfyBackend, VideoServiceError


def forbid_dispatch(*args, **kwargs):
    pytest.fail("Invalid input reached ComfyUI.")


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
def test_invalid_plan_never_dispatches(tmp_path, monkeypatch, changes):
    backend = ComfyBackend(tmp_path)
    monkeypatch.setattr(backend, "_request", forbid_dispatch)

    plan = {"asset_id": uuid4(), "prompt": "Slow camera movement"}
    plan.update(changes)

    with pytest.raises(ValidationError):
        backend.create(plan)


def test_portrait_image_rejected(tmp_path, monkeypatch):
    backend = ComfyBackend(tmp_path)
    monkeypatch.setattr(backend, "_request", forbid_dispatch)
    Image.new("RGB", (360, 640)).save(
        tmp_path / "incoming" / "portrait.png"
    )

    with pytest.raises(VideoServiceError, match="16:9"):
        backend.register_image("portrait.png")


def test_asset_and_plan_contract(tmp_path, monkeypatch):
    backend = ComfyBackend(tmp_path)
    monkeypatch.setattr(backend, "_request", forbid_dispatch)
    Image.new("RGB", (640, 360)).save(
        tmp_path / "incoming" / "photo.png"
    )

    asset = backend.register_image("photo.png")
    plan = GenerationPlan(asset_id=asset.asset_id, prompt="Slow zoom")

    assert (asset.width, asset.height) == (1280, 720)
    assert plan.duration == 5
    assert backend.estimate(plan).generated_seconds == 6

    (tmp_path / "assets" / f"{asset.asset_id}.jpg").write_bytes(b"changed")

    with pytest.raises(VideoServiceError, match="changed"):
        backend.create(plan)
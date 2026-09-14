import pytest

import video_mcp.video as video_module
from video_mcp.video import ComfyBackend


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("COMFY_URL", raising=False)
    monkeypatch.delenv("PUBLIC_BASE_URL", raising=False)


def test_default_configuration(tmp_path, no_network):
    backend = ComfyBackend(root=tmp_path / "data")

    assert backend.comfy_url == "http://127.0.0.1:8188"
    assert backend.public_url == ""
    no_network.assert_not_called()


def test_environment_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("COMFY_URL", "http://127.0.0.1:9000/")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://desktop.example.test/")

    backend = ComfyBackend(root=tmp_path / "data")

    assert backend.comfy_url == "http://127.0.0.1:9000"
    assert backend.public_url == "https://desktop.example.test"


def test_required_directories_are_created(tmp_path):
    root = tmp_path / "data"
    ComfyBackend(root=root)

    assert {path.name for path in root.iterdir()} == {
        "incoming",
        "assets",
        "jobs",
        "outputs",
    }
    assert all(path.is_dir() for path in root.iterdir())


def test_default_data_directory_is_relative_to_project(tmp_path, monkeypatch):
    project = tmp_path / "project"
    monkeypatch.setattr(
        video_module,
        "__file__",
        str(project / "video_mcp" / "video.py"),
    )

    backend = ComfyBackend()

    assert backend.root == project / "data"
    assert backend.root.is_dir()


def test_initialization_preserves_existing_data(tmp_path):
    root = tmp_path / "data"
    jobs = root / "jobs"
    jobs.mkdir(parents=True)

    existing = jobs / "existing.json"
    existing.write_text('{"preserved": true}')

    ComfyBackend(root=root)

    assert existing.read_text() == '{"preserved": true}'


def test_mock_timing_variables_do_not_affect_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("AI_VIDEO_MOCK_QUEUED_SECONDS", "invalid")
    monkeypatch.setenv("AI_VIDEO_MOCK_RUNNING_SECONDS", "-100")

    backend = ComfyBackend(root=tmp_path / "data")

    assert backend.comfy_url == "http://127.0.0.1:8188"
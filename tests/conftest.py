import asyncio
from copy import deepcopy
from typing import Any
from unittest.mock import Mock
from uuid import uuid4

import httpx
import pytest
from fastmcp import Client
from PIL import Image
from pydantic import TypeAdapter

import video_mcp.video as video_module
from video_mcp.models import GenerationPlan
from video_mcp.video import ComfyBackend


class ComfyStub:
    def __init__(self):
        self.calls = []
        self.uploads = {}
        self.jobs = {}
        self.video_bytes = b"test-video-content"
        self.accept_then_timeout = False
        self.health = {
            "ready": True,
            "missing": [],
            "preset": "ltx25-fast-5s-16x9-v1",
        }

    def request(self, method, url, **kwargs):
        request = httpx.Request(
            method,
            url,
            params=kwargs.get("params"),
        )
        path = request.url.path
        self.calls.append((method, path, deepcopy(kwargs)))

        def response(payload=None, content=None, status=200):
            if content is not None:
                return httpx.Response(
                    status,
                    content=content,
                    request=request,
                )
            return httpx.Response(
                status,
                json=payload,
                request=request,
            )

        if method == "GET" and path == "/avg/health":
            return response(self.health)

        if method == "POST" and path == "/upload/image":
            filename, content, mime_type = kwargs["files"]["image"]
            self.uploads[filename] = {
                "content": content,
                "mime_type": mime_type,
            }
            return response({
                "name": filename,
                "subfolder": "avg-input",
                "type": "input",
            })

        if method == "POST" and path == "/prompt":
            identifier = str(uuid4())
            self.jobs[identifier] = {
                "payload": deepcopy(kwargs["json"]),
                "state": "queued",
            }

            if self.accept_then_timeout:
                raise httpx.ReadTimeout(
                    "Response lost after acceptance.",
                    request=request,
                )

            return response({
                "prompt_id": identifier,
                "node_errors": {},
            })

        if method == "GET" and path == "/queue":
            return response({
                "queue_running": [
                    [index, identifier]
                    for index, (identifier, job) in enumerate(self.jobs.items())
                    if job["state"] == "running"
                ],
                "queue_pending": [
                    [index, identifier]
                    for index, (identifier, job) in enumerate(self.jobs.items())
                    if job["state"] == "queued"
                ],
            })

        if method == "GET" and path.startswith("/history/"):
            identifier = path.rsplit("/", 1)[1]
            job = self.jobs.get(identifier)

            if job is None:
                return response({})

            if "history" in job:
                return response({identifier: job["history"]})

            if job["state"] == "failed":
                return response({
                    identifier: {
                        "status": {
                            "status_str": "error",
                            "completed": False,
                        },
                        "outputs": {},
                    }
                })

            if job["state"] != "completed":
                return response({})

            request_id = job["payload"]["prompt"]["2"]["inputs"]["request_id"]
            return response({
                identifier: {
                    "status": {
                        "status_str": "success",
                        "completed": True,
                    },
                    "outputs": {
                        "2": {
                            "avg_video": [{
                                "filename": f"{request_id}.mp4",
                                "subfolder": "avg",
                                "type": "output",
                            }]
                        }
                    },
                }
            })

        if method == "GET" and path == "/view":
            assert request.url.params["subfolder"] == "avg"
            assert request.url.params["type"] == "output"

            filename = request.url.params["filename"]
            for job in self.jobs.values():
                request_id = job["payload"]["prompt"]["2"]["inputs"]["request_id"]
                if (
                    filename == f"{request_id}.mp4"
                    and job["state"] == "completed"
                ):
                    return response(content=self.video_bytes)

            return response({"error": "Missing video"}, status=404)

        raise AssertionError(f"Unexpected request: {method} {url}")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    blocked = Mock(side_effect=AssertionError("Unexpected network request."))
    monkeypatch.setattr(httpx, "request", blocked)
    return blocked


@pytest.fixture
def comfy(monkeypatch):
    stub = ComfyStub()
    monkeypatch.setattr(httpx, "request", stub.request)
    return stub


@pytest.fixture
def backend(tmp_path, monkeypatch, comfy):
    monkeypatch.setenv("COMFY_URL", "http://comfy.test:8188")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://video.test")
    return ComfyBackend(root=tmp_path / "data")


@pytest.fixture
def asset(backend):
    Image.new("RGB", (640, 360), "navy").save(
        backend.root / "incoming" / "photo.png"
    )
    return backend.register_image("photo.png")


@pytest.fixture
def plan(asset):
    return GenerationPlan(
        asset_id=asset.asset_id,
        prompt="A slow camera movement through a futuristic city.",
    )


@pytest.fixture
def server_module(backend, monkeypatch):
    monkeypatch.setattr(
        video_module,
        "__file__",
        str(backend.root.parent / "video_mcp" / "video.py"),
    )
    from video_mcp import server

    monkeypatch.setattr(server, "backend", backend)
    return server


@pytest.fixture
def expected_tools():
    return {
        "list_video_models",
        "register_image",
        "estimate_video_cost",
        "create_video",
        "get_video_status",
        "get_video_result",
    }


@pytest.fixture
def call_tool(server_module):
    def call(name, **arguments):
        async def invoke():
            async with Client(server_module.mcp) as client:
                result = await client.call_tool(name, arguments)
                data = TypeAdapter(Any).dump_python(
                    result.data,
                    mode="json",
                )
                if isinstance(data, dict) and set(data) == {"result"}:
                    return data["result"]
                return data

        return asyncio.run(invoke())

    return call


@pytest.fixture
def list_tools(server_module):
    def get_tools():
        async def invoke():
            async with Client(server_module.mcp) as client:
                return await client.list_tools()

        return asyncio.run(invoke())

    return get_tools
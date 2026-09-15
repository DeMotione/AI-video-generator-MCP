import asyncio
from uuid import uuid4

import httpx
import pytest
from fastmcp.exceptions import ToolError
from PIL import Image


def test_server_exposes_current_tools(list_tools, expected_tools):
    assert {tool.name for tool in list_tools()} == expected_tools


def test_every_tool_has_a_description(list_tools):
    for tool in list_tools():
        assert tool.description


def test_create_schema_advertises_foundation_contract(list_tools):
    tool = next(tool for tool in list_tools() if tool.name == "create_video")
    schema = getattr(tool, "input_schema", None)
    if schema is None:
        schema = tool.input_schema

    assert set(schema["required"]) == {"plan"}

    plan_schema = schema["properties"]["plan"]
    while "$ref" in plan_schema:
        reference = plan_schema["$ref"]
        assert reference.startswith("#/")
        plan_schema = schema
        for part in reference[2:].split("/"):
            plan_schema = plan_schema[part]

    assert set(plan_schema["required"]) == {"asset_id", "prompt"}
    assert plan_schema["additionalProperties"] is False

    duration = plan_schema["properties"]["duration"]
    assert duration["type"] == "integer"
    assert duration["minimum"] == 5
    assert duration["maximum"] == 5
    assert duration["default"] == 5

    ratio = plan_schema["properties"]["aspect_ratio"]
    assert ratio.get("const") == "16:9" or ratio.get("enum") == ["16:9"]


def test_list_models_does_not_dispatch(call_tool, comfy):
    models = call_tool("list_video_models")

    assert len(models) == 1
    assert models[0]["model"] == "ltx-2-5-fast"
    assert models[0]["duration"] == 5
    assert models[0]["aspect_ratio"] == "16:9"
    assert models[0]["audio"] == "silent"
    assert comfy.calls == []


def test_full_tool_workflow(call_tool, backend, comfy):
    Image.new("RGB", (640, 360), "navy").save(
        backend.root / "incoming" / "photo.png"
    )

    asset = call_tool("register_image", filename="photo.png")
    plan = {
        "asset_id": asset["asset_id"],
        "prompt": "The camera moves slowly forward.",
    }

    estimate = call_tool("estimate_video_cost", plan=plan)

    assert estimate["estimated_cost"] == pytest.approx(0.54)
    assert estimate["generated_seconds"] == 6
    assert estimate["delivered_seconds"] == 5
    assert comfy.calls == []

    job = call_tool("create_video", plan=plan)

    assert job["status"] == "queued"
    assert job["plan"]["duration"] == 5

    comfy.jobs[job["comfy_id"]]["state"] = "running"

    running = call_tool("get_video_status", job_id=job["job_id"])
    assert running["status"] == "running"
    assert running["progress"] is None

    comfy.jobs[job["comfy_id"]]["state"] = "completed"

    completed = call_tool("get_video_status", job_id=job["job_id"])
    assert completed["status"] == "completed"

    result = call_tool("get_video_result", job_id=job["job_id"])

    assert result["status"] == "completed"
    assert result["duration"] == 5
    assert result["video_url"].endswith(f"/videos/{job['job_id']}.mp4")


@pytest.mark.parametrize("changes", [
    {"duration": 6},
    {"duration": "5"},
    {"duration": 5.0},
    {"aspect_ratio": "9:16"},
    {"model": "unsupported"},
    {"audio": "enabled"},
    {"prompt": ""},
    {"prompt": "   "},
    {"unexpected": True},
])
def test_invalid_plans_fail_before_dispatch(
    call_tool, backend, comfy, plan, changes
):
    arguments = plan.model_dump(mode="json") | changes

    with pytest.raises(ToolError):
        call_tool("create_video", plan=arguments)

    assert comfy.calls == []
    assert list((backend.root / "jobs").glob("*.json")) == []


def test_text_only_create_call_is_rejected(call_tool, comfy):
    with pytest.raises(ToolError):
        call_tool("create_video", prompt="A city.")

    assert comfy.calls == []


def test_unknown_asset_is_reported(call_tool, comfy):
    with pytest.raises(ToolError, match="Unknown assets ID"):
        call_tool(
            "create_video",
            plan={"asset_id": str(uuid4()), "prompt": "Slow zoom."},
        )

    assert comfy.calls == []


def test_unknown_job_is_reported(call_tool, comfy):
    with pytest.raises(ToolError, match="Unknown jobs ID"):
        call_tool("get_video_status", job_id=str(uuid4()))

    assert comfy.calls == []


def test_invalid_job_id_is_rejected(call_tool, comfy):
    with pytest.raises(ToolError):
        call_tool("get_video_status", job_id="invalid")

    assert comfy.calls == []


def test_result_is_unavailable_while_queued(call_tool, plan):
    job = call_tool("create_video", plan=plan.model_dump(mode="json"))

    with pytest.raises(ToolError, match="queued"):
        call_tool("get_video_result", job_id=job["job_id"])


def test_node_readiness_error_is_reported(call_tool, comfy, plan):
    comfy.health.update(ready=False, missing=["ffmpeg"])

    with pytest.raises(ToolError, match="not ready"):
        call_tool("create_video", plan=plan.model_dump(mode="json"))

    assert comfy.jobs == {}


def test_uncertain_submission_returns_job_without_retry(call_tool, comfy, plan):
    comfy.accept_then_timeout = True

    job = call_tool("create_video", plan=plan.model_dump(mode="json"))

    assert job["status"] == "unknown"
    assert "unknown" in job["message"].lower()
    assert len(comfy.jobs) == 1


def test_video_download_route(server_module, backend, comfy, plan):
    job = backend.create(plan)
    comfy.jobs[job.comfy_id]["state"] = "completed"
    backend.result(job.job_id)

    async def download():
        app = server_module.mcp.http_app()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1",
            ) as client:
                return await client.get(f"/videos/{job.job_id}.mp4")

    response = asyncio.run(download())

    assert response.status_code == 200
    assert response.content == comfy.video_bytes
    assert response.headers["content-type"].startswith("video/mp4")


def test_invalid_download_id_returns_404(server_module):
    async def download():
        app = server_module.mcp.http_app()
        async with app.router.lifespan_context(app):
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url="http://127.0.0.1",
            ) as client:
                return await client.get("/videos/invalid.mp4")

    assert asyncio.run(download()).status_code == 404
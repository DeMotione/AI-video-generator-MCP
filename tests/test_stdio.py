import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from PIL import Image
from pydantic import TypeAdapter


PROJECT_ROOT = Path(__file__).resolve().parent.parent

STDIO_BOOTSTRAP = """
import os
from pathlib import Path
import video_mcp.video as video_module

video_module.__file__ = str(
    Path(os.environ["AVG_TEST_ROOT"]) / "video_mcp" / "video.py"
)

from video_mcp.server import mcp

mcp.run(transport="stdio")
"""

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "avg-tests", "version": "1"},
    },
}


@pytest.fixture
def stdio_env(tmp_path):
    incoming = tmp_path / "data" / "incoming"
    incoming.mkdir(parents=True)
    Image.new("RGB", (640, 360), "navy").save(incoming / "photo.png")

    return {
        **os.environ,
        "AVG_TEST_ROOT": str(tmp_path),
        "COMFY_URL": "http://127.0.0.1:1",
        "PUBLIC_BASE_URL": "https://video.test",
        "PYTHONUNBUFFERED": "1",
    }


def make_transport(env):
    return StdioTransport(
        command=sys.executable,
        args=["-u", "-c", STDIO_BOOTSTRAP],
        cwd=str(PROJECT_ROOT),
        env=env,
    )


def result_data(result):
    return TypeAdapter(Any).dump_python(result.data, mode="json")


def test_server_exposes_tools_over_explicit_stdio(stdio_env, expected_tools):
    async def drive():
        async with Client(make_transport(stdio_env)) as client:
            return {tool.name for tool in await client.list_tools()}

    tools = asyncio.run(asyncio.wait_for(drive(), timeout=60))

    assert tools == expected_tools


def test_stdio_registration_and_estimation_without_generation(stdio_env):
    async def drive():
        async with Client(make_transport(stdio_env)) as client:
            asset = result_data(await client.call_tool(
                "register_image",
                {"filename": "photo.png"},
            ))
            estimate = result_data(await client.call_tool(
                "estimate_video_cost",
                {
                    "plan": {
                        "asset_id": asset["asset_id"],
                        "prompt": "Slow forward camera movement.",
                    }
                },
            ))
            return asset, estimate

    asset, estimate = asyncio.run(
        asyncio.wait_for(drive(), timeout=60)
    )

    assert asset["width"] == 1280
    assert asset["height"] == 720
    assert estimate["estimated_cost"] == pytest.approx(0.54)
    assert estimate["generated_seconds"] == 6
    assert estimate["delivered_seconds"] == 5


def test_stdio_rejects_unsupported_duration_before_backend_call(stdio_env):
    async def drive():
        async with Client(make_transport(stdio_env)) as client:
            with pytest.raises(ToolError) as error:
                await client.call_tool(
                    "create_video",
                    {
                        "plan": {
                            "asset_id": str(uuid4()),
                            "prompt": "Slow zoom.",
                            "duration": 6,
                        }
                    },
                )
            return str(error.value)

    message = asyncio.run(asyncio.wait_for(drive(), timeout=60))

    assert "duration" in message.lower()
    assert "cannot reach comfyui" not in message.lower()


def test_nothing_but_json_rpc_reaches_stdout(stdio_env):
    async def drive():
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-u",
            "-c",
            STDIO_BOOTSTRAP,
            cwd=str(PROJECT_ROOT),
            env=stdio_env,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )

        async def send(message):
            process.stdin.write((json.dumps(message) + "\n").encode())
            await process.stdin.drain()

        async def receive(identifier):
            while True:
                line = await asyncio.wait_for(
                    process.stdout.readline(),
                    timeout=45,
                )
                assert line, "Server closed stdout before replying."
                message = json.loads(line)
                assert message["jsonrpc"] == "2.0"
                if message.get("id") == identifier:
                    return message

        try:
            await send(INITIALIZE)
            initialized = await receive(1)

            assert "error" not in initialized
            assert (
                initialized["result"]["serverInfo"]["name"]
                == "AI Video Generator"
            )

            await send({
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            })
            await send({
                "jsonrpc": "2.0",
                "id": 2,
                "method": "ping",
            })

            ping = await receive(2)
            assert "result" in ping
            assert "error" not in ping

            process.stdin.close()
            await asyncio.wait_for(process.wait(), timeout=10)

            remaining = await process.stdout.read()
            for line in remaining.splitlines():
                if line.strip():
                    assert json.loads(line)["jsonrpc"] == "2.0"

            assert process.returncode == 0
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    asyncio.run(drive())
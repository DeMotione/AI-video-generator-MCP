"""Offline job API tests: python -m unittest discover -s deploy/vm/agent -p test_jobs.py."""

import asyncio
import base64
import io
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
from fastapi.testclient import TestClient
from PIL import Image

import agent


class JobApiTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        patches = [
            patch.object(agent, "JOB_ROOT", self.root),
            patch.object(agent, "API_TOKEN", "a" * 40),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        image = io.BytesIO()
        Image.new("RGB", (640, 360), "navy").save(image, "PNG")
        self.payload = {
            "request_id": str(uuid4()),
            "prompt": "The camera moves slowly.",
            "image_base64": base64.b64encode(image.getvalue()).decode(),
        }
        self.headers = {"Authorization": "Bearer " + "a" * 40}
        self.remote_id = str(uuid4())
        self.remote_status = "queued"

        @asynccontextmanager
        async def mcp():
            async def call(name, arguments):
                self.assertEqual(name, "get_video_status")
                self.assertEqual(arguments["job_id"], self.remote_id)
                return SimpleNamespace(
                    is_error=False,
                    structured_content={
                        "status": self.remote_status,
                        "message": "Remote status.",
                    },
                )

            yield SimpleNamespace(list_tools=AsyncMock(return_value=[]), call_tool=call)

        self.mcp_patch = patch.object(agent, "mcp_client", mcp)
        self.mcp_patch.start()
        self.addCleanup(self.mcp_patch.stop)

    async def decide(self, client, tools, payload, model_client, on_submission, on_created):
        on_submission()
        on_created({"job_id": self.remote_id, "status": "queued", "message": "Queued."})
        return {"status": "pending"}

    def client(self):
        return TestClient(agent.app)

    def wait_for_decision(self, client):
        # Drain the asynchronous task without wall-clock sleeps.
        async def drain():
            await asyncio.gather(*list(agent.app.state.tasks))

        client.portal.call(drain)

    def test_authentication_and_image_validation(self):
        with self.client() as client:
            self.assertEqual(client.post("/jobs", json=self.payload).status_code, 401)
            invalid = {**self.payload, "image_base64": "invalid"}
            self.assertEqual(
                client.post("/jobs", json=invalid, headers=self.headers).status_code, 400
            )
            self.assertIsNone(agent.saved_request(self.payload["request_id"]))

    def test_duplicate_submission_runs_gemma_once_and_cleans_temp_image(self):
        with patch.object(agent, "process_question", side_effect=self.decide) as decide:
            with self.client() as client:
                first = client.post("/jobs", json=self.payload, headers=self.headers)
                self.assertEqual(first.status_code, 202)
                self.wait_for_decision(client)
                second = client.post("/jobs", json=self.payload, headers=self.headers)
                self.assertEqual(second.status_code, 200)
                self.assertEqual(second.json()["job_id"], self.remote_id)
                self.assertEqual(decide.call_count, 1)
                changed = {**self.payload, "prompt": "A different request."}
                self.assertEqual(
                    client.post("/jobs", json=changed, headers=self.headers).status_code, 409
                )
        self.assertEqual(list(self.root.glob("*.image.tmp")), [])

    def test_known_job_survives_agent_restart(self):
        with patch.object(agent, "process_question", side_effect=self.decide) as decide:
            with self.client() as client:
                client.post("/jobs", json=self.payload, headers=self.headers)
                self.wait_for_decision(client)
            self.remote_status = "completed"
            with self.client() as client:
                response = client.get(f"/jobs/{self.payload['request_id']}", headers=self.headers)
                self.assertEqual(response.json()["status"], "completed")
                self.assertEqual(decide.call_count, 1)

    def test_interrupted_submission_becomes_unknown_without_resubmitting(self):
        with agent.job_database() as database:
            database.execute(
                "INSERT INTO requests (request_id, fingerprint, status) VALUES (?, ?, ?)",
                (self.payload["request_id"], "fingerprint", "submitting"),
            )
        with patch.object(agent, "process_question") as decide:
            with self.client() as client:
                response = client.get(f"/jobs/{self.payload['request_id']}", headers=self.headers)
                self.assertEqual(response.json()["status"], "unknown")
                decide.assert_not_called()

    def test_another_request_waits_while_video_is_running(self):
        with patch.object(agent, "process_question", side_effect=self.decide):
            with self.client() as client:
                client.post("/jobs", json=self.payload, headers=self.headers)
                self.wait_for_decision(client)
                other = {**self.payload, "request_id": str(uuid4())}
                self.assertEqual(
                    client.post("/jobs", json=other, headers=self.headers).status_code, 429
                )

    def test_download_uses_private_mcp_and_requires_credentials(self):
        with agent.job_database() as database:
            database.execute(
                "INSERT INTO requests (request_id, fingerprint, status, job_id) "
                "VALUES (?, ?, 'completed', ?)",
                (self.payload["request_id"], "fingerprint", self.remote_id),
            )
        outgoing = []

        def handler(request):
            outgoing.append(request)
            self.assertEqual(str(request.url), f"http://127.0.0.1:8001/videos/{self.remote_id}.mp4")
            return httpx.Response(
                200, content=b"mp4-content", headers={"Content-Type": "video/mp4"}
            )

        real_client = httpx.AsyncClient
        with patch.object(
            agent.httpx,
            "AsyncClient",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ):
            with self.client() as client:
                path = f"/jobs/{self.payload['request_id']}/video"
                self.assertEqual(client.get(path).status_code, 401)
                response = client.get(path, headers=self.headers)
                self.assertEqual(response.content, b"mp4-content")
                self.assertEqual(response.headers["Content-Type"], "video/mp4")
        self.assertEqual(len(outgoing), 1)

    def test_gemma_submission_is_recorded_before_create_and_returns_without_polling(self):
        events = []
        asset_id = str(uuid4())
        payload = agent.ChatRequest.model_validate(self.payload)
        tools = [
            SimpleNamespace(name="register_image_base64"),
            SimpleNamespace(
                name="create_video",
                description="Generate a video.",
                input_schema={"type": "object", "properties": {"plan": {"type": "object"}}},
            ),
        ]

        async def call(name, arguments, **kwargs):
            if name == "register_image_base64":
                data = {"asset_id": asset_id}
            else:
                self.assertEqual(events, ["submitting"])
                self.assertEqual(arguments["plan"]["asset_id"], asset_id)
                data = {"job_id": self.remote_id, "status": "queued"}
            return SimpleNamespace(is_error=False, structured_content=data)

        decision = agent.Decision(
            action="tool",
            tool_name="create_video",
            arguments={"plan": {"asset_id": asset_id, "prompt": self.payload["prompt"]}},
        )
        with (
            patch.object(agent, "ask_gemma", AsyncMock(return_value=decision)),
            patch.object(agent, "follow_job", AsyncMock()) as follow,
        ):
            result = asyncio.run(
                agent.process_question(
                    SimpleNamespace(call_tool=call),
                    tools,
                    payload,
                    None,
                    on_submission=lambda: events.append("submitting"),
                    on_created=lambda data: events.append(data["job_id"]),
                )
            )
            follow.assert_not_called()
        self.assertEqual(events, ["submitting", self.remote_id])
        self.assertEqual(result["status"], "pending")


if __name__ == "__main__":
    unittest.main()

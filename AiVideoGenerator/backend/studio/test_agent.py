import base64
import io
import json
from unittest.mock import patch
from uuid import uuid4

import httpx
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from studio import tests as studio_fixtures
from studio.models import Generation
from studio.services.jobs import worker_tick
from studio.services.storage import get_storage


@override_settings(GENERATION_BACKEND="agent", AGENT_API_TOKEN="a" * 40)
class AgentTests(TestCase):
    submit = studio_fixtures.StudioTests.submit

    def setUp(self):
        studio_fixtures.StudioTests.setUp(self)
        override = override_settings(GENERATION_BACKEND="agent", AGENT_API_TOKEN="a" * 40)
        override.enable()
        self.addCleanup(override.disable)

    def use_agent(self, handler):
        self.network.stop()
        real_client = httpx.Client
        mock = patch(
            "studio.services.agent.httpx.Client",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        )
        mock.start()
        self.addCleanup(mock.stop)

    def test_upload_does_not_require_comfy_workflow_and_preserves_backend(self):
        self.workflow.unlink()
        self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(Generation.objects.get().backend, "agent")

    def test_incompatible_image_is_rejected_before_job_creation(self):
        content = io.BytesIO()
        Image.new("RGB", (512, 512)).save(content, "PNG")
        image = SimpleUploadedFile("square.png", content.getvalue(), content_type="image/png")
        self.assertEqual(self.submit(image=image).status_code, 400)
        self.assertFalse(Generation.objects.exists())

    def test_agent_lifecycle_and_authenticated_download(self):
        self.submit()
        job = Generation.objects.get()
        remote_id = str(uuid4())
        submitted = []

        def handler(request):
            self.assertEqual(request.headers["Authorization"], "Bearer " + "a" * 40)
            if request.method == "POST":
                body = json.loads(request.content)
                self.assertEqual(body["request_id"], str(job.pk))
                self.assertEqual(body["prompt"], job.prompt)
                with Image.open(io.BytesIO(base64.b64decode(body["image_base64"]))) as image:
                    self.assertEqual(image.size, (640, 360))
                submitted.append(body)
                return httpx.Response(
                    202,
                    json={
                        "request_id": str(job.pk),
                        "status": "planning",
                        "job_id": None,
                        "message": "Gemma is planning.",
                    },
                )
            if request.url.path.endswith("/video"):
                return httpx.Response(200, content=b"private-mp4")
            return httpx.Response(
                200,
                json={
                    "request_id": str(job.pk),
                    "status": "completed",
                    "job_id": remote_id,
                    "message": "Video ready.",
                },
            )

        self.use_agent(handler)
        worker_tick()
        job.refresh_from_db()
        self.assertEqual(job.status, "running")
        worker_tick()
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        self.assertEqual(job.remote_job_id, remote_id)
        response = self.client.get(
            reverse("studio:media", args=[job.pk, "video"]) + "?download=1"
        )
        self.assertEqual(b"".join(response.streaming_content), b"private-mp4")
        self.assertIn("attachment", response["Content-Disposition"])
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.get(reverse("studio:media", args=[job.pk, "video"])).status_code, 404
        )
        worker_tick()
        self.assertEqual(len(submitted), 1)

    def test_lost_acceptance_response_is_reconciled_without_resubmission(self):
        self.submit()
        job = Generation.objects.get()
        submissions = []

        def handler(request):
            if request.method == "POST":
                submissions.append(request)
                raise httpx.ReadTimeout("Response lost", request=request)
            return httpx.Response(
                200,
                json={
                    "request_id": str(job.pk),
                    "status": "planning",
                    "message": "Working.",
                    "job_id": None,
                },
            )

        self.use_agent(handler)
        worker_tick()
        self.assertEqual(Generation.objects.get().status, "submitting")
        worker_tick()
        self.assertEqual(Generation.objects.get().status, "running")
        self.assertEqual(len(submissions), 1)

    def test_busy_agent_leaves_request_queued(self):
        self.submit()
        self.use_agent(lambda request: httpx.Response(429))
        worker_tick()
        self.assertEqual(Generation.objects.get().status, "queued")

    def test_accepted_request_is_not_resubmitted_if_vm_record_is_missing(self):
        self.submit()
        Generation.objects.update(status="running")
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(404)

        self.use_agent(handler)
        worker_tick()
        self.assertEqual(Generation.objects.get().status, "unknown")
        self.assertTrue(all(request.method == "GET" for request in requests))

    def test_download_failure_is_retried_without_regeneration(self):
        self.submit()
        job = Generation.objects.get()
        Generation.objects.update(status="running")
        attempts = []

        def handler(request):
            self.assertEqual(request.method, "GET")
            if request.url.path.endswith("/video"):
                attempts.append(request)
                return (
                    httpx.Response(503)
                    if len(attempts) == 1
                    else httpx.Response(200, content=b"mp4")
                )
            return httpx.Response(
                200,
                json={
                    "request_id": str(job.pk),
                    "status": "completed",
                    "job_id": str(uuid4()),
                    "message": "Ready.",
                },
            )

        self.use_agent(handler)
        worker_tick()
        self.assertEqual(Generation.objects.get().status, "running")
        worker_tick()
        job.refresh_from_db()
        self.assertEqual(job.status, "completed")
        with get_storage().open(job.video_key) as stream:
            self.assertEqual(stream.read(), b"mp4")

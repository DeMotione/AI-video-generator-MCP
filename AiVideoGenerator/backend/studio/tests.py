import importlib.util
import io
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import Mock, patch
from uuid import uuid4

import httpx
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from studio.models import Conversation, Generation
from studio.services.comfy import ComfyClient, ComfyError, GenerationError, load_workflow
from studio.services.jobs import worker_tick
from studio.services.storage import LocalStorage, OCIStorage, get_storage

WORKFLOW = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "example.png"}},
    "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "Original prompt"}},
    "3": {"class_type": "VideoOutput", "inputs": {}},
}


def image_upload():
    output = io.BytesIO()
    Image.new("RGB", (640, 360), "#8f9d75").save(output, format="PNG")
    return SimpleUploadedFile("photo.png", output.getvalue(), content_type="image/png")


class StudioTests(TestCase):
    def setUp(self):
        cache.clear()
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.workflow = root / "workflow.json"
        self.workflow.write_text(json.dumps(WORKFLOW), encoding="utf-8")
        override = override_settings(
            PRIVATE_STORAGE_ROOT=root / "private",
            STORAGE_BACKEND="local",
            COMFY_WORKFLOW_PATH=self.workflow,
            COMFY_IMAGE_NODE_ID="1",
            COMFY_PROMPT_NODE_ID="2",
            COMFY_PROMPT_INPUT="text",
            COMFY_OUTPUT_NODE_ID="3",
            COMFY_VIDEO_OUTPUT_KEY="",
        )
        override.enable()
        self.addCleanup(override.disable)
        self.network = patch(
            "httpx.Client.send", side_effect=AssertionError("Unexpected network")
        )
        self.network.start()
        self.addCleanup(self.network.stop)
        self.owner = get_user_model().objects.create_user(
            "owner@example.com", "A-strong-test!123"
        )
        self.other = get_user_model().objects.create_user(
            "other@example.com", "A-strong-test!123"
        )
        self.client.force_login(self.owner)
        self.conversation = Conversation.objects.create(owner=self.owner)

    def submit(self, **changes):
        data = {
            "request_id": str(uuid4()),
            "prompt": "A slow camera move.",
            "image": image_upload(),
        }
        data.update(changes)
        return self.client.post(reverse("studio:generate", args=[self.conversation.pk]), data)

    def test_login_is_required_for_page_and_api(self):
        self.client.logout()
        self.assertEqual(self.client.get("/").status_code, 302)
        self.assertEqual(self.client.get("/api/conversations/").status_code, 401)
        self.assertEqual(self.client.post("/api/conversations/new/").status_code, 401)

    def test_email_login_creates_database_session_and_normalizes_case(self):
        self.client.logout()
        response = self.client.post(
            "/auth/login/",
            {
                "username": " OWNER@EXAMPLE.COM ",
                "password": "A-strong-test!123",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        self.assertTrue(self.owner.check_password("A-strong-test!123"))
        self.assertNotEqual(self.owner.password, "A-strong-test!123")

    def test_invalid_login_uses_generic_error(self):
        self.client.logout()
        response = self.client.post(
            "/auth/login/", {"username": self.owner.email, "password": "no"}
        )
        self.assertContains(response, "The email or password is incorrect.")
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_repeated_login_failures_are_throttled(self):
        self.client.logout()
        for _ in range(10):
            self.client.post("/auth/login/", {"username": "none@example.com", "password": "no"})
        response = self.client.post(
            "/auth/login/", {"username": "none@example.com", "password": "no"}
        )
        self.assertEqual(response.status_code, 429)

    def test_inactive_user_cannot_log_in(self):
        self.owner.is_active = False
        self.owner.save()
        self.client.logout()
        self.client.post(
            "/auth/login/",
            {
                "username": self.owner.email,
                "password": "A-strong-test!123",
            },
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_logout_is_post_only_and_invalidates_session(self):
        self.assertEqual(self.client.get("/auth/logout/").status_code, 405)
        self.assertEqual(self.client.post("/auth/logout/").status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_csrf_is_enforced_for_upload_and_logout(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.owner)
        self.assertEqual(client.post("/api/conversations/new/").status_code, 403)
        self.assertEqual(client.post("/auth/logout/").status_code, 403)

    def test_upload_is_normalized_and_queued_without_dispatch(self):
        response = self.submit()
        self.assertEqual(response.status_code, 201)
        job = Generation.objects.get()
        self.assertEqual(job.status, "queued")
        with get_storage().open(job.image_key) as stream:
            with Image.open(stream) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (640, 360))

    def test_duplicate_request_returns_same_job(self):
        identifier = str(uuid4())
        first = self.submit(request_id=identifier)
        second = self.submit(request_id=identifier)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Generation.objects.count(), 1)

    def test_invalid_inputs_never_create_job(self):
        for changes in [{"prompt": " "}, {"prompt": "x" * 2001}, {"request_id": "invalid"}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.submit(**changes).status_code, 400)
        invalid = SimpleUploadedFile("fake.png", b"not an image", content_type="image/png")
        self.assertEqual(self.submit(image=invalid).status_code, 400)
        self.assertEqual(Generation.objects.count(), 0)

    @override_settings(MAX_IMAGE_BYTES=5)
    def test_oversized_image_is_rejected(self):
        self.assertEqual(self.submit().status_code, 400)
        self.assertFalse(Generation.objects.exists())

    def test_missing_workflow_fails_before_enqueue(self):
        self.workflow.unlink()
        self.assertEqual(self.submit().status_code, 400)
        self.assertFalse(Generation.objects.exists())

    def test_active_job_limit(self):
        for _ in range(3):
            self.assertEqual(self.submit().status_code, 201)
        self.assertEqual(self.submit().status_code, 429)

    def test_other_user_cannot_read_conversation_or_private_image(self):
        job = self.submit().json()
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(job["image_url"]).status_code, 404)
        detail = reverse("studio:detail", args=[self.conversation.pk])
        self.assertEqual(self.client.get(detail).status_code, 404)
        self.assertEqual(self.submit().status_code, 404)
        self.assertEqual(self.client.get("/api/conversations/").json()["conversations"], [])

    def test_private_media_does_not_survive_logout(self):
        job = self.submit().json()
        self.assertEqual(self.client.get(job["image_url"]).status_code, 200)
        self.client.logout()
        self.assertEqual(self.client.get(job["image_url"]).status_code, 401)

    def test_video_playback_supports_authenticated_ranges(self):
        self.submit()
        job = Generation.objects.get()
        job.status = "completed"
        job.video_key = f"users/{self.owner.pk}/videos/{job.pk}.mp4"
        get_storage().put(job.video_key, io.BytesIO(b"0123456789"), "video/mp4")
        job.save()
        url = reverse("studio:media", args=[job.pk, "video"])
        response = self.client.get(url, HTTP_RANGE="bytes=2-5")
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response["Content-Range"], "bytes 2-5/10")
        self.assertEqual(b"".join(response.streaming_content), b"2345")
        self.assertIn("private", response["Cache-Control"])
        self.assertEqual(self.client.get(url, HTTP_RANGE="bytes=99-").status_code, 416)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_local_storage_blocks_path_traversal(self):
        with self.assertRaises(ValueError):
            LocalStorage().open("../../secret")

    def test_worker_full_lifecycle_uses_exported_graph(self):
        self.submit()
        job = Generation.objects.get()
        requests = []

        def handler(request):
            requests.append(request)
            if request.url.path == "/upload/image":
                return httpx.Response(200, json={"name": "uploaded.png", "subfolder": "avg"})
            if request.url.path == "/prompt":
                body = json.loads(request.content)
                self.assertEqual(body["prompt"]["1"]["inputs"]["image"], "avg/uploaded.png")
                self.assertEqual(body["prompt"]["2"]["inputs"]["text"], job.prompt)
                self.assertEqual(body["extra_data"]["avg_job_id"], str(job.pk))
                return httpx.Response(200, json={"prompt_id": "comfy-job", "node_errors": {}})
            if request.url.path == "/history/comfy-job":
                return httpx.Response(
                    200,
                    json={
                        "comfy-job": {
                            "status": {"completed": True, "status_str": "success"},
                            "outputs": {
                                "3": {
                                    "gifs": [
                                        {
                                            "filename": "result.mp4",
                                            "subfolder": "",
                                            "type": "output",
                                        }
                                    ]
                                }
                            },
                        }
                    },
                )
            if request.url.path == "/view":
                return httpx.Response(200, content=b"test-video")
            raise AssertionError(request.url)

        self.network.stop()
        real_client = httpx.Client
        with patch(
            "studio.services.comfy.httpx.Client",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ):
            worker_tick()
            job.refresh_from_db()
            self.assertEqual(job.status, "running")
            worker_tick()
            job.refresh_from_db()
            self.assertEqual(job.status, "completed")
            with get_storage().open(job.video_key) as video:
                self.assertEqual(video.read(), b"test-video")
            worker_tick()
        self.assertEqual(sum(request.url.path == "/prompt" for request in requests), 1)

    def test_ambiguous_submission_is_not_automatically_repeated(self):
        self.submit()
        self.network.stop()
        real_client = httpx.Client
        submissions = []

        def handler(request):
            if request.url.path == "/upload/image":
                return httpx.Response(200, json={"name": "uploaded.png"})
            if request.url.path == "/prompt":
                submissions.append(request)
                raise httpx.ReadTimeout("Lost response", request=request)
            raise AssertionError(request.url)

        with patch(
            "studio.services.comfy.httpx.Client",
            side_effect=lambda **kwargs: real_client(
                transport=httpx.MockTransport(handler), **kwargs
            ),
        ):
            worker_tick()
            worker_tick()
        self.assertEqual(Generation.objects.get().status, "unknown")
        self.assertEqual(len(submissions), 1)

    def test_stale_submission_is_never_requeued(self):
        self.submit()
        Generation.objects.update(
            status="submitting", updated_at=timezone.now() - timedelta(minutes=10)
        )
        worker_tick()
        self.assertEqual(Generation.objects.get().status, "unknown")

    def test_unreachable_job_times_out_without_resubmission(self):
        self.submit()
        Generation.objects.update(
            status="running",
            comfy_id="accepted",
            submitted_at=timezone.now() - timedelta(hours=1),
        )
        with patch.object(ComfyClient, "history", side_effect=ComfyError("offline")):
            worker_tick()
        self.assertEqual(Generation.objects.get().status, "unknown")

    def test_output_requires_one_saved_video(self):
        with ComfyClient() as client:
            with self.assertRaises(GenerationError):
                client.output({"status": {"completed": True}, "outputs": {}})
            with self.assertRaises(GenerationError):
                client.output({"status": {"status_str": "error"}})

    def test_editor_layout_json_is_rejected(self):
        self.workflow.write_text(json.dumps({"nodes": []}), encoding="utf-8")
        with self.assertRaises(ComfyError):
            load_workflow()

    @skipUnless(
        importlib.util.find_spec("oci"), "Install the oracle extra to test OCI storage."
    )
    def test_oci_storage_rejects_public_bucket_and_never_returns_public_urls(self):
        fake = Mock()
        fake.get_bucket.return_value.data.public_access_type = "NoPublicAccess"
        fake.get_object.return_value.data.raw = io.BytesIO(b"private-content")
        with (
            patch.dict("os.environ", {"OCI_NAMESPACE": "ns", "OCI_BUCKET": "private"}),
            patch("oci.config.from_file", return_value={}),
            patch("oci.object_storage.ObjectStorageClient", return_value=fake),
        ):
            storage = OCIStorage()
            storage.put("a.png", io.BytesIO(b"a"), "image/png")
            self.assertEqual(storage.open("a.png").read(), b"private-content")
            fake.get_object.assert_called_with("ns", "private", "a.png")
            fake.get_bucket.return_value.data.public_access_type = "ObjectRead"
            from django.core.exceptions import ImproperlyConfigured

            with self.assertRaises(ImproperlyConfigured):
                OCIStorage()

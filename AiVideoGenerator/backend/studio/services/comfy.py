import json
import mimetypes
from pathlib import PurePosixPath
from tempfile import SpooledTemporaryFile
from urllib.parse import urlparse

import httpx
from django.conf import settings


class ComfyError(Exception):
    pass


class SubmissionUnknown(ComfyError):
    pass


class GenerationError(ComfyError):
    pass


def load_workflow():
    try:
        workflow = json.loads(settings.COMFY_WORKFLOW_PATH.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        raise ComfyError(
            "The renderer workflow is not configured yet. Contact your admin."
        ) from exc
    if (
        not isinstance(workflow, dict)
        or not workflow
        or any(
            not isinstance(node, dict) or "class_type" not in node or "inputs" not in node
            for node in workflow.values()
        )
    ):
        raise ComfyError(
            "Export the workflow in ComfyUI API format, then configure its inputs."
        )
    for node_id, input_name in [
        (settings.COMFY_IMAGE_NODE_ID, settings.COMFY_IMAGE_INPUT),
        (settings.COMFY_PROMPT_NODE_ID, settings.COMFY_PROMPT_INPUT),
    ]:
        node = workflow.get(node_id)
        if not node or input_name not in node["inputs"]:
            raise ComfyError("The renderer image or prompt input is not configured correctly.")
    if (settings.COMFY_IMAGE_NODE_ID, settings.COMFY_IMAGE_INPUT) == (
        settings.COMFY_PROMPT_NODE_ID,
        settings.COMFY_PROMPT_INPUT,
    ):
        raise ComfyError("Image and prompt must use different workflow inputs.")
    if settings.COMFY_OUTPUT_NODE_ID and settings.COMFY_OUTPUT_NODE_ID not in workflow:
        raise ComfyError("The configured output node is missing from the workflow.")
    return workflow


def configured():
    try:
        load_workflow()
        return True
    except ComfyError:
        return False


class ComfyClient:
    def __init__(self):
        if urlparse(settings.COMFY_URL).scheme not in {"http", "https"}:
            raise ComfyError("COMFY_URL must be an HTTP or HTTPS URL.")
        self.client = httpx.Client(
            base_url=settings.COMFY_URL + "/",
            timeout=httpx.Timeout(30, connect=5),
            follow_redirects=False,
            trust_env=False,
        )

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.client.close()

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, **kwargs)
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise ComfyError(
                "Cannot reach the renderer. Check ComfyUI and its connection."
            ) from exc

    def upload(self, job, storage):
        with storage.open(job.image_key) as stream:
            data = self.request(
                "POST",
                "upload/image",
                files={"image": (f"avg-{job.id}.png", stream, "image/png")},
                data={"overwrite": "false"},
            ).json()
        return str(PurePosixPath(data.get("subfolder", "")) / data["name"])

    def submit(self, job, workflow, image_name):
        workflow[settings.COMFY_IMAGE_NODE_ID]["inputs"][settings.COMFY_IMAGE_INPUT] = (
            image_name
        )
        workflow[settings.COMFY_PROMPT_NODE_ID]["inputs"][settings.COMFY_PROMPT_INPUT] = (
            job.prompt
        )
        try:
            response = self.client.post(
                "prompt",
                json={
                    "prompt": workflow,
                    "client_id": str(job.id),
                    "extra_data": {"avg_job_id": str(job.id)},
                },
            )
        except httpx.HTTPError as exc:
            raise SubmissionUnknown("Renderer acceptance is unknown. Check its queue.") from exc
        if response.status_code == 400:
            raise ComfyError("ComfyUI rejected this workflow. Check its nodes and models.")
        try:
            response.raise_for_status()
            data = response.json()
            if data.get("node_errors") or not isinstance(data.get("prompt_id"), str):
                raise ValueError("Missing acceptance ID")
            return data["prompt_id"]
        except (httpx.HTTPError, ValueError) as exc:
            raise SubmissionUnknown("Renderer acceptance is unknown. Check its queue.") from exc

    def history(self, prompt_id):
        return self.request("GET", f"history/{prompt_id}").json().get(prompt_id)

    def output(self, history):
        if history.get("status", {}).get("status_str") == "error":
            raise GenerationError(
                "Generation failed in ComfyUI. Check its log before retrying."
            )
        if not history.get("status", {}).get("completed"):
            return None
        outputs = history.get("outputs", {})
        if settings.COMFY_OUTPUT_NODE_ID:
            outputs = {
                settings.COMFY_OUTPUT_NODE_ID: outputs.get(settings.COMFY_OUTPUT_NODE_ID, {})
            }
        keys = (
            [settings.COMFY_VIDEO_OUTPUT_KEY]
            if settings.COMFY_VIDEO_OUTPUT_KEY
            else [
                "videos",
                "gifs",
                "images",
                "avg_video",
            ]
        )
        found = []
        for node in outputs.values():
            for key in keys:
                for item in node.get(key, []):
                    if not isinstance(item, dict):
                        continue
                    name = item.get("filename", "")
                    if (
                        PurePosixPath(name).suffix.lower() in {".mp4", ".webm", ".mov"}
                        and item.get("type", "output") == "output"
                    ):
                        descriptor = {
                            "filename": name,
                            "subfolder": item.get("subfolder", ""),
                            "type": "output",
                        }
                        if descriptor not in found:
                            found.append(descriptor)
        if len(found) != 1:
            raise GenerationError(
                "Expected one saved video. Configure the output node and enable video saving."
            )
        return found[0]

    def download(self, descriptor, destination):
        total = 0
        with self.client.stream("GET", "view", params=descriptor) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes(1024 * 1024):
                total += len(chunk)
                if total > settings.MAX_VIDEO_BYTES:
                    raise GenerationError("The generated video exceeds the download limit.")
                destination.write(chunk)
        if not total:
            raise GenerationError("The renderer returned an empty video.")
        destination.seek(0)

    def save_output(self, job, descriptor, storage):
        extension = PurePosixPath(descriptor["filename"]).suffix.lower()
        key = f"users/{job.conversation.owner_id}/videos/{job.id}{extension}"
        mime = mimetypes.guess_type("video" + extension)[0] or "video/mp4"
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024) as temporary:
            self.download(descriptor, temporary)
            storage.put(key, temporary, mime)
        return key, mime

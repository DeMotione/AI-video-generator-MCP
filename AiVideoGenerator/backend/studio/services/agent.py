import base64
from tempfile import SpooledTemporaryFile
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from django.conf import settings


class AgentError(Exception):
    pass


class AgentBusy(AgentError):
    pass


class RequestMissing(AgentError):
    pass


def check_configuration():
    parsed = urlsplit(settings.AGENT_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentError("Configure the video agent connection.")
    if (
        len(settings.AGENT_API_TOKEN) < 32
        or settings.AGENT_API_TOKEN == "REPLACE_WITH_A_RANDOM_TOKEN"
    ):
        raise AgentError("Configure the video agent credentials.")


class AgentClient:
    def __init__(self):
        check_configuration()
        self.client = httpx.Client(
            base_url=settings.AGENT_URL + "/",
            headers={"Authorization": f"Bearer {settings.AGENT_API_TOKEN}"},
            timeout=httpx.Timeout(150, connect=5),
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
            if response.status_code == 429:
                raise AgentBusy("The video agent is busy. Your request is waiting.")
            if response.status_code == 404:
                raise RequestMissing("The agent has no record of this request.")
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise AgentError(
                "The video agent is unavailable. Reconnecting to your request."
            ) from exc

    def state(self, response, job):
        try:
            data = response.json()
            if data["request_id"] != str(job.pk) or data["status"] not in {
                "planning",
                "submitting",
                "running",
                "completed",
                "failed",
                "cancelled",
                "unknown",
            }:
                raise ValueError("Invalid request state")
            if data.get("job_id"):
                data["job_id"] = str(UUID(data["job_id"]))
            if data["status"] == "completed" and not data.get("job_id"):
                raise ValueError("Missing video job ID")
            return data
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentError("The video agent returned an invalid request record.") from exc

    def submit(self, job, storage):
        with storage.open(job.image_key) as image:
            content = image.read(10 * 1024 * 1024 + 1)
        if len(content) > 10 * 1024 * 1024:
            raise AgentError("The normalized image exceeds the agent's 10 MiB limit.")
        response = self.request(
            "POST",
            "jobs",
            timeout=30,
            json={
                "request_id": str(job.pk),
                "prompt": job.prompt,
                "image_base64": base64.b64encode(content).decode(),
            },
        )
        return self.state(response, job)

    def status(self, job):
        return self.state(self.request("GET", f"jobs/{job.pk}"), job)

    def save_output(self, job, storage):
        key = f"users/{job.conversation.owner_id}/videos/{job.pk}.mp4"
        with SpooledTemporaryFile(max_size=8 * 1024 * 1024) as temporary:
            try:
                total = 0
                with self.client.stream("GET", f"jobs/{job.pk}/video") as response:
                    response.raise_for_status()
                    for chunk in response.iter_bytes(1024 * 1024):
                        total += len(chunk)
                        if total > settings.MAX_VIDEO_BYTES:
                            raise AgentError("The generated video exceeds the download limit.")
                        temporary.write(chunk)
                if not total:
                    raise AgentError("The video agent returned an empty video.")
                temporary.seek(0)
                storage.put(key, temporary, "video/mp4")
            except httpx.HTTPError as exc:
                raise AgentError(
                    "Could not retrieve the video yet. The worker will try again."
                ) from exc
        return key

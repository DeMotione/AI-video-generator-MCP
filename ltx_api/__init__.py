import base64
import hashlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

import folder_paths
import numpy as np
from aiohttp import web
from PIL import Image
from server import PromptServer


PRESET = "ltx25-fast-5s-16x9-v1"


def api_key():
    value = os.getenv("LTX_API_KEY", "").strip()
    key_file = Path(__file__).with_name("ltx_api_key.txt")
    if not value and key_file.is_file():
        value = key_file.read_text().strip()
    return value


def readiness():
    missing = []
    if not api_key():
        missing.append("LTX_API_KEY or ltx_api_key.txt")
    for executable in ("ffmpeg", "ffprobe"):
        if not shutil.which(executable):
            missing.append(executable)
    return {
        "ready": not missing,
        "missing": missing,
        "preset": PRESET,
    }


@PromptServer.instance.routes.get("/avg/health")
async def health(request):
    return web.json_response(readiness())


def api_request(method, path, payload=None):
    request = Request(
        f"https://api.ltx.io{path}",
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {api_key()}",
            "Content-Type": "application/json",
        },
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def save_state(path, state):
    temporary = path.with_name(f"{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(state))
    temporary.replace(path)


def video_result(identifier, path):
    return {
        "ui": {
            "avg_video": [{
                "filename": f"{identifier}.mp4",
                "subfolder": "avg",
                "type": "output",
            }]
        },
        "result": (str(path),),
    }


class AVGLTX25:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),
                "prompt": ("STRING", {"multiline": True}),
                "request_id": ("STRING", {"default": ""}),
            }
        }

    RETURN_TYPES = ("STRING",)
    RETURN_NAMES = ("video_path",)
    FUNCTION = "generate"
    CATEGORY = "AVG"
    OUTPUT_NODE = True

    @classmethod
    def IS_CHANGED(cls, **kwargs):
        return float("nan")

    def generate(self, image, prompt, request_id):
        available = readiness()
        if not available["ready"]:
            raise RuntimeError(f"Missing: {available['missing']}")

        prompt = prompt.strip()
        if not 1 <= len(prompt) <= 2000:
            raise ValueError("Prompt must contain 1–2000 characters.")

        if image.ndim != 4 or image.shape[0] != 1:
            raise ValueError("Exactly one image is required.")

        _, height, width, channels = image.shape
        if (
            channels != 3
            or width < 320
            or height < 180
            or max(width, height) > 4096
            or width * 9 != height * 16
        ):
            raise ValueError("Use a static 16:9 image, 320×180 to 4096px.")

        pixels = np.clip(
            image[0].detach().cpu().numpy() * 255, 0, 255
        ).astype(np.uint8)

        buffer = io.BytesIO()
        Image.fromarray(pixels).resize(
            (1280, 720), Image.Resampling.LANCZOS
        ).save(buffer, format="JPEG", quality=90)

        encoded = base64.b64encode(buffer.getvalue()).decode()
        if len(encoded) > 7 * 1024 * 1024:
            raise ValueError("Encoded image exceeds the LTX input limit.")

        payload = {
            "model": "ltx-2-5-fast",
            "image_uri": f"data:image/jpeg;base64,{encoded}",
            "prompt": prompt,
            "duration": 6,
            "resolution": "1280x720",
            "fps": 24,
            "generate_audio": False,
        }

        identifier = str(UUID(request_id)) if request_id else str(uuid4())
        directory = Path(folder_paths.get_output_directory()) / "avg"
        directory.mkdir(parents=True, exist_ok=True)
        output = directory / f"{identifier}.mp4"
        journal = directory / f"{identifier}.json"
        fingerprint = hashlib.sha256(
            json.dumps(payload, sort_keys=True).encode()
        ).hexdigest()

        if journal.is_file():
            state = json.loads(journal.read_text())
            if state["fingerprint"] != fingerprint:
                raise ValueError("Request ID was reused with different inputs.")
        else:
            state = {"fingerprint": fingerprint, "provider_id": None}
            with journal.open("x") as stream:
                json.dump(state, stream)
            try:
                submitted = api_request(
                    "POST", "/v2/image-to-video", payload
                )
                state["provider_id"] = submitted["id"]
                save_state(journal, state)
            except Exception as exc:
                raise RuntimeError(
                    "LTX submission outcome is unresolved. Check the LTX "
                    "console before creating another request."
                ) from exc

        if output.is_file():
            return video_result(identifier, output)

        if not state["provider_id"]:
            raise RuntimeError(
                "Previous submission outcome is unknown. Check the LTX console."
            )

        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            try:
                job = api_request(
                    "GET",
                    f"/v2/image-to-video/{state['provider_id']}",
                )
            except HTTPError as exc:
                if exc.code != 429 and exc.code < 500:
                    raise RuntimeError(f"LTX status HTTP {exc.code}") from exc
                time.sleep(5)
                continue
            except URLError:
                time.sleep(5)
                continue

            if job["status"] == "failed":
                raise RuntimeError(
                    "LTX generation failed. Check the developer console."
                )
            if job["status"] == "completed":
                break
            time.sleep(5)
        else:
            raise RuntimeError(
                "Polling timed out; the provider job may still be running."
            )

        video_url = job["result"]["video_url"]
        if not video_url.startswith("https://"):
            raise RuntimeError("LTX returned an unsupported output URL.")

        with tempfile.TemporaryDirectory(dir=directory) as temporary:
            source = Path(temporary) / "source.mp4"
            trimmed = Path(temporary) / "trimmed.mp4"

            with urlopen(video_url, timeout=60) as response:
                with source.open("wb") as stream:
                    total = 0
                    while chunk := response.read(1024 * 1024):
                        total += len(chunk)
                        if total > 100 * 1024 * 1024:
                            raise RuntimeError("Video exceeds 100 MiB.")
                        stream.write(chunk)

            subprocess.run(
                [
                    shutil.which("ffmpeg"),
                    "-y", "-hide_banner", "-loglevel", "error",
                    "-i", str(source),
                    "-map", "0:v:0",
                    "-vf", "fps=24,scale=1280:720,setsar=1",
                    "-frames:v", "120",
                    "-an",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(trimmed),
                ],
                check=True,
                capture_output=True,
                timeout=180,
            )

            probe = subprocess.run(
                [
                    shutil.which("ffprobe"),
                    "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries",
                    "stream=width,height,nb_frames:format=duration",
                    "-of", "json",
                    str(trimmed),
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            metadata = json.loads(probe.stdout)
            video = metadata["streams"][0]
            if (
                video["width"] != 1280
                or video["height"] != 720
                or int(video["nb_frames"]) != 120
                or abs(float(metadata["format"]["duration"]) - 5) > 0.01
            ):
                raise RuntimeError("Output does not match the five-second preset.")

            trimmed.replace(output)

        return video_result(identifier, output)


NODE_CLASS_MAPPINGS = {"AVG_LTX25": AVGLTX25}
NODE_DISPLAY_NAME_MAPPINGS = {
    "AVG_LTX25": "AVG · LTX 2.5 · 5 seconds"
}
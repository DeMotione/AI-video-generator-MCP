import argparse
import base64
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from dotenv import load_dotenv

load_dotenv(Path(__file__).with_name(".env"), override=False)
parser = argparse.ArgumentParser()
parser.add_argument("--prompt", help="Also run one chat request after readiness succeeds.")
parser.add_argument("--image", type=Path, help="Optional image, used with --prompt.")
arguments = parser.parse_args()
token = os.getenv("AGENT_API_TOKEN", "")
if not token or token == "REPLACE_WITH_A_RANDOM_TOKEN":
    sys.exit("Set AGENT_API_TOKEN in .env first.")
if arguments.image and not arguments.prompt:
    sys.exit("--image requires --prompt.")


def request(path, payload=None, timeout=35):
    body = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    outgoing = Request(f"http://127.0.0.1:8100{path}", data=body, headers=headers)
    try:
        with urlopen(outgoing, timeout=timeout) as response:
            result = json.load(response)
    except HTTPError as exc:
        print(f"HTTP {exc.code}: {exc.read().decode()}")
        sys.exit(1)
    except (URLError, TimeoutError) as exc:
        sys.exit(f"Agent connection failed: {exc}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


request("/healthz")
request("/readyz")
if arguments.prompt:
    payload = {"prompt": arguments.prompt}
    if arguments.image:
        payload["image_base64"] = base64.b64encode(arguments.image.read_bytes()).decode()
    result = request(
        "/chat", payload, timeout=float(os.getenv("AGENT_REQUEST_TIMEOUT_SECONDS", "900")) + 30
    )
    if result.get("status") != "answered":
        sys.exit(1)

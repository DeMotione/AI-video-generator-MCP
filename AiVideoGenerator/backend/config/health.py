"""Readiness checks only local dependencies; never invoke paid generation."""

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError

import httpx
from django.conf import settings
from django.db import connections
from django.http import JsonResponse
from django.views.decorators.http import require_GET

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="readiness")
_lock = threading.Lock()
_pending = None


def dependencies_ready():
    try:
        with connections["default"].cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM DUAL" if settings.DB_BACKEND == "oracle" else "SELECT 1"
            )
            cursor.fetchone()
        if settings.APP_ENV == "production":
            heartbeat = json.loads(settings.WORKER_HEARTBEAT.read_text())
            if (
                time.time() - heartbeat["time"] > 120
                or heartbeat["release"] != settings.RELEASE_SHA
            ):
                return False
        if settings.GENERATION_BACKEND == "agent":
            with httpx.Client(timeout=2, trust_env=False, follow_redirects=False) as client:
                response = client.get(settings.AGENT_URL + "/healthz")
                if response.status_code != 200 or response.json().get("status") != "running":
                    return False
        return True
    except Exception:
        return False
    finally:
        connections.close_all()


@require_GET
def live(request):
    return JsonResponse({"status": "running", "release": settings.RELEASE_SHA})


@require_GET
def ready(request):
    global _pending
    # At most one probe per process, even when a database connection hangs.
    with _lock:
        if _pending is None or _pending.done():
            _pending = _executor.submit(dependencies_ready)
        pending = _pending
    try:
        healthy = pending.result(timeout=4)
    except TimeoutError:
        healthy = False
    response = JsonResponse(
        {"status": "ready" if healthy else "not_ready", "release": settings.RELEASE_SHA},
        status=200 if healthy else 503,
    )
    response["Cache-Control"] = "no-store"
    return response

import logging
import re
from functools import wraps
from uuid import UUID

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .models import Conversation, Generation
from .services.comfy import ComfyError, configured, load_workflow
from .services.images import normalize_image
from .services.storage import get_storage

logger = logging.getLogger(__name__)


def authenticated_api(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse(
                {"error": "Your session has ended. Please log in again."}, status=401
            )
        return view(request, *args, **kwargs)

    return never_cache(wrapped)


def job_data(job):
    return {
        "id": str(job.id),
        "prompt": job.prompt,
        "status": job.status,
        "label": job.get_status_display(),
        "message": job.message,
        "image_name": job.image_name,
        "image_url": reverse("studio:media", args=[job.id, "image"]),
        "video_url": reverse("studio:media", args=[job.id, "video"]) if job.video_key else None,
        "created_at": job.created_at.isoformat(),
    }


@never_cache
@login_required
def home(request):
    return render(
        request,
        "studio/chat.html",
        {
            "workflow_ready": configured(),
            "max_image_mb": settings.MAX_IMAGE_BYTES // 1048576,
        },
    )


@authenticated_api
@require_GET
def conversations(request):
    rows = Conversation.objects.filter(owner=request.user)[:100]
    return JsonResponse(
        {
            "conversations": [
                {
                    "id": str(row.id),
                    "title": row.title,
                    "updated_at": row.updated_at.isoformat(),
                }
                for row in rows
            ]
        }
    )


@authenticated_api
@require_POST
def new_conversation(request):
    conversation = Conversation.objects.create(owner=request.user)
    return JsonResponse({"id": str(conversation.id), "title": conversation.title}, status=201)


@authenticated_api
@require_GET
def conversation_detail(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id, owner=request.user)
    return JsonResponse(
        {
            "id": str(conversation.id),
            "title": conversation.title,
            "generations": [job_data(job) for job in conversation.generations.all()],
        }
    )


@authenticated_api
@require_POST
def generate(request, conversation_id):
    conversation = get_object_or_404(Conversation, pk=conversation_id, owner=request.user)
    try:
        identifier = UUID(request.POST.get("request_id", ""))
    except (ValueError, AttributeError):
        return JsonResponse(
            {"error": "Invalid request ID. Please refresh the page."}, status=400
        )
    existing = Generation.objects.filter(pk=identifier).first()
    if existing:
        if existing.conversation_id != conversation.id:
            return JsonResponse({"error": "Request ID already used."}, status=409)
        return JsonResponse(job_data(existing))
    prompt = request.POST.get("prompt", "").strip()
    if not 1 <= len(prompt) <= 2000:
        return JsonResponse(
            {"error": "Write a prompt between 1 and 2,000 characters."}, status=400
        )
    upload = request.FILES.get("image")
    if not upload:
        return JsonResponse(
            {"error": "Attach or paste an image to start your video."}, status=400
        )
    try:
        load_workflow()
        normalized, width, height = normalize_image(upload)
    except (ComfyError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    key = f"users/{request.user.pk}/images/{identifier}.png"
    stored = False
    try:
        with transaction.atomic():
            conversation = Conversation.objects.select_for_update().get(pk=conversation.pk)
            existing = Generation.objects.filter(pk=identifier).first()
            if existing:
                if existing.conversation_id != conversation.id:
                    return JsonResponse({"error": "Request ID already used."}, status=409)
                return JsonResponse(job_data(existing))
            active = Generation.objects.filter(
                conversation__owner=request.user,
                status__in=[
                    Generation.Status.QUEUED,
                    Generation.Status.SUBMITTING,
                    Generation.Status.RUNNING,
                ],
            ).count()
            if active >= 3:
                return JsonResponse(
                    {"error": "You already have three videos in progress."}, status=429
                )
            job = Generation.objects.create(
                id=identifier,
                conversation=conversation,
                prompt=prompt,
                image_key=key,
                image_name=upload.name[:150],
                image_width=width,
                image_height=height,
                message="Waiting for the video worker.",
            )
            storage = get_storage()
            storage.put(key, normalized, "image/png")
            stored = True
            if conversation.title == "Untitled creation":
                conversation.title = prompt[:80]
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=["title", "updated_at"])
    except IntegrityError:
        return JsonResponse(
            {"error": "This request is already being saved. Try again."}, status=409
        )
    except Exception:
        logger.exception("Could not store generation %s", identifier)
        if stored:
            try:
                storage.delete(key)
            except Exception:
                logger.exception("Could not clean up unused upload %s", identifier)
        return JsonResponse(
            {"error": "Could not save your image. Please try again."}, status=503
        )
    finally:
        normalized.close()
    return JsonResponse(job_data(job), status=201)


def read_chunks(stream, remaining):
    try:
        while remaining:
            chunk = stream.read(min(65536, remaining))
            if not chunk:
                break
            remaining -= len(chunk)
            yield chunk
    finally:
        stream.close()


@authenticated_api
@require_GET
def media(request, job_id, kind):
    job = get_object_or_404(Generation, pk=job_id, conversation__owner=request.user)
    key = job.image_key if kind == "image" else job.video_key if kind == "video" else ""
    if not key or (kind == "video" and job.status != Generation.Status.COMPLETED):
        return HttpResponse(status=404)
    try:
        storage = get_storage()
        size = storage.size(key)
        start, end, status = 0, size - 1, 200
        requested = request.headers.get("Range")
        if requested:
            match = re.fullmatch(r"bytes=(\d*)-(\d*)", requested)
            if not match or not any(match.groups()):
                return HttpResponse(status=416, headers={"Content-Range": f"bytes */{size}"})
            first, last = match.groups()
            if first:
                start = int(first)
                end = min(int(last), size - 1) if last else size - 1
            else:
                start = max(0, size - int(last))
            if start > end or start >= size:
                return HttpResponse(status=416, headers={"Content-Range": f"bytes */{size}"})
            status = 206
        stream = storage.open(key, start=start, end=end)
    except Exception:
        logger.exception("Could not read private media for job %s", job_id)
        return JsonResponse({"error": "This file is temporarily unavailable."}, status=503)
    response = StreamingHttpResponse(
        read_chunks(stream, end - start + 1),
        status=status,
        content_type="image/png" if kind == "image" else job.video_mime,
    )
    response["Content-Length"] = str(end - start + 1)
    response["Accept-Ranges"] = "bytes"
    response["Cache-Control"] = "private, no-store"
    if status == 206:
        response["Content-Range"] = f"bytes {start}-{end}/{size}"
    if kind == "video":
        extension = key.rsplit(".", 1)[-1]
        disposition = "attachment" if request.GET.get("download") == "1" else "inline"
        response["Content-Disposition"] = f'{disposition}; filename="{job.id}.{extension}"'
    return response

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from studio.models import Generation

from .comfy import ComfyClient, ComfyError, GenerationError, SubmissionUnknown, load_workflow
from .storage import get_storage

logger = logging.getLogger(__name__)


def update(job, **fields):
    fields["updated_at"] = timezone.now()
    Generation.objects.filter(pk=job.pk).update(**fields)


def submit_job(job):
    try:
        workflow = load_workflow()
        storage = get_storage()
        with ComfyClient() as client:
            image_name = client.upload(job, storage)
            accepted = client.submit(job, workflow, image_name)
            update(
                job,
                status=Generation.Status.RUNNING,
                comfy_id=accepted,
                submitted_at=timezone.now(),
                message="Your video is rendering.",
            )
    except SubmissionUnknown as exc:
        update(job, status=Generation.Status.UNKNOWN, message=str(exc))
    except ComfyError as exc:
        update(job, status=Generation.Status.FAILED, message=str(exc))
    except Exception:
        logger.exception("Submission stopped for job %s", job.pk)
        update(
            job,
            status=Generation.Status.UNKNOWN,
            message="Submission was interrupted. Ask your admin to check the renderer queue.",
        )


def poll_job(job):
    try:
        with ComfyClient() as client:
            history = client.history(job.comfy_id)
            if history:
                output = client.output(history)
                if output:
                    key, mime = client.save_output(job, output, get_storage())
                    update(
                        job,
                        status=Generation.Status.COMPLETED,
                        video_key=key,
                        video_mime=mime,
                        message="Your video is ready.",
                    )
                    return
    except GenerationError as exc:
        update(job, status=Generation.Status.FAILED, message=str(exc))
        return
    except ComfyError:
        update(job, message="Renderer unavailable. Reconnecting without submitting again.")
    except Exception:
        logger.exception("Polling failed for job %s; no generation resubmitted", job.pk)
        update(job, message="Could not retrieve the result yet. The worker will try again.")
    if job.submitted_at and (timezone.now() - job.submitted_at).total_seconds() > (
        settings.COMFY_JOB_TIMEOUT_SECONDS
    ):
        update(
            job,
            status=Generation.Status.UNKNOWN,
            message="The renderer is taking longer than expected. Ask your admin to "
            "check the job; it may still be running.",
        )


def worker_tick():
    stale = timezone.now() - timedelta(minutes=5)
    Generation.objects.filter(status=Generation.Status.SUBMITTING, updated_at__lt=stale).update(
        status=Generation.Status.UNKNOWN,
        message="Submission was interrupted. Check ComfyUI before starting another generation.",
        updated_at=timezone.now(),
    )
    for job in Generation.objects.filter(status=Generation.Status.RUNNING).select_related(
        "conversation"
    ):
        poll_job(job)
    job = Generation.objects.filter(status=Generation.Status.QUEUED).first()
    if job and Generation.objects.filter(pk=job.pk, status=Generation.Status.QUEUED).update(
        status=Generation.Status.SUBMITTING, updated_at=timezone.now()
    ):
        submit_job(job)

import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from studio.models import Generation

from .agent import AgentBusy, AgentClient, AgentError, RequestMissing
from .comfy import ComfyClient, ComfyError, GenerationError, SubmissionUnknown, load_workflow
from .storage import get_storage

logger = logging.getLogger(__name__)


def update(job, **fields):
    fields["updated_at"] = timezone.now()
    Generation.objects.filter(pk=job.pk).update(**fields)


def submit_job(job):
    if job.backend == "agent":
        submit_agent_job(job)
        return
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
    if job.backend == "agent":
        poll_agent_job(job)
        return
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


def apply_agent_state(job, client, data):
    fields = {
        "remote_job_id": data.get("job_id") or "",
        "message": data.get("message", "")[:500],
    }
    state = data["status"]
    if state == "completed":
        fields.update(
            status=Generation.Status.COMPLETED,
            video_key=client.save_output(job, get_storage()),
            video_mime="video/mp4",
        )
    elif state in {"failed", "cancelled"}:
        fields["status"] = Generation.Status.FAILED
    elif state == "unknown":
        fields["status"] = Generation.Status.UNKNOWN
    else:
        fields["status"] = Generation.Status.RUNNING
    update(job, **fields)


def submit_agent_job(job):
    try:
        with AgentClient() as client:
            apply_agent_state(job, client, client.submit(job, get_storage()))
    except AgentBusy as exc:
        update(job, status=Generation.Status.QUEUED, message=str(exc))
    except AgentError as exc:
        # The response may have been lost after acceptance. Reconcile using
        # the same request ID; never create a replacement request.
        update(job, message=str(exc))
    except Exception:
        logger.exception("Agent submission interrupted for job %s", job.pk)
        update(job, message="Checking whether the video agent accepted your request.")


def poll_agent_job(job):
    try:
        with AgentClient() as client:
            try:
                data = client.status(job)
            except RequestMissing:
                if job.status != Generation.Status.SUBMITTING:
                    update(
                        job,
                        status=Generation.Status.UNKNOWN,
                        message="Request record missing. Check the VM before retrying.",
                    )
                    return
                data = client.submit(job, get_storage())
            apply_agent_state(job, client, data)
    except AgentBusy as exc:
        update(job, status=Generation.Status.QUEUED, message=str(exc))
    except AgentError as exc:
        update(job, message=str(exc))
    except Exception:
        logger.exception("Agent polling failed for job %s", job.pk)
        update(job, message="Could not retrieve your video yet. The worker will try again.")
    if (
        job.submitted_at
        and (timezone.now() - job.submitted_at).total_seconds()
        > settings.AGENT_JOB_TIMEOUT_SECONDS
    ):
        # Keep accepted jobs recoverable; do not turn a slow render into a resubmission.
        Generation.objects.filter(
            pk=job.pk, status__in=[Generation.Status.SUBMITTING, Generation.Status.RUNNING]
        ).update(
            message="Your video is taking longer than expected. Checking the same request."
        )


def worker_tick():
    stale = timezone.now() - timedelta(minutes=5)
    Generation.objects.filter(
        backend="comfy", status=Generation.Status.SUBMITTING, updated_at__lt=stale
    ).update(
        status=Generation.Status.UNKNOWN,
        message="Submission was interrupted. Check ComfyUI before starting another generation.",
        updated_at=timezone.now(),
    )
    for job in Generation.objects.filter(status=Generation.Status.RUNNING).select_related(
        "conversation"
    ):
        poll_job(job)
    for job in Generation.objects.filter(
        backend="agent", status=Generation.Status.SUBMITTING
    ).select_related("conversation"):
        poll_agent_job(job)
    job = Generation.objects.filter(status=Generation.Status.QUEUED).first()
    if (
        job
        and job.backend == "agent"
        and Generation.objects.filter(
            backend="agent",
            status__in=[Generation.Status.SUBMITTING, Generation.Status.RUNNING],
        ).exists()
    ):
        return
    if job and Generation.objects.filter(pk=job.pk, status=Generation.Status.QUEUED).update(
        status=Generation.Status.SUBMITTING,
        updated_at=timezone.now(),
        submitted_at=timezone.now(),
    ):
        job.status = Generation.Status.SUBMITTING
        submit_job(job)

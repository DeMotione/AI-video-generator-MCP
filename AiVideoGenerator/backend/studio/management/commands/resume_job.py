from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from studio.models import Generation
from studio.services.comfy import ComfyClient, ComfyError


class Command(BaseCommand):
    help = "Resume polling an uncertain job using an already accepted ComfyUI prompt ID."

    def add_arguments(self, parser):
        parser.add_argument("job_id")
        parser.add_argument("--comfy-id", required=True)

    def handle(self, *args, **options):
        try:
            job = Generation.objects.get(pk=options["job_id"])
        except (Generation.DoesNotExist, ValueError) as exc:
            raise CommandError("Unknown job ID.") from exc
        if job.status != Generation.Status.UNKNOWN:
            raise CommandError("Only jobs with unknown status can be resumed.")
        comfy_id = options["comfy_id"]
        try:
            with ComfyClient() as client:
                history = client.history(comfy_id)
                queue = client.request("GET", "queue").json()
            candidates = queue.get("queue_running", []) + queue.get("queue_pending", [])
            if history:
                candidates.append(history.get("prompt", []))
            matched = any(
                len(row) > 3
                and row[1] == comfy_id
                and isinstance(row[3], dict)
                and row[3].get("avg_job_id") == str(job.id)
                for row in candidates
            )
            if not matched:
                raise CommandError("No queue/history entry matches both IDs. No changes made.")
        except ComfyError as exc:
            raise CommandError(str(exc)) from exc
        job.comfy_id = comfy_id
        job.status = Generation.Status.RUNNING
        job.submitted_at = timezone.now()
        job.message = "Resuming result retrieval. No new render was submitted."
        job.save()
        self.stdout.write(self.style.SUCCESS("Polling resumed. No new render was submitted."))

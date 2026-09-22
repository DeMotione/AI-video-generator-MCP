from django.core.management.base import BaseCommand, CommandError

from studio.services.comfy import ComfyClient, ComfyError, load_workflow


class Command(BaseCommand):
    help = "Check the workflow and ComfyUI connection without generating a video."

    def handle(self, *args, **options):
        try:
            workflow = load_workflow()
            with ComfyClient() as client:
                client.request("GET", "system_stats")
                available = client.request("GET", "object_info").json()
            missing = sorted(
                {node["class_type"] for node in workflow.values()} - available.keys()
            )
            if missing:
                raise CommandError("Missing ComfyUI nodes: " + ", ".join(missing))
        except ComfyError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                "ComfyUI is reachable. Inputs are mapped and node types are installed. "
                "No video was generated."
            )
        )

import json
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import close_old_connections

from studio.services.jobs import worker_tick


class Command(BaseCommand):
    help = "Run the local video queue worker. Keep this terminal open alongside runserver."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        self.stdout.write("Video worker running. Ctrl+C to stop.")
        try:
            while True:
                close_old_connections()
                temporary = settings.WORKER_HEARTBEAT.with_suffix(".tmp")
                temporary.write_text(
                    json.dumps({"time": time.time(), "release": settings.RELEASE_SHA})
                )
                temporary.replace(settings.WORKER_HEARTBEAT)
                worker_tick()
                if options["once"]:
                    break
                time.sleep(settings.COMFY_POLL_SECONDS)
        except KeyboardInterrupt:
            self.stdout.write("Worker stopped. Accepted jobs will resume polling on restart.")

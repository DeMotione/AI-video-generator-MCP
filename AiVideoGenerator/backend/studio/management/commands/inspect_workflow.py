import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "List node IDs and input names in your exported ComfyUI API workflow."

    def add_arguments(self, parser):
        parser.add_argument("path")

    def handle(self, *args, **options):
        try:
            workflow = json.loads(Path(options["path"]).read_text(encoding="utf-8-sig"))
            if not isinstance(workflow, dict) or any(
                not isinstance(node, dict) or "class_type" not in node
                for node in workflow.values()
            ):
                raise ValueError("Use an API-format export, not the editor layout JSON.")
            for identifier, node in workflow.items():
                title = node.get("_meta", {}).get("title", "")
                inputs = ", ".join(node.get("inputs", {}).keys())
                self.stdout.write(
                    f"{identifier}: {node['class_type']} ({title}) | inputs: {inputs}"
                )
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

from django.conf import settings

from .agent import AgentError, check_configuration
from .comfy import ComfyError, load_workflow


def validate_renderer():
    if settings.GENERATION_BACKEND == "agent":
        check_configuration()
    else:
        load_workflow()


def configured():
    try:
        validate_renderer()
        return True
    except (AgentError, ComfyError):
        return False

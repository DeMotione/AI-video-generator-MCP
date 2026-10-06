"""One configuration loader; production receives its values from systemd."""

import os
from pathlib import Path

from django.core.exceptions import ImproperlyConfigured
from dotenv import dotenv_values


def load_configuration(repository_root: Path):
    # Select mode before consulting any local file. A local override cannot
    # turn production into development or replace an injected secret.
    mode = os.environ.get("APP_ENV", "development")
    if mode not in {"development", "production"}:
        raise ImproperlyConfigured("APP_ENV must be development or production.")
    values = {}
    if mode == "development" and os.environ.get("PYTHON_DOTENV_DISABLED") != "1":
        for name in (".env.defaults", ".env", ".env.local"):
            path = repository_root / name
            if path.is_file():
                values.update(
                    {
                        k: v
                        for k, v in dotenv_values(path, interpolate=False).items()
                        if v is not None
                    }
                )
    values.update(os.environ)
    values["APP_ENV"] = mode
    # Existing OCI storage code also consumes os.environ. Use the same merged
    # values there, without replacing any exported process value.
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return mode, values

#!/usr/bin/env python3
"""Database-specific pre-migration backup gate; no automatic live restore."""

import datetime
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path.cwd() / "AiVideoGenerator" / "backend"))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402

destination = Path(sys.argv[1]).resolve()
destination.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%dT%H%M%S%fZ")
if settings.DB_BACKEND == "sqlite":
    source = Path(settings.DATABASES["default"]["NAME"])
    if source.exists():
        with sqlite3.connect(source) as origin:
            with sqlite3.connect(destination / f"web-{stamp}.sqlite3") as backup:
                origin.backup(backup)
                if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise SystemExit("SQLite backup integrity check failed.")
        print("Pre-migration SQLite snapshot completed.")
    else:
        print("First deployment: no existing SQLite database to back up.")
else:
    hook = Path("/etc/aivideo/oracle-backup")
    if not hook.is_file() or hook.stat().st_uid != 0 or hook.stat().st_mode & 0o022:
        raise SystemExit("Install a root-owned /etc/aivideo/oracle-backup recovery hook first.")
    subprocess.run([str(hook), str(destination)], check=True, timeout=900)

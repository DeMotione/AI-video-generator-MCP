#!/usr/bin/env bash
set -euo pipefail
release=$(cd "$(dirname "$0")/../../.." && pwd -P)
export RELEASE_SHA
export APP_ENV=production PYTHON_DOTENV_DISABLED=1 PYTHONDONTWRITEBYTECODE=1
RELEASE_SHA=$(cat "$release/.release-sha")
cd "$release/AiVideoGenerator/backend"
exec "$release/AiVideoGenerator/.venv/bin/python" manage.py runworker

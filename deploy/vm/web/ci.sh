#!/usr/bin/env bash
# All checks use disposable local state and no developer/production secret files.
set -euo pipefail
root=$(cd "$(dirname "$0")/../../.." && pwd)
cd "$root"
export APP_ENV=development PYTHON_DOTENV_DISABLED=1 DJANGO_DEBUG=true
export DB_BACKEND=sqlite STORAGE_BACKEND=local GENERATION_BACKEND=agent
export DJANGO_RUNTIME_ROOT
DJANGO_RUNTIME_ROOT=$(mktemp -d)
trap 'rm -rf "$DJANGO_RUNTIME_ROOT"' EXIT
export DJANGO_SECRET_KEY=isolated-ci-development-key-not-used-in-production
export DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,testserver
export AGENT_URL=http://127.0.0.1:8100 AGENT_API_TOKEN=ci-placeholder-not-a-live-token-0000000000
uv sync --project AiVideoGenerator --locked --python 3.12
uv run --project AiVideoGenerator --no-sync ruff check \
    --config AiVideoGenerator/pyproject.toml AiVideoGenerator/backend deploy/vm/web
python="$root/AiVideoGenerator/.venv/bin/python"
"$python" AiVideoGenerator/backend/manage.py check
"$python" AiVideoGenerator/backend/manage.py makemigrations --check --dry-run
"$python" AiVideoGenerator/backend/manage.py test studio accounts
"$python" AiVideoGenerator/backend/manage.py collectstatic --noinput
export APP_ENV=production DJANGO_DEBUG=false DJANGO_HTTPS_ENABLED=true
export DJANGO_SECRET_KEY=isolated-ci-production-check-secret-00000000000000000000000000000000
export DJANGO_ALLOWED_HOSTS=ci.example.com DJANGO_CSRF_TRUSTED_ORIGINS=https://ci.example.com
"$python" AiVideoGenerator/backend/manage.py check --deploy --fail-level WARNING
for script in deploy/vm/web/*.sh; do bash -n "$script"; done
# Exercise code recovery using temporary release folders and mocked services.
# Only functions are loaded; never source the VM's production configuration.
(
    fixture=$(mktemp -d)
    trap 'rm -rf "$fixture"' EXIT
    DEPLOY_ROOT=$fixture
    eval "$(sed -n '/^validate_sha()/,$p' deploy/vm/web/release-common.sh)"
    first=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
    second=bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb
    mkdir -p "$fixture/releases/$first" "$fixture/releases/$second"
    sudo() { return 0; }
    restart_services() { return 0; }
    probe_release() { [[ $1 == "$first" ]]; }
    link_current "$fixture/releases/$second"
    restore_release "$fixture/releases/$first"
    [[ $(readlink -f "$fixture/current") == "$fixture/releases/$first" ]]
    if restore_release ""; then exit 1; fi
    if release_path ../../escape; then exit 1; fi
)

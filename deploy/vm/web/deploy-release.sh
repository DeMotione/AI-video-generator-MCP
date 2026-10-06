#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "$0")/release-common.sh"
sha=${1:?usage: deploy-release.sh EXACT_COMMIT_SHA}
validate_sha "$sha" || { echo 'A full lowercase commit SHA is required.' >&2; exit 1; }
uv=/home/aivideo-deploy/.local/bin/uv
[[ -x $uv && -r $CONFIG_FILE ]] || { echo 'Complete uv and production configuration setup.' >&2; exit 1; }
repo="$DEPLOY_ROOT/repository.git"
if [[ ! -d $repo ]]; then
    git init --bare "$repo"
    git --git-dir="$repo" remote add origin "$REPOSITORY"
fi
[[ ! -L $repo && $(realpath "$repo") == "$repo" ]] || exit 1
[[ $(git --git-dir="$repo" remote get-url origin) == "$REPOSITORY" ]] || {
    echo 'Repository origin differs from the administrator-configured source.' >&2; exit 1;
}
git --git-dir="$repo" fetch --prune origin '+refs/heads/main:refs/remotes/origin/main'
git --git-dir="$repo" merge-base --is-ancestor "$sha" refs/remotes/origin/main || {
    echo 'Commit is not a member of origin/main.' >&2; exit 1;
}
head=$(git --git-dir="$repo" rev-parse refs/remotes/origin/main)
if [[ $head != "$sha" ]]; then
    echo "Superseded commit $sha skipped. Current main $head must pass its own CI."
    exit 0
fi
previous=$(readlink -f "$DEPLOY_ROOT/current" || true)
if [[ -n $previous && -d $previous ]]; then
    release_path "$(basename "$previous")" >/dev/null || exit 1
else
    previous=''
fi
release="$DEPLOY_ROOT/releases/$sha"
if [[ $previous == "$release" ]]; then
    if ! probe_release "$sha"; then
        restart_services
        probe_release "$sha"
    fi
    echo "Commit $sha is already active and ready."
    exit 0
fi
if [[ -e $release ]]; then
    release_path "$sha" >/dev/null || exit 1
    [[ $(cat "$release/.release-sha") == "$sha" ]] || exit 1
else
    mkdir "$release"
    git --git-dir="$repo" archive "$sha" | tar -x -C "$release"
    printf '%s\n' "$sha" > "$release/.release-sha"
fi
cd "$release"
export RELEASE_SHA="$sha" APP_ENV=production PYTHON_DOTENV_DISABLED=1
export DJANGO_SETTINGS_MODULE=config.settings
export PYTHONPATH="$release/AiVideoGenerator/backend"
# The app account cannot traverse the deploy user's home. Install interpreters
# outside that home, then build the venv in its final release directory.
export UV_PYTHON_INSTALL_DIR="$DEPLOY_ROOT/tools/python"
run_config() { (trap - ERR; umask 0007; python3 "$common_dir/with-config.py" "$CONFIG_FILE" "$@"); }
"$uv" sync --project AiVideoGenerator --python 3.12 --managed-python --locked --no-dev \
    --extra production --extra oracle
chmod -R a+rX "$DEPLOY_ROOT/tools/python"
python="$release/AiVideoGenerator/.venv/bin/python"
manage=("$python" "$release/AiVideoGenerator/backend/manage.py")
run_config "${manage[@]}" check
run_config "$python" -c 'from django.conf import settings; import django; django.setup(); assert settings.RUNTIME_ROOT == __import__("pathlib").Path(__import__("sys").argv[1]); assert not settings.DEBUG' \
    "$DEPLOY_ROOT/shared/runtime"
https=$(run_config "${manage[@]}" shell -c \
    'from django.conf import settings; print("yes" if settings.HTTPS_ENABLED else "no")' | tail -n 1)
if [[ $https == yes ]]; then
    run_config "${manage[@]}" check --deploy --fail-level WARNING
else
    run_config "${manage[@]}" check --deploy
fi
run_config "${manage[@]}" migrate --plan
run_config "${manage[@]}" makemigrations --check --dry-run
run_config "${manage[@]}" collectstatic --noinput
chmod -R g+rX "$release"
chmod 0755 "$release" "$release/AiVideoGenerator"
chmod -R a+rX "$release/AiVideoGenerator/staticfiles"
# main can advance while dependencies build. Check again before downtime.
git --git-dir="$repo" fetch origin '+refs/heads/main:refs/remotes/origin/main'
if [[ $(git --git-dir="$repo" rev-parse refs/remotes/origin/main) != "$sha" ]]; then
    echo "Commit $sha was superseded during preparation; activation skipped."
    exit 0
fi
stopped=0
activated=0
failure() {
    local code=$?
    trap - ERR
    if [[ $activated == 1 ]]; then
        if restore_release "$previous"; then
            echo 'Previous release recovered. Database migrations were NOT reversed.' >&2
        else
            echo 'Recovery health failed; inspect services and database manually.' >&2
        fi
    elif [[ $stopped == 1 && -n $previous ]]; then
        restart_services || true
        probe_release "$(basename "$previous")" || echo 'Previous release recovery failed.' >&2
    fi
    exit "$code"
}
trap failure ERR
sudo -n /usr/bin/systemctl stop aivideo-worker.service
stopped=1
sudo -n /usr/bin/systemctl stop aivideo-web.service
run_config "$python" "$common_dir/backup-database.py" "$DEPLOY_ROOT/shared/backups"
run_config "${manage[@]}" migrate --noinput
find "$DEPLOY_ROOT/shared/runtime" -type d -exec chmod g+rwx {} +
find "$DEPLOY_ROOT/shared/runtime" -type f -exec chmod g+rw {} +
link_current "$release"
activated=1
restart_services
probe_release "$sha"
scheme=http
[[ $https == yes ]] && scheme=https
public_body=$(curl --fail --silent --max-time 15 "$scheme://$PUBLIC_HOST/healthz/")
printf '%s' "$public_body" | python3 -c \
    'import json,sys; sys.exit(json.load(sys.stdin).get("release")!=sys.argv[1])' "$sha"
if [[ -n $previous && $previous != "$release" ]]; then
    ln -sfn "$previous" "$DEPLOY_ROOT/previous"
fi
printf '%s\n' "$sha" > "$DEPLOY_ROOT/shared/deployed-sha"
trap - ERR
count=0
while IFS= read -r candidate; do
    candidate_sha=$(basename "$candidate")
    validate_sha "$candidate_sha" || continue
    [[ ! -L $candidate && $(realpath "$candidate") == "$candidate" ]] || continue
    count=$((count + 1))
    if [[ $count -gt $RETAIN_RELEASES && $candidate != "$release" && $candidate != "$previous" ]]; then
        rm -rf -- "$candidate"
    fi
done < <(find "$DEPLOY_ROOT/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
    | sort -rn | cut -d ' ' -f 2-)
echo "Deployed $sha. Previous: ${previous:-none}."

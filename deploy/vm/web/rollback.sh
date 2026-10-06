#!/usr/bin/env bash
# Code rollback only; never reverse migrations or restore a live database.
set -euo pipefail
source "$(dirname "$0")/release-common.sh"
sha=${1:?usage: rollback.sh EXACT_PREVIOUS_COMMIT_SHA}
target=$(release_path "$sha") || { echo 'Unknown or unsafe release.' >&2; exit 1; }
previous=$(readlink -f "$DEPLOY_ROOT/current" || true)
[[ -n $previous ]] || { echo 'No current release to roll back.' >&2; exit 1; }
release_path "$(basename "$previous")" >/dev/null || exit 1
sudo -n /usr/bin/systemctl stop aivideo-worker.service
sudo -n /usr/bin/systemctl stop aivideo-web.service
link_current "$target"
if restart_services && probe_release "$sha"; then
    ln -sfn "$previous" "$DEPLOY_ROOT/previous"
    printf '%s\n' "$sha" > "$DEPLOY_ROOT/shared/deployed-sha"
    echo "Code rolled back to $sha. Database unchanged."
else
    restore_release "$previous" || echo 'Recovery failed; inspect services manually.' >&2
    exit 1
fi

#!/usr/bin/env bash
set -euo pipefail
source /etc/aivideo/deploy.conf
[[ $DEPLOY_ROOT =~ ^/srv/[a-zA-Z0-9_-]+$ ]] || exit 1
[[ $CONFIG_FILE == /etc/aivideo/web.env ]] || exit 1
RETAIN_RELEASES=${RETAIN_RELEASES:-5}
[[ $RETAIN_RELEASES =~ ^[0-9]+$ && $RETAIN_RELEASES -ge 2 && $RETAIN_RELEASES -le 50 ]] || exit 1
for path in "$DEPLOY_ROOT" "$DEPLOY_ROOT/releases" "$DEPLOY_ROOT/shared" "$DEPLOY_ROOT/shared/runtime"; do
    [[ ! -L $path && -d $path && $(realpath "$path") == "$path" ]] || exit 1
done
[[ $(id -un) == aivideo-deploy ]] || { echo 'Run as aivideo-deploy.' >&2; exit 1; }
umask 0027
exec 9> "$DEPLOY_ROOT/shared/deploy.lock"
flock -w 1800 9
common_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
validate_sha() { [[ $1 =~ ^[0-9a-f]{40}$ ]]; }
release_path() {
    validate_sha "$1" || return 1
    local path="$DEPLOY_ROOT/releases/$1"
    [[ ! -L $path && -d $path && $(realpath "$path") == "$path" ]] || return 1
    printf '%s\n' "$path"
}
link_current() {
    [[ ! -e $DEPLOY_ROOT/.current-next || -L $DEPLOY_ROOT/.current-next ]] || return 1
    ln -sfn "$1" "$DEPLOY_ROOT/.current-next"
    mv -Tf "$DEPLOY_ROOT/.current-next" "$DEPLOY_ROOT/current"
}
restart_services() {
    sudo -n /usr/bin/systemctl restart aivideo-web.service &&
    sudo -n /usr/bin/systemctl restart aivideo-worker.service
}
probe_release() {
    local expected=$1 body
    for _ in {1..20}; do
        if body=$(curl --fail --silent --max-time 6 -H "Host: $PUBLIC_HOST" \
                http://127.0.0.1:8000/readyz/) && \
            printf '%s' "$body" | python3 -c \
                'import json,sys; d=json.load(sys.stdin); sys.exit(d.get("status")!="ready" or d.get("release")!=sys.argv[1])' "$expected"; then
            return 0
        fi
        sleep 2
    done
    return 1
}
restore_release() {
    local previous=$1 sha
    if [[ -z $previous ]]; then
        sudo -n /usr/bin/systemctl stop aivideo-web.service || true
        sudo -n /usr/bin/systemctl stop aivideo-worker.service || true
        echo 'First release failed; no prior release exists.' >&2
        return 1
    fi
    sha=$(basename "$previous")
    [[ $(release_path "$sha") == "$previous" ]] || return 1
    link_current "$previous"
    restart_services && probe_release "$sha"
}

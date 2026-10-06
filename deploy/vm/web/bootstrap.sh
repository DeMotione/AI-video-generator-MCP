#!/usr/bin/env bash
# Run as root from reviewed code. Does not create/read application secret files.
set -euo pipefail
[[ $EUID == 0 ]] || { echo 'Run bootstrap with sudo.' >&2; exit 1; }
root=${1:?usage: bootstrap.sh /srv/aivideo PUBLIC_HOST REPOSITORY_SSH_URL [SSH_PORT]}
host=${2:?Set your public domain or initial VM public IP}
repository=${3:?Set the GitHub repository SSH URL}
ssh_port=${4:-22}
[[ $root =~ ^/srv/[a-zA-Z0-9_-]+$ ]] || { echo 'Use a direct /srv/name path.' >&2; exit 1; }
[[ ! -L $root ]] || { echo 'Deployment root must not be a symlink.' >&2; exit 1; }
[[ $host =~ ^[a-zA-Z0-9][a-zA-Z0-9.-]*$ ]] || exit 1
[[ $repository =~ ^git@github\.com:[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+\.git$ ]] || exit 1
[[ $ssh_port =~ ^[0-9]+$ && $ssh_port -ge 1 && $ssh_port -le 65535 ]] || exit 1
templates=$(cd "$(dirname "$0")" && pwd)
app_user=aivideo
deploy_user=aivideo-deploy
config_file=/etc/aivideo/web.env
apt-get update
apt-get install -y nginx git curl python3 python3-venv sqlite3 util-linux \
    certbot python3-certbot-nginx
id "$app_user" >/dev/null 2>&1 || useradd --system --user-group --home-dir "$root" \
    --shell /usr/sbin/nologin "$app_user"
id "$deploy_user" >/dev/null 2>&1 || useradd --create-home --user-group --shell /bin/bash "$deploy_user"
usermod -aG "$app_user" "$deploy_user"
install -d -o "$deploy_user" -g "$app_user" -m 2755 "$root" "$root/releases"
install -d -o "$deploy_user" -g "$app_user" -m 2755 "$root/tools"
install -d -o "$deploy_user" -g "$app_user" -m 2770 "$root/shared" \
    "$root/shared/runtime" "$root/shared/backups"
install -d -o root -g "$app_user" -m 0750 /etc/aivideo
install -d -o root -g root -m 0755 /usr/local/lib/aivideo
printf 'DEPLOY_ROOT=%q\nPUBLIC_HOST=%q\nREPOSITORY=%q\nCONFIG_FILE=%q\n' \
    "$root" "$host" "$repository" "$config_file" > /etc/aivideo/deploy.conf
printf 'RETAIN_RELEASES=5\n' >> /etc/aivideo/deploy.conf
chmod 0644 /etc/aivideo/deploy.conf
for name in deploy-release.sh rollback.sh release-common.sh with-config.py backup-database.py ssh-deploy.sh; do
    install -o root -g root -m 0755 "$templates/$name" "/usr/local/lib/aivideo/$name"
done
render() {
    sed -e "s|@APP_USER@|$app_user|g" -e "s|@DEPLOY_ROOT@|$root|g" \
        -e "s|@CONFIG_FILE@|$config_file|g" -e "s|@PUBLIC_HOST@|$host|g" "$1" > "$2"
}
for service in aivideo-web aivideo-worker; do
    render "$templates/$service.service" "/etc/systemd/system/$service.service"
done
sudoers=$(mktemp)
trap 'rm -f "$sudoers"' EXIT
cat > "$sudoers" <<'SUDO'
aivideo-deploy ALL=(root) NOPASSWD: /usr/bin/systemctl stop aivideo-web.service, /usr/bin/systemctl stop aivideo-worker.service, /usr/bin/systemctl restart aivideo-web.service, /usr/bin/systemctl restart aivideo-worker.service
SUDO
visudo -cf "$sudoers"
install -o root -g root -m 0440 "$sudoers" /etc/sudoers.d/aivideo-deploy
if [[ ! -e /etc/nginx/sites-available/aivideo ]]; then
    render "$templates/nginx.conf" /etc/nginx/sites-available/aivideo
fi
ln -sfn /etc/nginx/sites-available/aivideo /etc/nginx/sites-enabled/aivideo
nginx -t
systemctl daemon-reload
systemctl enable aivideo-web.service aivideo-worker.service
systemctl reload nginx
echo "Bootstrap prepared $root. Services start after the first release."
echo "SSH port: $ssh_port. No firewall rules or application secrets changed."

#!/usr/bin/env bash
# Copy the MCP package and the agent to the Oracle VM and restart both services.
#
#   deploy/vm/deploy.sh ubuntu@<vm-tailscale-ip> path/to/ssh-key.key
#
# Backs up the VM's current code first. Never copies .env files: secrets stay
# on the VM (see deploy/vm/README.md for the variables to set there).
set -euo pipefail

host="${1:?usage: deploy.sh user@host ssh-key}"
key="${2:?usage: deploy.sh user@host ssh-key}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
ssh_opts=(-i "$key" -o BatchMode=yes)

stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/video_mcp"
cp "$root"/video_mcp/*.py "$root"/video_mcp/*.json "$stage/video_mcp/"
cp "$root/deploy/vm/agent/agent.py" "$stage/agent.py"

ssh "${ssh_opts[@]}" "$host" 'rm -rf ~/deploy-staging && mkdir -p ~/deploy-staging'
scp -q "${ssh_opts[@]}" -r "$stage/video_mcp" "$stage/agent.py" "$host:deploy-staging/"

ssh "${ssh_opts[@]}" "$host" 'set -e
stamp=$(date +%Y%m%d-%H%M%S)
cp -a ~/ai-video-mcp/video_mcp ~/ai-video-mcp/video_mcp.backup-$stamp
cp -a ~/mcp-agent/agent.py ~/mcp-agent/agent.py.backup-$stamp
sed -i "s/\r$//" ~/deploy-staging/video_mcp/* ~/deploy-staging/agent.py
cp ~/deploy-staging/video_mcp/* ~/ai-video-mcp/video_mcp/
cp ~/deploy-staging/agent.py ~/mcp-agent/agent.py
rm -rf ~/deploy-staging ~/ai-video-mcp/video_mcp/__pycache__
sudo systemctl restart aivideo-mcp
sleep 4
sudo systemctl restart aivideo-agent
sleep 4
curl -fsS http://127.0.0.1:8001/healthz && echo
systemctl is-active aivideo-mcp aivideo-agent
echo "Backups: video_mcp.backup-$stamp, agent.py.backup-$stamp"'

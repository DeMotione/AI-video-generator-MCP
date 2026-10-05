# Website on the existing Oracle Gemma VM

Keep the code in GitHub and clone it to `/home/ubuntu/aivideo-web` on the VM.
The existing `/home/ubuntu/mcp-agent` and `/home/ubuntu/ai-video-mcp` services
stay in their current folders. The website and one queue worker call the
authenticated agent at `http://127.0.0.1:8100`; no PC tunnel is involved in
generation on the deployed site.

## Prepare

On the VM, clone the repository containing these changes:

```bash
git clone <your-github-repository-url> /home/ubuntu/aivideo-web
cd /home/ubuntu/aivideo-web
uv sync --project AiVideoGenerator --extra production --frozen
```

Deploy the updated `deploy/vm/agent/agent.py` to `~/mcp-agent/agent.py` with
the existing `deploy/vm/deploy.sh` from the PC, or back up and copy it from
this checkout on the VM, then restart `aivideo-agent`. The new `/jobs` routes
are required; the original `/chat` route continues to work. Agent dependencies
are unchanged. Run `~/mcp-agent/.venv/bin/python ~/mcp-agent/check-agent.py`
to check readiness without rendering a video.

Copy `deploy/vm/web/.env.example` to the **repository root** `.env`, edit it,
and set mode 600. Supply a random Django secret, your hostname, and the
existing `AGENT_API_TOKEN` from `~/mcp-agent/.env`. Never commit `.env`.
The example values intentionally cannot be used as production credentials.

```bash
cp deploy/vm/web/.env.example .env
chmod 600 .env
# Edit .env before running these commands.
uv run --project AiVideoGenerator python AiVideoGenerator/backend/manage.py check --deploy
uv run --project AiVideoGenerator python AiVideoGenerator/backend/manage.py migrate
uv run --project AiVideoGenerator python AiVideoGenerator/backend/manage.py provision_user --email you@example.com --name YourName --admin
uv run --project AiVideoGenerator python AiVideoGenerator/backend/manage.py collectstatic --noinput
```

This creates website tables in its own SQLite database under
`AiVideoGenerator/.runtime/`; it does not modify the MCP job files. Back up
that folder and `~/mcp-agent/data/requests.sqlite3`. Run one queue worker and
one agent process. SQLite is suitable for this initial single-VM setup.

## Start the services

```bash
sudo cp deploy/vm/web/aivideo-web.service deploy/vm/web/aivideo-worker.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now aivideo-web aivideo-worker
systemctl is-active aivideo-web aivideo-worker
journalctl -u aivideo-worker -n 50 --no-pager
```

Serve the website through an HTTPS reverse proxy on the VM. Point your domain
to the Oracle VM, allow ports 80/443 in the Oracle network rules and VM
firewall, and keep ports 8000/8001/8100/11434 on localhost. If Caddy is your
proxy, `Caddyfile.example` provides the site configuration: replace the
hostname, copy collected static files to `/var/www/aivideo-static`, and make
them readable by Caddy. Gunicorn accepts forwarded HTTPS headers from the
local reverse proxy, as defined by its
[forwarded-header settings](https://github.com/benoitc/gunicorn/blob/23.0.0/gunicorn/config.py).
The example body limit follows Caddy's
[request_body directive](https://caddyserver.com/docs/caddyfile/directives/request_body).
Install/configure the proxy before opening the site;
production Django settings redirect HTTP to HTTPS.

For an initial private check through your existing SSH connection, keep
`DJANGO_DEBUG=true` temporarily, use localhost allowed hosts, and forward:

```bash
ssh -L 8000:127.0.0.1:8000 ubuntu@<vm-host>
```

Open `http://127.0.0.1:8000`, log in, and attach a landscape ~16:9 image with
a motion prompt. Generation uses the configured RunPod backend and is billed.
Use `VIDEO_BACKEND=demo` in the MCP service for a free prepared-video check.
Restore production settings before exposing the site publicly.

## Request lifecycle

The browser uploads to Django and gets a queued job immediately. The worker
sends `{request_id, prompt, image_base64}` to `POST /jobs`. The agent persists
the request before running Gemma, saves the upload as an image temp file,
registers it with MCP, and records the MCP video job ID. Django polls
`GET /jobs/<request_id>`, then downloads `GET /jobs/<request_id>/video` into
its private storage. Playback and downloads go through Django's existing
owner-checked media route; agent credentials and localhost URLs stay on the
server.

The temporary upload is deleted after planning, on cancellation, or at agent
startup after a crash. MCP's normalized `data/assets` and `data/outputs`
files remain persistent, as do the web chat attachments and downloaded videos.
There is no automatic retention policy for those persistent files yet.

Repeated requests with the same ID and same input return the saved record;
different input using the same ID is rejected. A lost acceptance response is
reconciled by ID. Known MCP jobs resume polling after worker/agent restarts.
An agent restart during planning or uncertain submission marks the request
unknown instead of repeating generation. Inspect the VM records before
creating a replacement for an unknown request. Preserve the request database
to preserve duplicate protection.

## Updating from GitHub

Stop the website worker before changing code or applying migrations, pull
the reviewed changes, sync dependencies, migrate and collect static files,
then restart the web services. Update the separate agent copy when its code
changes. Keep `.env`, `.runtime`, MCP data and the agent request database.
The repository contains deployment configuration; pushing code to GitHub
does not automatically deploy it to Oracle.

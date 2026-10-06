# Publish AiVideoGenerator on the Oracle VM

These artifacts are prepared for you to run. No VM, GitHub, DNS, firewall or
application secret configuration was changed by preparing this solution.
No environment files were inspected or edited. No test files were added.

## Architecture and paths

Internet → Nginx 80/443 → Gunicorn 127.0.0.1:8000 → Django SQLite or Oracle.
One systemd queue worker → authenticated agent 127.0.0.1:8100 → private MCP
127.0.0.1:8001 → OpenRouter Qwen planning and RunPod GPU generation.
The browser receives a request ID immediately and polls; GPU work does not
hold a web worker. Images/videos are served by authenticated owner-checked
Django routes. Nginx serves only static assets. No frontend build is required.

The default new web deployment root is `/srv/aivideo`, configurable to another
direct `/srv/name` path during bootstrap. It is separate from the existing
`/home/ubuntu/mcp-agent` and `/home/ubuntu/ai-video-mcp` installations.

```text
/srv/aivideo/
  source/                      administrator checkout for bootstrap/maintenance
  releases/<full-commit>/       code, web venv, matching collected static files
  current -> releases/<commit> atomic active release
  previous -> releases/<commit>
  tools/python/                Python 3.12, readable by the app account
  repository.git/              read-only upstream Git access
  shared/runtime/              web database, private media, worker heartbeat
  shared/backups/               pre-migration web database snapshots
/etc/aivideo/web.env            fixed production configuration you supply
/etc/aivideo/deploy.conf        non-secret host/root/repository settings
/usr/local/lib/aivideo/         administrator-installed deployment commands
```

`aivideo` runs the application with no interactive shell. `aivideo-deploy`
builds releases and has sudo only for stopping/restarting the two web services.
It belongs to the application group and can read production configuration:
this is a trusted deployment identity, not a developer login. Both identities
can write runtime state; Nginx cannot read it. Shared data is never replaced
by deployment. Keep one worker; do not start a second PC worker against this
production database. The initial web configuration uses two workers with two
threads each. Measure CPU, RAM, queue times and database contention before
changing capacity; GPU requests are currently serialized by the agent.

## 1. Commit the prepared code and bootstrap

Review changes on a feature branch and merge through a PR. Deployment pulls
an exact commit from `main`; files only on your PC cannot be deployed by SHA.
From your PC, connect to the VM using your existing SSH key/Tailscale address:

```powershell
& "C:\Windows\System32\OpenSSH\ssh.exe" `
  -i "C:/Users/goodf/.ssh/oracle-ai-video.key" ubuntu@100.99.77.89
```

On the VM, clone a reviewed checkout without touching existing service folders.
For a private repository, first give your administrator checkout Git access.
Replace the host with your chosen domain or initial **public** VM IP:

```bash
sudo mkdir -p /srv/aivideo
sudo install -d -o ubuntu -g ubuntu -m 0755 /srv/aivideo/source
git clone https://github.com/goodfy704/AI-video-generator-MCP.git /srv/aivideo/source
cd /srv/aivideo/source
git switch main
sudo bash deploy/vm/web/bootstrap.sh /srv/aivideo video.example.com \
  git@github.com:goodfy704/AI-video-generator-MCP.git 22
```

Bootstrap installs Ubuntu packages, accounts, web units, limited sudo rules
and a dedicated Nginx site. It does not open firewall ports, modify the
MCP/agent units or create/read the application secret file. It preserves other
Nginx sites; if another proxy already owns 80/443, resolve that conflict first.
On repeated bootstrap it preserves an existing Nginx site, including Certbot's
TLS edits. Template changes then require an administrator review/update.
Root-installed deployment scripts likewise need bootstrap again when changed.

Install uv for the deploy identity using the official installer:

```bash
sudo -u aivideo-deploy -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo -u aivideo-deploy -H /home/aivideo-deploy/.local/bin/uv --version
```

Dependencies come from the existing web `uv.lock` using `uv sync --locked
--no-dev --extra production --extra oracle`. Both extras support either SQLite
or Oracle plus OCI storage without changing production configuration per release.
The managed interpreter is Python 3.12, supported by the web's actual manifest.

### Fixed production configuration — supplied by you

Prepare configuration securely yourself, outside the repository. We have not
created an environment example because of your restriction. Install your file
as `/etc/aivideo/web.env`; for example, after securely transferring a file named
`web-production.conf` into your administrator's home:

```bash
sudo install -o root -g aivideo -m 0640 ~/web-production.conf /etc/aivideo/web.env
```

Remove the transferred plaintext copy securely according to your own process.
Do not send secrets in chat, commit them, add them to GitHub Actions, or pass
them as command-line arguments. Use a password manager or your trusted editor;
no `nano` workflow is required. Configuration entries are single `KEY=value`
lines, with quotes for spaces. No `$` expansion, backslashes, multiline values,
`export`, or inline comments; this literal subset behaves consistently in
systemd and the deployment command. Full-line `#` comments are allowed.

| Existing/new setting | Production value you supply |
| --- | --- |
| `APP_ENV` | `production` (also enforced by service launchers) |
| `DJANGO_DEBUG` | `false` |
| `DJANGO_SECRET_KEY` | Unique random secret, at least 50 characters |
| `DJANGO_ALLOWED_HOSTS` | Your public hostname; explicit comma-separated hosts, no wildcard |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://video.example.com` after TLS |
| `DJANGO_HTTPS_ENABLED` | `true` after TLS; `false` for initial HTTP verification only |
| `DJANGO_RUNTIME_ROOT` | `/srv/aivideo/shared/runtime`, matching your deployment root |
| `DB_BACKEND` | `sqlite` initially, or your existing `oracle` integration |
| `STORAGE_BACKEND` | `local` initially, or existing private `oci` storage |
| `GENERATION_BACKEND` | `agent` |
| `AGENT_URL` | `http://127.0.0.1:8100` on this same VM |
| `AGENT_API_TOKEN` | Same private token as the existing agent; at least 32 characters |

For Oracle, preserve `ORACLE_DB_DSN`, `ORACLE_DB_USER`, `ORACLE_DB_PASSWORD`
and optional `ORACLE_CONFIG_DIR`, `ORACLE_WALLET_LOCATION`,
`ORACLE_WALLET_PASSWORD`. Store wallets in a readable external directory such
as `/etc/aivideo/wallet`, not in a home directory hidden by `ProtectHome=true`.
For OCI, retain `OCI_NAMESPACE`, `OCI_BUCKET`, `OCI_REGION`, and use
`OCI_AUTH_MODE=instance_principal` with appropriately scoped IAM where possible;
otherwise put `OCI_CONFIG_FILE` outside `/home` and preserve
`OCI_CONFIG_PROFILE`. Keep the bucket private.

OpenRouter/RunPod keys remain in their existing agent/MCP service configuration.
The Django web file does not need those provider keys. Keep your selected
`qwen/qwen3.5-flash-02-23` model in the existing agent configuration. A model
is selected with the model slug, not a separate model-specific API key.

If an older web installation already holds real data, stop its web/worker
services, back up its database/private media, then explicitly transfer them
into `shared/runtime` and set group `aivideo` with group write permissions.
Do not assume the old development SQLite file is your production database.
For a new installation the script creates a separate database there.

## 2. Private Git access, SSH, CI and networking

### VM → GitHub (read-only repository key)

This key is separate from the CI key that logs into the VM:

```bash
sudo -u aivideo-deploy -H mkdir -p /home/aivideo-deploy/.ssh
sudo chmod 700 /home/aivideo-deploy/.ssh
sudo -u aivideo-deploy -H ssh-keygen -t ed25519 \
  -f /home/aivideo-deploy/.ssh/id_ed25519 -N '' -C aivideo-repository-readonly
sudo cat /home/aivideo-deploy/.ssh/id_ed25519.pub
```

GitHub repository → **Settings → Deploy keys → Add deploy key**. Paste the
public key; leave **Allow write access** unchecked. For GitHub host verification,
collect a candidate public host key, compare its fingerprint against
[GitHub's published SSH fingerprints](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/githubs-ssh-key-fingerprints),
then install only a verified key in the deploy user's `known_hosts`. Do not
blindly accept `ssh-keyscan` output. Verify access without changing code:

```bash
sudo -u aivideo-deploy -H git ls-remote \
  git@github.com:goodfy704/AI-video-generator-MCP.git refs/heads/main
```

### GitHub Actions → VM (restricted deployment key)

Generate a separate Ed25519 CI key on your trusted PC. Keep the private key
for the GitHub secret; append the public key to
`/home/aivideo-deploy/.ssh/authorized_keys` with this prefix on the same line:

```text
restrict,command="/usr/local/lib/aivideo/ssh-deploy.sh" ssh-ed25519 YOUR_CI_PUBLIC_KEY
```

Use administrator access to set owner `aivideo-deploy:aivideo-deploy`, mode
700 for `.ssh`, and 600 for `authorized_keys`. This key only accepts
`deploy <full-commit>`; it cannot start a shell or SSH port forwarding.
The script checks `main` membership and rejects/skips stale commits under its
server lock. Never put a PR-running self-hosted runner on this VM.

Confirm the VM's SSH host fingerprint independently through the Oracle console
or your already trusted administrator connection:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
sudo cat /etc/ssh/ssh_host_ed25519_key.pub
```

Construct the known-hosts line with the exact CI hostname/IP and that confirmed
public host key: `100.99.77.89 ssh-ed25519 PUBLIC_HOST_KEY`. For a nonstandard
SSH port use `[100.99.77.89]:PORT`. Store that line in `DEPLOY_KNOWN_HOSTS`.

### Tailscale for the GitHub-hosted runner

The workflow uses `tailscale/github-action@v4`, then normal verified SSH over
the VM's Tailscale address. In the Tailscale admin console:

1. Create tag `tag:aivideo-ci` with tag ownership limited to administrators.
2. Tag the VM `tag:aivideo-vm` and grant the CI tag access only to that VM's
   actual SSH port (e.g. `tcp:22`). Preserve your administrator access rules.
3. Create an OAuth client that can create auth keys scoped to `tag:aivideo-ci`.
   Save its client ID and secret as the two GitHub secrets below.

Example policy fragments to merge into your existing policy, not replace it:

```json
{
  "tagOwners": {
    "tag:aivideo-ci": ["autogroup:admin"],
    "tag:aivideo-vm": ["autogroup:admin"]
  },
  "grants": [{"src": ["tag:aivideo-ci"], "dst": ["tag:aivideo-vm"], "ip": ["tcp:22"]}]
}
```

Use the VM's OpenSSH server for the forced-command key. If Tailscale SSH
intercepts port 22 on your VM, choose/configure a distinct OpenSSH port and
allow it in the tailnet grant; do not disable your current administrator
connection without an alternative. Set `DEPLOY_PORT` accordingly.
See [Tailscale's CI integration](https://tailscale.com/docs/solutions/connect-github-cicd-workflows-to-private-infrastructure-without-public-exposure).

### GitHub settings

Repository → **Settings → Environments → New environment → production**.
Restrict deployment branches to `main`. Under that environment's secrets and
variables (or repository **Secrets and variables → Actions**), configure:

| Kind | Name | Content |
| --- | --- | --- |
| Secret | `DEPLOY_SSH_KEY` | Dedicated CI private key, complete PEM/OpenSSH text |
| Secret | `DEPLOY_KNOWN_HOSTS` | Independently verified VM known-hosts entry |
| Secret | `TS_OAUTH_CLIENT_ID` | Scoped Tailscale OAuth client ID |
| Secret | `TS_OAUTH_SECRET` | Scoped Tailscale OAuth client secret |
| Variable | `DEPLOY_HOST` | VM tailnet hostname/IP, e.g. `100.99.77.89` |
| Variable | `DEPLOY_PORT` | OpenSSH port, normally `22` |

No Django, Oracle, OCI, OpenRouter or RunPod secrets belong in this workflow.
Protect `main`: **Settings → Rules → Rulesets → New branch ruleset**; target
`main`, require PRs, at least one approving reviewer, resolve conversations,
block force pushes/deletion and require **Django checks** and **MCP and agent
checks**. Run the workflow once so those check names become selectable.
Keep workflow/deployment-script changes reviewed. Manual Actions dispatch must
select `main`; a failed/older run cannot deploy a newer unchecked commit.
CI concurrency does not cancel a running deployment; the server lock also
serializes manual deployments. If newer main supersedes a checked SHA, that
SHA is skipped; the newer commit's own successful workflow deploys it.

### OCI public networking and host firewall are separate

In Oracle → VM → attached VNIC → subnet security list / network security
group, add ingress TCP 80 and 443 for your site's intended public users. Keep
SSH limited to trusted administration/tailnet access. Do not expose 8000,
8001, 8100 or the database to the internet. DNS `A` points to the VM **public**
IP, not `100.99.77.89`; add `AAAA` only if IPv6 is configured end to end.

Inspect the VM firewall manager before changing rules:

```bash
sudo ufw status verbose
sudo nft list ruleset
sudo iptables -S
sudo ss -ltnp
```

If UFW is already active, preserve the real SSH port rule before adding web
access, then `sudo ufw allow 'Nginx Full'`. If OCI uses iptables/nftables,
update that existing manager persistently; do not enable a competing manager
or flush rules. Bootstrap deliberately does not make these changes.
Oracle trial credits and Always Free eligibility are different: check the VM
shape and all related resources in your tenancy; do not assume trial-funded
resources survive expiry. [Oracle Free Tier documentation](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm).

## 3. First deployment, user account, HTTPS and verification

Finish the fixed production file and repository access first. For initial
IP/HTTP verification keep `DJANGO_DEBUG=false`, set the explicit public IP or
domain in allowed hosts, and temporarily set `DJANGO_HTTPS_ENABLED=false`.
Do not log in or upload over public HTTP. Establish HTTPS before real use.
Initial Django deployment checks will warn about HTTP cookies, redirects and
HSTS; those are expected only for this bootstrap phase.

Deploy the current reviewed `main` head explicitly:

```bash
cd /srv/aivideo/source
git pull --ff-only origin main
commit=$(git rev-parse HEAD)
sudo -u aivideo-deploy -H bash /usr/local/lib/aivideo/deploy-release.sh "$commit"
sudo systemctl is-active aivideo-web aivideo-worker aivideo-agent aivideo-mcp
curl --fail -H 'Host: video.example.com' http://127.0.0.1:8000/readyz/
curl --fail http://video.example.com/healthz/
```

Readiness must return `status: ready` and the expected full `release` SHA.
It checks database connectivity, worker heartbeat/release and the agent's
free liveness endpoint. It never invokes OpenRouter or paid GPU generation.
The public health check validates the Nginx route separately. Deployment
fails and restores the prior release if activation or health fails. On a
first-release failure there is no prior release; inspect logs and fix setup.
HSTS applies to this host after TLS. Checks W005/W021 are deliberately silenced:
subdomain-wide HSTS and browser preload require separate domain-owner decisions.
All other deployment warnings remain enforced after HTTPS activation.

Create the initial admin interactively after database migration (the password
is requested without echoing). Run the existing management command under the
same production configuration and deployment identity:

```bash
cd /srv/aivideo/current
sudo -u aivideo-deploy -H python3 /usr/local/lib/aivideo/with-config.py \
  /etc/aivideo/web.env /srv/aivideo/current/AiVideoGenerator/.venv/bin/python \
  /srv/aivideo/current/AiVideoGenerator/backend/manage.py provision_user \
  --email you@example.com --name YourName --admin
```

After DNS and both firewall layers permit 80/443, obtain HTTPS:

```bash
sudo certbot --nginx -d video.example.com
sudo nginx -t
sudo systemctl is-active certbot.timer
sudo certbot renew --dry-run
```

Through your secure configuration process, enable `DJANGO_HTTPS_ENABLED=true`
and HTTPS CSRF origins in the fixed VM file. Restart web/worker as administrator:

```bash
sudo systemctl restart aivideo-web aivideo-worker
curl --fail https://video.example.com/readyz/
```

Do not disable certificate validation. After TLS, future deployments enforce
`check --deploy --fail-level WARNING`. Follow Django's
[deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).
Log in at `https://video.example.com/auth/login/`. A real video request is billed
by your configured providers; validation here did not render a video.

### Keep the existing agent current

The web release deployment restarts only web/worker; it does not overwrite
MCP code, provider configuration or the agent request database. Your previously
prepared native Qwen agent must already be installed on the VM. If needed,
upload just `deploy/vm/agent/agent.py` with your existing `scp -O` command,
back up the current copy and restart `aivideo-agent` as administrator. Preserve
`/home/ubuntu/mcp-agent/data/requests.sqlite3` and all MCP data. Provider-service
code upgrades remain separate reviewed administrator actions.

## 4. Three-developer workflow

Each developer clones and installs the web project:

```powershell
git clone https://github.com/goodfy704/AI-video-generator-MCP.git
cd AI-video-generator-MCP
uv sync --project AiVideoGenerator --locked
$env:APP_ENV = 'development'
$env:DB_BACKEND = 'sqlite'
$env:STORAGE_BACKEND = 'local'
$env:DJANGO_DEBUG = 'true'
uv run --project AiVideoGenerator python AiVideoGenerator/backend/manage.py migrate
uv run --project AiVideoGenerator python AiVideoGenerator/backend/manage.py runserver
```

In a second terminal with the same development settings, run `manage.py
runworker`. Configure each developer's agent access/SSH tunnel independently
using their own untracked configuration and scoped development credentials.
Never copy production credentials or point the local database at production.

One schema uses the existing variable names. Development precedence is:
optional `.env.defaults` → untracked repository `.env` → untracked `.env.local`
→ process variables. The mode comes from process `APP_ENV` before any local
file can load; invalid modes are rejected. Production never loads local files.
No such files were created/changed here. Shared safe defaults are already in
Python settings; add personal overrides yourself without editing shared rows.
Values are literal; no dotenv variable expansion. OCI storage receives the
same merged values as Django.

For each change:

```powershell
git switch main
git pull --ff-only
git switch -c feature/your-change
# Implement, commit, and push your branch.
git push -u origin feature/your-change
```

Open a PR, get another developer's review, pass CI, then merge. Update your
local `main` with `git pull --ff-only`; personal untracked overrides persist.
Do not include keys, wallets, media or local runtime databases in commits.
Ignore rules cannot remove secrets already tracked: check repository history
separately and rotate any credentials previously published.

## 5. Subsequent deploys, logs, rollback and recovery

Successful pushes/PR merges to `main` run isolated existing checks/tests, then
deploy over the CI tailnet. PR jobs have no production secrets; no
`pull_request_target` workflow is used. To retry, **Actions → Validate and
deploy → Run workflow → main**. Web services briefly stop for consistent
backup/migration. Review all migrations for compatibility with the previous
release; use expand/contract changes. No deployment script can automatically
prove that arbitrary migrations are backward compatible.

```bash
sudo journalctl -u aivideo-web -u aivideo-worker -n 100 --no-pager
sudo journalctl -u aivideo-agent -u aivideo-mcp -n 100 --no-pager
readlink -f /srv/aivideo/current
readlink -f /srv/aivideo/previous
```

Manual **code** rollback to an existing full SHA:

```bash
sudo -u aivideo-deploy -H bash /usr/local/lib/aivideo/rollback.sh FULL_PREVIOUS_SHA
```

The rollback command verifies release paths, shares the deploy lock, restarts
web/worker and verifies readiness. If the target fails health, it attempts to
recover the starting release. It does not reverse migrations. Five release
directories are retained; current/previous are always protected. Shared data
and backups are never cleaned up automatically.
Administrators can set `RETAIN_RELEASES` (2–50) in the non-secret
`/etc/aivideo/deploy.conf`; the default is five.

SQLite snapshots use SQLite's backup API plus integrity checks after stopping
the web/worker. Store encrypted/off-VM backups of shared private media and the
database together on a schedule, and back up the separate agent request
database/MCP data using a procedure appropriate to those running services.
Pre-migration web snapshots alone are not a complete disaster-recovery plan.
For recovery: stop web/worker, preserve the current database, choose a tested
snapshot, explicitly restore it and matching media, restore owner/group,
verify integrity, then restart compatible code. Never restore over a live
database or erase request IDs without reconciling accepted GPU jobs: a restore
can lose knowledge of recent paid submissions.

For Oracle, deployment deliberately blocks before migration unless an
administrator installs executable `/etc/aivideo/oracle-backup`, root-owned and
not writable by group/others. It receives the backups directory and must
confirm a fresh recoverable database backup/restore point, recording the
recovery reference; return nonzero if that cannot be guaranteed. Implement
the procedure for your actual Oracle deployment (e.g. Autonomous Database
backup facilities or DBA-managed Data Pump/RMAN), rehearse recovery, and keep
recovery credentials out of the repository. No generic Oracle backup or
automatic schema reverse is assumed.

## Prepared files and validation

Application: `config/environment.py`, `settings.py`, `health.py`, `urls.py`,
worker heartbeat in existing `runworker.py`, and updated web metadata.
Deployment: this runbook, `bootstrap.sh`, `deploy-release.sh`, `rollback.sh`,
`release-common.sh`, `with-config.py`, `backup-database.py`, `ssh-deploy.sh`,
web/worker launchers and systemd templates, `nginx.conf`, `ci.sh`.
Repository: `.github/workflows/ci.yml`, `.gitattributes`, `.gitignore`.
Existing test files are reused; no new test files are required.
One existing media test now closes its streaming response for Windows cleanup.
MCP source import/UTC formatting was corrected so the new CI lint gate passes.

Local verification: 33 existing Django tests, 167 existing MCP tests and
10 existing agent tests passed. Django configuration/migration checks,
HTTPS deployment checks, lint, Python syntax, workflow structure, shell syntax,
locked dependency metadata and in-memory configuration precedence checks passed.
Ubuntu Nginx/systemd/Certbot are unavailable locally. Windows disallows native
symlinks in the isolated rollback fixture, so atomic switch/recovery validation
runs in the Linux CI script and must be observed after pushing this change.

Pending external setup: public host/DNS, the fixed production file, separate
repository and CI SSH keys, verified host keys, tailnet OAuth/grants, GitHub
environment/ruleset, firewall rules, HTTPS, and database recovery procedure.
Ubuntu Nginx/systemd/Certbot activation must be verified on the VM; preparing
these artifacts does not demonstrate a successful live deployment.

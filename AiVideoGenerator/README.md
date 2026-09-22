# AiVideoGenerator

A private Django website for turning an uploaded image and prompt into video through your existing ComfyUI workflow. Run it on your PC at `http://127.0.0.1:8000`.

Included: email/password login, predefined accounts, roles, database-backed sessions, image pasting and drag-and-drop, saved conversations, a persistent job queue, video playback, downloads, and logout. The interface uses Django templates, local CSS, and lightweight JavaScript. No Node.js build or frontend service is needed.

## Start locally

Install Python 3.12–3.14 and `uv`. Run these commands inside the extracted **AiVideoGenerator** folder. They work in Git Bash and PowerShell.

```bash
uv sync
uv run python backend/manage.py migrate
uv run python backend/manage.py provision_user --email you@example.com --name YourName --admin
uv run python backend/manage.py runserver 127.0.0.1:8000
```

Choose your own password when prompted. Open **http://127.0.0.1:8000** and log in with the email and password you just created. There is no shared default password and no public registration endpoint.

The `.env` file is included with local settings and blank Oracle credentials. A safe configuration template is also in `.env.example`. If setting up from Git instead of the ZIP, first copy `.env.example` to `.env`.

The local `migrate` command initializes only the development SQLite file and application tables. It does **not** create any Oracle cloud database. SQLite and private local files make the site usable while Oracle provisioning is deferred.

For rendering, connect your working workflow using [workflows/README.md](workflows/README.md). Start ComfyUI Desktop and keep it running. In a **second terminal**, from this project root:

```bash
uv run python backend/manage.py runworker
```

You now have three processes: ComfyUI, the Django website, and the worker. Paste or attach an image in the chat, describe the motion, and click Generate. The website remains usable while the worker renders. A stopped worker leaves jobs queued until it starts again.

This site talks directly to ComfyUI. Your Gemma VM and FastMCP agent are not required for this web flow; your existing MCP project can remain separate. There is no LLM reply generator in this first version: each image/prompt message creates a video job, and the assistant-style reply reports its state and result.

## Project layout

| Path | Purpose |
| --- | --- |
| `backend/config/` | Django settings, routes, Oracle configuration |
| `backend/accounts/` | Email users, roles, login, sessions, account provisioning |
| `backend/studio/` | Conversations, generation jobs, private file routes, worker |
| `backend/studio/services/` | Image validation, ComfyUI client, local/OCI storage |
| `frontend/templates/` | Login and chat page templates |
| `frontend/static/` | CSS, small JavaScript client, local SVG icon |
| `workflows/` | Your exported ComfyUI API workflow and setup instructions |
| `.env` | Local runtime settings; excluded from Git |
| `.env.example` | Shareable settings template |
| `.runtime/` | Development SQLite database and private local media; excluded from Git |

## Accounts and sessions

`accounts_user` contains normalized, unique email addresses, Django password hashes, role, active/staff flags, and profile fields. `django_session` stores sessions separately. Django's standard groups and permissions are also available; a separate password table is unnecessary.

Predefine more accounts with:

```bash
uv run python backend/manage.py provision_user --email teammate@example.com --name Teammate
```

Change a password with:

```bash
uv run python backend/manage.py changepassword teammate@example.com
```

An account created with `--admin` can manage users at `/admin/`. The `role` field labels membership; Django's staff/superuser flags and permissions enforce admin access. Both members and admins only see their own chats and media in the studio. Job records are read-only in the admin to avoid accidental resubmission.

Login is protected by CSRF and a basic per-process, per-IP throttle. Sessions use HttpOnly cookies and logout accepts POST only. Production HTTPS settings turn on when `DJANGO_DEBUG=false`. Before external hosting, replace the development secret, configure the allowed hosts and trusted origins, and configure a shared login throttle/cache if using multiple web processes. Deployment is intentionally outside this starter's scope.

## Oracle database configuration, for later

No cloud resources, database users, wallets, buckets, or credentials are created by this project. Leave `DB_BACKEND=sqlite` until you have an Oracle database and application user.

Install the optional Oracle packages when needed:

```bash
uv sync --extra oracle
```

Then supply your actual connection values in `.env`:

```dotenv
DB_BACKEND=oracle
ORACLE_DB_USER=
ORACLE_DB_PASSWORD=
ORACLE_DB_DSN=
ORACLE_CONFIG_DIR=
ORACLE_WALLET_LOCATION=
ORACLE_WALLET_PASSWORD=
```

`ORACLE_DB_DSN` accepts a connection descriptor, an Easy Connect string, or a TNS alias. The config directory points to the directory containing `tnsnames.ora`. Wallet fields support python-oracledb Thin-mode mTLS when required by your database. Use absolute paths and keep wallets outside Git. Blank optional connection fields are omitted.

This project uses Django 5.2 LTS and its official Oracle backend with `python-oracledb`. Django 5.2 requires Oracle Database 19c or later. The actual cloud connection and Oracle migration run remain unverified until you provide the database. Switching from SQLite to Oracle does not automatically copy local users, sessions, or chat history.

## Private object storage

By default, uploads and results live in `.runtime/private/`. They are **not** served through a public `/media/` path. Each image, video, and download request checks the logged-in owner first. Videos support authenticated byte-range requests for seeking.

For an existing private OCI Object Storage bucket, install the Oracle extras and configure:

```dotenv
STORAGE_BACKEND=oci
OCI_AUTH_MODE=config
OCI_CONFIG_FILE=~/.oci/config
OCI_CONFIG_PROFILE=DEFAULT
OCI_NAMESPACE=
OCI_BUCKET=
```

The OCI SDK reads your standard OCI config and signing key. Its identity needs the appropriate bucket-read and object-read/write permissions; this starter does not create IAM policies. The adapter checks that the bucket is `NoPublicAccess`, stores objects privately, and streams them through authenticated Django routes. It does not create public object URLs or preauthenticated links.

On an appropriately configured OCI instance, `OCI_AUTH_MODE=instance_principal` is also supported; set `OCI_REGION` if necessary. Provisioning and policy setup can be done later. Live OCI access has not been tested without your account.

Keep the web process and worker on the same storage backend. Changing backends does not move existing objects. ComfyUI also retains its uploaded inputs and generated outputs on its own machine; application privacy does not remove those renderer-side copies.

## Job behavior

The browser saves a queued job, then the separate worker validates your exported workflow, uploads the starting frame, and submits it once. The worker polls ComfyUI history, downloads the saved video, and places it in private storage.

Image inputs: PNG, JPEG, or still WebP; up to 10 MiB; each dimension 64–4096 pixels. Inputs are decoded, orientation-corrected, stripped of metadata, and stored as RGB PNG. Transparency is flattened on white. Your workflow determines output shape, duration, frame rate, and model. The UI does not invent progress percentages.

The client reuses a request ID if a submission response is lost, preventing a normal retry from creating another job. If ComfyUI's acceptance cannot be determined, the job becomes `unknown` and is never automatically resubmitted. Known accepted jobs resume polling after worker restart. A stale interrupted submission becomes `unknown` after five minutes.

For an unknown job, inspect ComfyUI's queue/history and find its accepted prompt ID. An admin can resume **polling only**, without submitting another render:

```bash
uv run python backend/manage.py resume_job JOB_UUID --comfy-id COMFY_PROMPT_ID
```

The command verifies that ComfyUI's stored `avg_job_id` matches the job. If history was cleared, it refuses to guess. The worker's default wait limit is 30 minutes. A timed-out job may still be rendering, so inspect ComfyUI before starting another.

Run one worker for this localhost prototype. This is a persistent local queue, not a distributed GPU scheduling system. Uploads and output retrieval are bounded; FFmpeg rendering requirements and GPU/model dependencies remain those of your working ComfyUI setup.

## Verification

```bash
uv sync --extra oracle
uv run python backend/manage.py check
uv run python backend/manage.py test studio -v 2
uv run ruff check backend
```

The tests cover authentication, CSRF, user isolation, image validation, private video ranges, duplicate requests, worker completion, ambiguous submissions, and the private OCI adapter with a stubbed SDK. Tests never call your GPU or a paid video provider. A live render and live Oracle/OCI connection require your actual workflow and credentials.

Verified in the build environment with Python 3.12.14 and Django 5.2.17: all 24 backend tests, Django checks, migration consistency, Ruff, and JavaScript syntax checks passed. A Chromium browser check passed login, image pasting, job creation, worker HTTP integration, status polling, video playback metadata, authenticated download, mobile navigation, and logout using a simulated ComfyUI server. Desktop and mobile layouts were visually inspected. No live GPU, Oracle DB, or OCI account was accessed.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Cannot log in | Run `migrate`, provision an account, and use its email/password |
| Renderer setup notice | Follow `workflows/README.md`; restart the web server and worker |
| Job stays queued | Keep `runworker` running in another terminal |
| Cannot reach renderer | Use ComfyUI's actual URL/port in `.env`; run `check_renderer` |
| Job says failed | Read ComfyUI's log and check that the selected node saves a video |
| Job needs attention | Inspect the queue/history; do not blindly resubmit |
| Website port is occupied | Use `runserver 127.0.0.1:8002` and add that origin to `.env` |

## References

- [Django authentication and sessions](https://docs.djangoproject.com/en/5.2/topics/auth/default/)
- [Django Oracle database support](https://docs.djangoproject.com/en/5.2/ref/databases/#oracle-notes)
- [python-oracledb connections and wallets](https://python-oracledb.readthedocs.io/en/latest/user_guide/connection_handling.html)
- [ComfyUI HTTP routes](https://docs.comfy.org/development/comfyui-server/comms_routes)
- [OCI Python SDK Object Storage client](https://docs.oracle.com/en-us/iaas/tools/python/latest/api/object_storage/client/oci.object_storage.ObjectStorageClient.html)

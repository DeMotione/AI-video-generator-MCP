# AI Video Generator: roadmap from mock MCP to paid SaaS

Prepared for justnevermark, PICNIC and Mot1One · 10 September 2026

This is a proposed delivery plan, with feature-level backlog items and acceptance criteria. Prices are current public list prices checked on this date, mostly in USD. They are not account-specific quotes. Performance figures below are test targets or explicitly illustrative calculations, not measured results from your service. No cloud resources, paid jobs or GitHub issues were created during this review.

## 1. Recommended decisions

| Area | Decision for your team |
|---|---|
| First deliverable | A private image + story → real downloadable 480p MP4 pipeline, usable with all three personal PCs switched off |
| Demo scope | One image, one short scene, 5-second output first; add a 10-second preset after it works; silent output initially |
| Control server | Keep the existing Oracle A1 VM for the MCP service, job coordinator and small local LLM |
| GPU | Try Modal Starter with one A100 80 GB worker; use Runpod as the fallback |
| Video model | Freeze Mot1One's best working LTX-2.5 workflow as the baseline; compare alternatives using recorded tests |
| Orchestrator | Benchmark Gemma 3 12B against Gemma 3 4B and Qwen3 4B; keep a direct, no-LLM baseline |
| Reliability | The application controls validation, job state, spending, retries and credit accounting |
| Task tracking | GitHub Issues + one GitHub Project; Discord for discussion, decisions recorded in issues |
| Website | Python Django, simple templates with lightweight JavaScript, PostgreSQL, private object storage |
| Deployment | Docker Compose + GitHub Actions; PICNIC owns infrastructure, release and recovery |
| Later infrastructure | Terraform for OCI resources; Ansible for VM configuration; introduce after the real GPU smoke test |
| First cash budget | €20 for a constrained demo; separate budget decision before expanded testing and paid launch |

Your VM + external GPU idea is sound. Keep the long video computation outside Oracle. A browser should receive a job ID quickly, then display progress while background work continues. MCP provides the tool interface; it is not the queue, database, GPU scheduler or billing system.

## 2. What the repository actually contains

Reviewed repository HEAD: 646804d0dd98c6f0cff203bc6aace0a74f2f713d. This was a source review; I did not run its tests or access the deployed VM. Source: [AI-video-generator-MCP](https://github.com/goodfy704/AI-video-generator-MCP).

| Finding | Effect on the roadmap |
|---|---|
| FastMCP is pinned to 4.0.3; Python is restricted to 3.14.x | Preserve a reproducible control environment; give the GPU worker its own Python/CUDA environment |
| Four thin MCP tool wrappers and a VideoBackend protocol exist | Extend these rather than rebuilding the project |
| The mock has in-memory jobs, timed state transitions and cancellation | Reuse it for cheap workflow/failure tests; replace memory-only persistence for hosted jobs |
| VideoRequest has prompt, duration and aspect ratio, but no image | Image upload and asset references are the first contract change |
| Mock result paths point to files that do not exist | A real, validated MP4 is a mandatory proof-of-concept gate |
| Duration currently accepts 1–60 seconds and five aspect ratios | Replace broad mock promises with model-specific supported presets |
| server.py already starts HTTP on 127.0.0.1:8000 | README instructions saying stdio-only are stale; test and document each intended transport |
| Tests cover models, backend, configuration and MCP paths | Retain them, reconcile transport assumptions, then add tests for the new failure modes |
| agent.py is not present in the reviewed checkout | Commit a sanitized agent and configuration example so the VM setup is reproducible |
| pyproject.toml names README.md, while the file is readme.md | Fix the filename/reference mismatch for Linux and packaging |

The README records earlier LLM test results, but those are historical project claims rather than benchmarks independently reproduced here. Your supplied description is the source for the live Oracle/Ollama/Tailscale setup.

## 3. Architecture and ownership

### Proof of concept

~~~mermaid
flowchart TD
    A[Private CLI: image and story] --> B[Oracle job coordinator]
    B --> C[Ollama planner]
    C --> D[Validated MCP tool call]
    D --> E[Durable job record]
    E --> F[GPU provider adapter]
    F --> G[Serverless video worker]
    G --> H[Private media storage]
    B --> E
    B --> H
~~~

The orchestrator constructs a small generation plan, including required action, image reference, duration preset, orientation and output settings. It may propose a tool call. Your Python code validates that call, attaches trusted job/user context and submits a bounded job. A background coordinator checks provider status without asking the LLM to poll repeatedly.

Start with the exact workflow Mot1One already knows works. If it is ComfyUI, export and pin the workflow JSON, nodes, model revisions and dependencies, then run that fixed workflow inside the GPU worker. If it is already a native Python pipeline, keep that. Porting a working ComfyUI graph to another inference library is an optional later optimization. LTX documents both approaches. [LTX quick start](https://docs.ltx.io/open-source-model/getting-started/quick-start).

### Website and paid beta

~~~mermaid
flowchart TD
    U[Browser] --> W[Django web API]
    W --> P[PostgreSQL: users, jobs, credits]
    W --> S[Private object storage]
    W --> Q[Durable job coordinator]
    Q --> L[Ollama planner]
    L --> M[Private MCP service]
    M --> G[GPU provider and worker]
    G --> S
    Q --> P
    B[Payment provider] --> W
~~~

Use Django because you are already developing in Python and need accounts, forms, administration and database migrations. Its authentication framework provides the foundation for accounts and permissions. Add verified email and password-reset delivery using a maintained integration. This avoids spending the first release building a separate frontend application and custom authentication system. [Django authentication](https://docs.djangoproject.com/en/5.2/topics/auth/).

Keep the generation service independent of Django and FastMCP. Both should call the same application service, which enforces authorization and spending. A customer browser never receives GPU-provider credentials or directly invokes unrestricted MCP tools.

Use PostgreSQL for durable jobs from the hosted proof of concept onward. At first, a separate Python worker can claim queued rows with database transactions, leases and heartbeats. This is one authoritative job queue; a GPU provider can have its own execution queue, with its IDs mapped to your jobs. Add a dedicated broker only if measured queue complexity warrants it.

Store images and MP4 files in private object storage. Store ownership, keys, checksums and metadata in PostgreSQL. Model weights stay in GPU-provider cache/storage, not in your customer-media bucket or Git repository.

### Responsibilities

| Person | Primary ownership | Concrete handoff |
|---|---|---|
| justnevermark | MCP contracts, application services, agent integration, web/API, accounts and credits | Versioned API/tool contract, working application, automated correctness tests |
| Mot1One | Video-model evaluation, LLM evaluation, prompt quality and media validation | Reproducible workflow pack and a scored benchmark report |
| PICNIC | OCI, GPU deployment, container builds, CI/CD, secrets, monitoring and recovery | Reproducible deployment and a tested recovery runbook |

Each feature has one accountable owner. Review by another person is required for changes to billing, security, job transitions or deployment. PICNIC can begin access hygiene and deployment discovery immediately; full automation follows the first real clip.

## 4. GPU options and the billing question

### Shortlist

| Option | Public price checked | Appropriate use |
|---|---|---|
| Modal A100 80 GB | $0.000694/GPU-second, about $2.50/GPU-hour; CPU and RAM extra | First serverless demo candidate |
| Runpod A100 80 GB Flex | Approximately $2.72–$2.74 per running worker-hour | Serverless fallback; confirm the endpoint's actual rate |
| Runpod A100 PCIe 80 GB Pod | Listed $1.59/hour on the main pricing page | A short, supervised development/benchmark session |
| Runpod RTX Pro 6000 96 GB Pod | Listed $2.09/hour | Alternative with more VRAM; benchmark compatibility and speed |
| Vast.ai marketplace | Dynamic listing price; no verified fixed 80 GB quote obtained | Compare live offers for controlled experiments after the baseline |

Sources: [Modal pricing](https://modal.com/pricing), [Runpod serverless billing](https://docs.runpod.io/serverless/pricing), [Runpod current pricing](https://www.runpod.io/pricing), [Vast.ai pricing](https://vast.ai/pricing). Runpod's main page and documentation differ slightly for A100 serverless; use $2.74/hour as a conservative planning figure, then record the actual quote. Availability, host RAM, storage, region and taxes matter as well as VRAM.

Modal advertises $30 monthly credits and three workspace seats on Starter. A payment method is required; check the credit in your workspace before relying on it. Its published base prices can increase with region selection. Choose an acceptable processing region before uploading outside testers' personal media. [Modal pricing](https://modal.com/pricing), [Modal billing](https://modal.com/docs/guide/billing).

### Does €1/hour mean paying while nobody generates?

For an ordinary on-demand GPU instance: yes, while it remains provisioned/running. One hour at €1/hour is €1 even if it spends most of that hour waiting. At that hypothetical rate, 24 hours costs €24 and 30 days costs €720. An hourly price can still be metered per second; it does not necessarily mean rounding each job up to a full hour. Stopped-instance storage can continue costing money. [Vast instance management](https://docs.vast.ai/guides/instances/manage-instances).

For serverless: configure zero minimum workers. GPU compute can stop billing after the worker scales down. Startup, model loading, generation and the warm/idle interval can be billable, and persistent storage can cost money between requests. An LLM tool call does not itself define the billing window. [Runpod billing details](https://docs.runpod.io/serverless/pricing), [Modal cold starts and idle resources](https://modal.com/docs/guide/cold-start).

### Initial GPU configuration

Use one A100 80 GB, one generation per worker, zero minimum workers and one maximum worker. Choose host memory and disk suitable for the full workflow, not only the main transformer. Cache the pinned weights before repeated tests; load the model once per worker lifecycle. Set a finite startup limit and job deadline; measure before tightening them.

LTX-2.5's published minimum is 32 GB VRAM, 32 GB system RAM and 100 GB free storage. Its recommended configuration is A100 80 GB or H100, 64 GB+ system RAM and 200 GB+ SSD. These are not a guarantee that every duration, resolution and checkpoint fits. [LTX system requirements](https://docs.ltx.io/open-source-model/getting-started/system-requirements).

After the 80 GB baseline, compare one supported 48 GB configuration. Quantization, offloading and tiling can change quality and speed. Use formats supported by that exact GPU and pipeline: for example, a ComfyUI-only checkpoint is not interchangeable with a native Python checkpoint, and Blackwell-specific quantization is not an A100 configuration. [LTX model files and compatibility](https://huggingface.co/Lightricks/LTX-2.5).

### A useful fallback: a managed model API

If packaging the model consumes the demo budget before a real clip works, temporarily plug a managed LTX API into the same backend adapter. This proves the application/MCP path, but custom serverless deployment remains an unfinished milestone. The official LTX-2.5 Fast image-to-video API lists $0.09 per output second at 720p: a supported six-second request is $0.54 before other charges. It does not offer 480p in that matrix; downsample for delivery. Check minimum purchase and account access separately. [LTX pricing](https://docs.ltx.io/pricing), [supported LTX-2.5 presets](https://docs.ltx.io/models/ltx-2-5).

## 5. The €20 demo budget

€20 is plausible for a focused private demo, especially if advertised credits are available. It is not a production budget or a guarantee of a large model-comparison campaign.

| Allocation | Cash ceiling | Scope |
|---|---:|---|
| Baseline setup and first real clip | €5 | Download/cache, one working workflow, inspect the output |
| Repeatability and shortlisted comparisons | €7 | Small paid generation batch after mocks pass |
| Serverless integration and recovery checks | €3 | Cold start, repeat request, cancellation/reconciliation |
| Storage, FX/tax and failure reserve | €5 | Leave room for setup errors and provider overhead |
| Total | €20 | No domain or commercial email purchase required for private demo |

Example arithmetic, not measured performance: Modal A100 GPU + four physical CPU cores + 64 GiB host RAM is approximately $3.20 per provisioned hour at published base rates. If startup is 90 seconds, rendering 180 seconds and warm idle 30 seconds, 300 billed seconds cost approximately $0.27. A failed run can still consume those resources. Formula inputs come from [Modal resource rates](https://modal.com/pricing).

Five seconds of output is not five seconds of GPU time. Count all billed time, including unsuccessful attempts. Track both provider resource cost before free credits and actual cash charged after credits; otherwise promotional credits hide whether subscriptions can be profitable.

Start Modal with a workspace usage cap at or below the credited amount and an out-of-pocket limit where available. Its usage budget is before credits, whereas its spend limit is after credits. Confirm those displayed values. Add your own conservative job-cost reservations, one-worker maximum and application kill switch. Stop new submissions before the remaining budget cannot cover one worst-case in-flight job. [Modal budgets](https://modal.com/docs/guide/budgets).

Do not promise a number of demos until you have measured the first successful job. If the first working setup costs more than €5, pause new GPU experiments and choose between the managed API fallback, a cheaper validated configuration, or a larger agreed budget.

## 6. Roadmap and release gates

Work is ordered by evidence, not a fixed calendar. At roughly 6–8 hours per person per week, use 10–14 weeks as an initial planning envelope for a small paid beta, then re-estimate after the proof of concept. The €20 cap applies to M0–M2 only. Later milestones need a separate operating and test budget.

| Milestone | Indicative timing | Deliverable | Gate to move forward |
|---|---|---|---|
| M0: scope and baseline | First 1–2 working sessions | Corrected setup docs, frozen demo contract, budget controls, reproducible model manifest | All three people understand the same supported input/output and can reproduce the mocks |
| M1: real GPU smoke test | Weeks 1–2 | One image + prompt creates a real MP4 on the selected GPU | File downloads and plays; cost/time recorded; repeat works |
| M2: hosted proof of concept | Weeks 2–4 | Oracle coordinator + LLM + hosted MCP + durable jobs + serverless GPU | Five consecutive valid jobs; private demo works with PCs off; cancellation, duplicate submit and restart behavior verified |
| M3: private web alpha | Weeks 5–7 | Accounts, upload, generation form, history, download and administrator view | Three real accounts have isolated data; ten submitted requests are queued correctly |
| M4: subscription beta | Weeks 8–10 | Subscription checkout, credits, quotas, refunds and billing reconciliation | Payment sandbox lifecycle and concurrency tests pass; per-video economics support plans |
| M5: small paid release | Weeks 11–14 | Production deployment, operational controls, recovery and limited paid access | Security and recovery gates pass; start with 10–20 invited users before expanding toward 100 |
| M6: quality and scale | After measured usage | Longer stories, upscaling, faster model profiles and more GPU workers | Each addition passes a separate quality/cost benchmark |

M0 can overlap PICNIC's access preparation. M1 must precede substantial GPU deployment automation. M2 must precede building paid plans around speculative quality. Development of the website can start against the stable mock contract once M2's interfaces are fixed.

### Exactly what belongs in the proof of concept

1. A versioned request accepting an uploaded image, story, fixed duration and orientation.
2. An actual GPU inference workflow, with pinned model files and dependencies.
3. A small LLM planning/tool-call step, validated against a direct baseline.
4. The existing four MCP operations backed by real persisted jobs.
5. A bounded async coordinator that survives client disconnects and process restarts.
6. Private image/output storage and a usable download path.
7. A real MP4 validator and recorded quality scores.
8. Spend controls and evidence of shutdown/scale-to-zero.
9. A repeatable deployment on Oracle; personal computers are not required.

Payments, full public registration, arbitrary 60-second generation, 1080p enhancement, audio editing and model training are later milestones. Silent delivery is an explicit first-demo choice; do not assume disabling output audio eliminates all audio-related model memory or compute.

### Output and duration contract

Deliver MP4/H.264, yuv420p, 24 fps, web playback metadata at the front of the file, and 480p-class dimensions: 854×480 landscape or 480×854 portrait. Start with one orientation and add the second after the first works. Preserve aspect ratio with documented padding/resizing; do not silently crop out the subject.

Keep internal generation dimensions separate from delivered dimensions. The chosen backend may require a larger resolution and then downsampling. A 480p download is not automatically cheaper if the model ran at 720p or 1080p. Persist both dimensions and their costs.

Native LTX documentation requires frame counts of 8n+1 and dimensions divisible by 32. At 24 fps, 121 generated frames can be trimmed to 120 delivered frames for exactly five seconds. Validate constraints against the pinned workflow, because a specific two-stage graph may impose additional rules. Explicitly set duration; do not use automatic duration for a fixed-credit demo. [LTX Python parameter reference](https://docs.ltx.io/open-source-model/integration-tools/pytorch-api).

## 7. How many tools are needed?

Four tools are enough to complete the proof of concept. Use six for the SaaS beta, and add upscaling later. Tool count is not a quality metric.

| Tool | Milestone | Contract and acceptance |
|---|---|---|
| create_video | M2; extend existing | Accepts a validated plan/image asset reference and returns a durable job ID quickly; a repeat of the same authorized request does not start another billable job |
| get_video_status | M2; extend existing | Returns real state, stage and safe error information; progress can be unknown rather than invented |
| get_video_result | M2; extend existing | Returns authorized asset/download metadata only after the output exists and passes validation |
| cancel_video | M2; extend existing | Removes queued work or requests provider cancellation; reports cancellation pending until confirmed |
| get_generation_capabilities | M3 | Returns supported model profiles, durations, ratios, output formats and feature limits from server configuration |
| estimate_video_cost | M4 | Returns an expiring quote bound to normalized parameters and server-calculated credit cost |
| upscale_video | M6 | Creates a separately quoted job with its own status/result; preserves the original asset |

Uploads, login, subscriptions, account deletion and billing webhooks are normal application endpoints. They do not need to be additional LLM tools. Tool inputs must not let the model choose another user's identity, alter credit balances, supply provider secrets or authorize extra workers.

Use typed request/response models. Add asset_id, output profile, model profile, seed and a versioned plan. Store user_id and request/idempotency context from the authenticated application, not from generated text. For the private CLI, use a configured team identity that maps to the same authorization checks.

The web API can expose create-upload, quote, create-job, list-jobs, job-status, cancel and result routes. Return HTTP 202 and your own job ID after validation/admission, even if planning has not yet started. Use that same job throughout planning and tool execution; do not create a second billable job when the planner calls create_video.

## 8. Job correctness and cost safety

Use explicit states: validating, planning, queued, submitted, running, postprocessing, succeeded, failed, cancel_requested, cancelled and timed_out. Keep provider state separate from your user-visible state. Completion means the output is validated and available, not simply that the provider said it finished.

Persist your job ID, provider attempt ID, attempt number, user, input/output keys, plan version, checkpoint/workflow revision, seed, timestamps, lease/heartbeat, quote and credit reservation. Failed attempts remain part of cost history.

Enforce these rules in code:

- A unique idempotency key is bound to one user and one normalized request; changing the payload under the same key is rejected.
- Reserve credit and create the queued job atomically; only workers with a valid lease may dispatch it.
- Use provider idempotency if supported. If submission times out ambiguously, reconcile using the saved request/attempt identity before resubmitting. If the provider cannot prove whether it accepted the request, surface the uncertainty for operator recovery rather than launching a blind duplicate.
- Retry known transient failures within a small explicit attempt and spend budget. Do not retry validation failures, OOM configuration errors or unsupported models automatically.
- A cancellation request is not proof the GPU stopped billing. Confirm terminal provider state and handle races with completion. Credit policy and actual provider cost remain separate.
- Restart recovery reconciles submitted/running jobs; it must not reset them to a new paid submission.
- Mark results available only after storage upload and MP4 validation finish; expire temporary files and abandoned uploads.
- Do not report fabricated percentages when the backend only exposes queued/running states.

Keep status polling in the application with backoff. Do not run a CPU-heavy LLM turn for every progress update. Limit planning output length, context size, execution time and tool steps; permit at most one bounded repair of invalid structured output before a clear error or deterministic fallback.

## 9. Testing and model-selection process

### A. Orchestrator tests: no GPU charges

Evaluate four configurations: direct validated workflow, current Gemma 3 12B, Gemma 3 4B and Qwen3 4B. A direct workflow provides the baseline for whether an LLM improves the prompt or just adds delay. Ollama advertises tool capability for Qwen3; Gemma 3's listed capabilities do not establish native tool-call support. Verify the actual installed model/template; a JSON planner with an allowlisted dispatcher is a legitimate fallback. [Qwen3 catalog](https://ollama.com/library/qwen3), [Gemma 3 catalog](https://ollama.com/library/gemma3).

Use 20 scenarios × 3 runs × 4 configurations = 240 mock-only cases. Include valid creation, multiple jobs, missing image, invalid duration, status/result timing, cancellation, unknown IDs, provider error, instruction injection, attempted credit changes and a request to create extra videos. Use the same scenarios and server-enforced limits. The direct baseline can reject ambiguity; it need not invent a story expansion.

Record schema validity, correct tool/arguments, preservation of duration and required story details, completion/error honesty, duplicate attempts, wall time and peak resident memory. Run models one at a time with realistic short context. Text-only candidates must receive the same supplied image description when comparing text planning; evaluate vision separately rather than pretending Qwen3 reads the image.

Suggested M2 gate: at least 57/60 cases handled correctly for the selected orchestrator; 60/60 respect authorization and spending invariants. These are small-sample gates, not production reliability estimates. Target planning p95 below 30 seconds on the actual VM, or explicitly accept a slower private demo; reduce model size if it starves the web/DB services.

Gemma 3 12B's listed download is about 8.1 GB; runtime memory also includes context, vision/runtime overhead and other processes. On a 12 GB CPU-only VM, measure headroom before cohosting the web application. A larger model being able to load does not prove useful concurrent throughput. [Gemma 3 model sizes](https://ollama.com/library/gemma3).

### B. Video tests: deliberately small paid batches

Keep LTX-2.5 as the lead candidate based on Mot1One's experience. Shortlist the exact Wan 2.2 configuration and exact Hunyuan model/checkpoint already tested; record the latter's full name rather than comparing an unspecified family. Do not download every model just to satisfy a matrix.

| Test round | Size | Purpose |
|---|---:|---|
| GPU smoke | 2 successful runs of baseline | Prove image conditioning, file creation and repeat execution |
| Initial comparison | 3 models × 3 reference scenarios = 9 clips | Eliminate clear quality, speed or memory failures |
| Finalist comparison | 2 finalists × 5 new scenarios × 2 seeds = 20 clips | Judge consistency and select a supported preset |
| Hosted acceptance | 5 consecutive jobs; reuse suitable benchmark jobs | Prove the integrated pipeline, not just a notebook |

Release each paid batch only after measuring the previous batch and checking remaining budget. Full 29-clip comparison may exceed €20 after setup/failed runs; complete the smaller screen for the demo and fund the rest separately. GPU credits do not change the underlying economics.

Use the same source images and requested actions. Include a cartoon character, a product, a human with consent, camera movement, object movement and a constrained two-action sequence. Compare matching delivered duration/resolution, record internal resolution, and permit model-specific valid sampling settings. Equal seeds across models do not create equivalent random samples.

For each clip, save model and code revision, GPU, host RAM, quantization, dimensions, frames, FPS, steps, seed, prompt/enhancement, cold/warm state, peak VRAM, startup/render/encode/upload time, actual provider cost and success/failure.

Two teammates independently score shuffled outputs from 1–5 for source identity, requested action, temporal stability, visual defects and camera/style adherence. Suggested quality gate: average at least 4/5 for identity and action, no critical defect, and at least 80% acceptable outputs on the finalist set. Keep all failed outputs in the record; do not select only the best seed.

Primary metric: total paid experiment cost divided by acceptable clips. Secondary metrics: cost per delivered video second, queue delay, warm/cold latency and failure rate. LLM performance and video-model performance are separate decisions.

### C. Integration, security and billing gates

| Gate | Test and expected result |
|---|---|
| Media correctness | ffprobe/decode checks codec, playable frames, duration, dimensions and pixel format; play on desktop and mobile |
| Input safety | Corrupt/oversized images, path tricks and unsupported media fail before GPU dispatch |
| Asset isolation | User A cannot read, generate from, cancel or download User B's assets/jobs, including guessed IDs |
| Duplicate submission | Double-click and repeated API request create one logical job and one credit reservation |
| Network uncertainty | Simulate timeout after provider acceptance; reconciliation avoids a duplicate generation |
| Process failure | Restart Oracle coordinator and GPU worker at defined stages; job reaches a truthful recoverable/terminal state |
| Cancellation | Test queued, running, completion-race and repeated cancel; no false claim of refunded GPU spend |
| Storage failure | Expired upload/download URL and failed output upload produce a recoverable error without revealing another asset |
| Credit races | Simultaneous jobs cannot spend the same available balance; failed jobs release reservation once |
| Payment events | Sandbox purchase, renewal, failed payment, cancellation, refund, duplicated/reordered events; no duplicate credit grants |
| Load | Mock 100 accounts and 10 simultaneous submissions first; validate responsiveness and per-user limits |
| Real concurrency | Test 2 real jobs, then 5, then 10 within a separate budget; count queue wait separately from render time |
| Recovery | Restore DB and required assets to a clean deployment, reconcile jobs and prove downloads still work |

Run existing unit/contract tests and lint on each PR. Run targeted integration tests for changed boundaries. Paid GPU tests are manually budgeted release checks, not an unrestricted test on every public pull request.

## 10. Accounts, subscriptions and credits

Name the customer allowance video credits rather than LLM tokens. Video cost primarily depends on generation duration, resolution, model profile, inference work and retries. A token meter for the short story prompt would not track that cost fairly.

Start with two subscription tiers sharing one video-quality profile. Differentiate monthly credits, queue priority or storage retention only after measuring demand. Begin with one active generation per user. Publish a quote before submission and make any later regeneration a new quoted action.

Use an integer credit ledger: grant, reserve, settle, release, refund and expire. Preserve an audit trail. Reserve at admission, settle the agreed price on successful valid delivery, and release for platform failure. Define the policy for queued versus already-running cancellation. The business may absorb a failed GPU bill; that does not justify corrupting the user's ledger.

For billing, use Stripe Checkout and Customer Portal as the initial integration candidate. Activate/renew entitlements from verified server-side events and payment status, not a browser success redirect. Store event IDs and grant-period identifiers to make processing idempotent. Handle out-of-order delivery with reconciliation. [Stripe subscription webhooks](https://docs.stripe.com/billing/subscriptions/webhooks).

Suggested data entities: users, sessions, assets, generation_jobs, generation_attempts, model_profiles, quotes, credit_ledger, credit_reservations, subscriptions, payment_events and audit_events. Django can own the application schema while the MCP adapter uses the same service boundary.

Do not set subscription prices from promotional GPU credits. Model a fully used plan using measured acceptable-clip cost, unsuccessful attempts, storage/downloads, payment fees, taxes, support and a margin reserve. As a sensitivity example, 100 users making 20 clips/month produce 2,000 clips: at €0.30 per accepted clip, generation alone is €600/month; at €0.70, €1,400/month. These are hypothetical scenarios, not forecasts or recommended prices.

## 11. Capacity: 100 users and 10 concurrent requests

One hundred registered accounts is not the same as one hundred simultaneous generations. Start with a queue and a global maximum of one GPU worker; increase only when demand and revenue justify it.

Illustration: each job occupies one warmed worker for three minutes, with no batching or new cold starts. Ten jobs arrive together:

| Workers | Jobs generating at once | Last of the 10 finishes after | Average completion time |
|---:|---:|---:|---:|
| 1 | 1 | 30 minutes | 16.5 minutes |
| 2 | 2 | 15 minutes | 9 minutes |
| 5 | 5 | 6 minutes | 4.5 minutes |
| 10 | 10 | 3 minutes | 3 minutes |

All four cases use 30 worker-minutes in this idealized calculation. Additional cold starts, idle time and different hardware utilization change real cost. Advertised provider concurrency is a quota, not a guarantee that ten requested GPUs are immediately available.

For ongoing traffic, worker count is driven by arrival rate × mean service time, with spare capacity for variability. One worker at three minutes/job has a theoretical ceiling of 20 jobs/hour, and should not be planned at 100% utilization. Measure p50/p95 queue and service times before promising completion times.

The Oracle LLM is another queue. A CPU planner taking 30 seconds per request can delay ten users before their GPU jobs even begin. Benchmark it under load; use a smaller model, direct fallback or separate planner hosting if necessary. Do not run ten copies of a 12B model on this VM.

## 12. DevOps plan for PICNIC

### Tool choices

| Tool | Job | When |
|---|---|---|
| Docker Compose | Run the web app, coordinator, MCP and PostgreSQL as a small deployment | Hosted PoC onward |
| GitHub Actions | Lint/test, build images, publish a release and deploy | Lightweight checks now; deployment after M1 |
| Terraform | Describe OCI network, security rules, buckets, IAM and VM references | Import existing resources after M1 |
| Ansible | Configure Ubuntu, users, firewall, Docker and service deployment consistently | M2–M3 |
| Caddy or equivalent reverse proxy | Public HTTPS and routing | Web alpha |
| Jenkins | No initial deployment | Reconsider only if a concrete requirement exceeds GitHub Actions |
| Kubernetes | No initial deployment | Reconsider only after multiple-node operations justify it |

Standard GitHub-hosted runners are free for public repositories; larger runners and excess storage have separate billing rules. Keep model weights and video outputs out of build artifacts. [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).

The Oracle VM is ARM64. Build/test the control images for linux/arm64. The GPU worker usually needs linux/amd64 plus NVIDIA/CUDA libraries. Maintain separate images and dependency locks. Do not force the worker to inherit the MCP project's Python 3.14 pin.

### Separate DevOps epic and feature backlog

| ID | Feature | Milestone / priority | Depends on | Done when |
|---|---|---|---|---|
| D1.1 | Individual cloud and VM identities | M0 / P0 | None | Each member has an individual identity/key, needed privileges and account recovery; shared login secrets are removed if currently used |
| D1.2 | Private access and network baseline | M0 / P0 | D1.1 | SSH/admin paths are restricted; Ollama, DB and MCP have no unauthenticated public route |
| D1.3 | Spend and quota controls | M0 / P0 | GPU account choice | Provider limits, one-worker cap, startup/job limits and stop procedure are recorded and tested |
| D2.1 | ARM control-service image | M2 / P0 | F1.1 | Image builds from a locked revision and starts on the Oracle VM |
| D2.2 | GPU worker image and model cache | M1–M2 / P0 | F2.1 | Pinned known workflow works on selected GPU; cached weights survive scale-down; image contains no secrets |
| D2.3 | Hosted shared MCP service | M2 / P0 | D2.1, F1.2 | All three members use the deployed service and a request completes with personal PCs offline |
| D2.4 | Private asset storage | M2 / P0 | F1.2 | Job-scoped upload/download works; retention, expiry and access denial are tested |
| D3.1 | OCI Terraform baseline | M2–M3 / P1 | D1.1, inventory | Existing resources are imported safely; reviewed plan causes no unexpected replacement; state access and concurrent applies are controlled |
| D3.2 | Repeatable VM configuration | M2–M3 / P1 | D2.1 | Ansible rerun is safe; users, firewall, services and directories converge without manual drift |
| D3.3 | PR checks and image publishing | M2 / P0 | F1.1, D2.1 | Tests/lint run on PRs; trusted branch builds immutable image tags; untrusted PRs receive no deploy/GPU secrets |
| D3.4 | Release, migration and rollback | M3 / P0 | D3.3, F5.1 | Versioned release deploys, health check passes, backward-compatible DB migrations are sequenced, previous app image can be restored |
| D4.1 | Domain, HTTPS and web routing | M3 / P0 | F5.1 | Website works over HTTPS with secure headers; internal ports remain private |
| D4.2 | Secret lifecycle | M3 / P0 | D1.1 | Application/provider/payment secrets are injected securely, redacted from logs and rotatable |
| D4.3 | Backup and restore | M3–M5 / P0 | PostgreSQL and assets | Encrypted off-VM backup restores to a clean environment; credentials, migrations and object references are covered |
| D4.4 | Operational monitoring | M3–M5 / P0 | F3.1 | Queue age, failures, spend, disk, RAM, provider health and backup freshness are visible |
| D4.5 | Controlled GPU scaling | M5 / P1 | F7.1 | Limits 1→2→5 are tested; ten-request queue behavior is measured; budget cap remains effective |
| D4.6 | Production capacity and recovery decision | M5 / P0 | F7.1, D4.3 | Team chooses acceptable downtime/recovery targets and funds capacity beyond free resources when needed |

Suggested private-alpha targets: backup at least daily, recover within four hours, and accept at most 24 hours of data loss only while using test credits. Before real payments, target substantially tighter credit/payment recovery, such as recoverable DB changes within 15 minutes, and prove event reconciliation. Choose and document feasible targets; a daily database copy alone is insufficient evidence for billing durability.

Oracle's current documentation lists 2 OCPU / 12 GB for the A1 Always Free allowance, combined 200 GB block storage and 20 GB object storage in the stated free-only configuration. Idle instances may be reclaimed and capacity may be unavailable. Verify your tenancy's actual entitlements and home region; do not assume the older 4 OCPU / 24 GB allowance. [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm).

Keep media retention bounded and database backups off the VM. Do not claim high availability from a single free instance. Review Tailscale plan eligibility and limits as this becomes a commercial service; public customers should not need Tailscale. [Tailscale plans](https://tailscale.com/pricing).

## 13. Security features by phase

Security that prevents unauthorized GPU spend starts in M0, not after the website.

| Phase | Required application behavior |
|---|---|
| Private PoC | Authenticated/private MCP, secret-free repository, tool allowlist, bounded inputs and budget, safe files, private assets |
| Web alpha | Per-user object/job authorization, secure session cookies, CSRF protection, rate limits, safe uploads, expiring downloads, administrator access control |
| Paid beta | Verified and replay-safe billing callbacks, credit race protection, audit trail, emergency stop, provider-result reconciliation |
| Paid release | Tested restore/rotation, dependency and container review, abuse/reporting and deletion flows, documented media processing and retention |

Use asset IDs rather than arbitrary URLs or local paths supplied by the LLM. Re-decode uploaded images, impose file/pixel limits and strip unnecessary metadata. If a provider must fetch a URL, generate a narrowly scoped expiring URL for an owned object; do not let prompts direct requests to internal network addresses. Workers execute a fixed workflow and cannot run arbitrary generated Python, shell or ComfyUI nodes.

If callbacks are used, verify the provider's supported signature/token and then confirm the job belongs to a recorded attempt. A polling coordinator avoids needing a public GPU callback for the PoC. Signed download links are bearer credentials: scope them narrowly and keep them out of logs.

For a public image/video service, include practical misuse controls, reporting, deletion and a product policy for uploaded likenesses and rights. Before paid launch, review the licenses of every actual checkpoint, text encoder, LoRA and upscaler. The LTX-2.5 model card identifies a community license and conditional commercial use; it is not a blanket permissive license for every component or redistribution scenario. [LTX model card](https://huggingface.co/Lightricks/LTX-2.5). Record the binding license review in the release feature rather than assuming an open repository grants all rights.

## 14. GitHub tracking setup

Use one GitHub Project connected to this repository. GitHub Projects provides board, table and roadmap views integrated with issues and pull requests. [GitHub Projects documentation](https://docs.github.com/en/issues/planning-and-tracking-with-projects/learning-about-projects/about-projects).

Represent an epic as a parent issue and each feature below as a linked issue/sub-issue. Use milestones M0–M6. One feature should deliver a demonstrable result; add small implementation checklists only when someone starts it.

| Field | Values |
|---|---|
| Status | Backlog, Ready, In progress, Review, Blocked, Done |
| Owner | justnevermark, Mot1One, PICNIC |
| Area | Application, Models, DevOps, Security, Billing |
| Priority | P0 required for that release; P1 improvement after the relevant P0 gate |
| Milestone | M0 through M6 |
| Size | S: roughly half–one day; M: one–three days; L: split before starting |
| Dependency | Blocking feature IDs |
| GPU budget | None, estimated amount, actual spent |

Create three views: full milestone roadmap, current work board and PICNIC-only DevOps board. Limit each person to one primary feature in progress. Hold one 30-minute weekly review: demonstrate work, record quality/cost evidence and choose the next Ready feature. Record decisions in the issue or repository so Discord is not the only history.

Feature issue template: problem/outcome; owner; milestone/priority; dependencies; scope; acceptance criteria; test evidence; GPU spend cap; deployment/recovery impact. Keep sensitive operational values out of public issues.

## 15. Application and model epics with feature backlog

All rows are proposed features, not claims of completed work. D-prefixed dependencies refer to PICNIC's separate backlog above.

| ID | Epic / feature | Owner | Milestone / priority | Depends on | Acceptance criteria |
|---|---|---|---|---|---|
| F1.1 | E1 Foundation: reproducible project setup | justnevermark | M0 / P0 | None | Sanitized agent committed; configuration documented; README/transport/Python mismatches resolved; current tests characterized |
| F1.2 | E1 Foundation: image and generation contract | justnevermark | M0 / P0 | F1.1 | Typed asset/plan/job models; five-second preset and one orientation; unsupported inputs fail before dispatch |
| F1.3 | E1 Foundation: project board and decision log | justnevermark | M0 / P0 | None | All features have one owner, milestone and acceptance criteria; first-week work is Ready |
| F2.1 | E2 Video baseline: reproducible workflow pack | Mot1One | M1 / P0 | F1.2 | Exact model/workflow, required files, versions, GPU/RAM and source test image recorded |
| F2.2 | E2 Video baseline: first real 480p output | Mot1One | M1 / P0 | F2.1, D1.3 | Two runs produce playable MP4s; actual costs, cold/warm time and VRAM captured |
| F2.3 | E2 Video baseline: budgeted model screen | Mot1One | M2 / P0 | F2.2 | Up to three known candidates tested with fixed scenarios; baseline decision justified |
| F2.4 | E2 Video baseline: finalist quality benchmark | Mot1One | M3 / P1 | F2.3 | Two-seed evaluation with blind scoring and all failures retained; funded separately if demo budget exhausted |
| F3.1 | E3 Reliable pipeline: durable jobs and attempts | justnevermark | M2 / P0 | F1.2 | Persisted state, leases and provider IDs; restart does not erase jobs |
| F3.2 | E3 Reliable pipeline: real provider adapter | justnevermark | M2 / P0 | F2.2, D2.2, F3.1 | Existing tool operations use hosted GPU jobs through a replaceable adapter |
| F3.3 | E3 Reliable pipeline: idempotency and reconciliation | justnevermark | M2 / P0 | F3.2 | Duplicate requests and ambiguous submissions cannot blindly cause duplicate spend |
| F3.4 | E3 Reliable pipeline: cancellation and retry policy | justnevermark | M2 / P0 | F3.3 | Queued/running cancellation, finite retries and terminal races produce truthful state |
| F3.5 | E3 Reliable pipeline: output delivery and expiry | justnevermark | M2 / P0 | D2.4, F3.2 | Only validated files become downloadable; expired assets are cleaned up predictably |
| F4.1 | E4 Orchestration: model evaluation harness | Mot1One | M2 / P0 | F1.2 | Mock scenarios compare direct/Gemma/Qwen configurations and produce reliability/memory/latency results |
| F4.2 | E4 Orchestration: bounded planner and dispatcher | justnevermark | M2 / P0 | F4.1, F3.2 | Story requirements become a validated plan; one authorized generation; no model-controlled credit changes |
| F4.3 | E4 Orchestration: prompt-fidelity evaluation | Mot1One | M2 / P0 | F4.2 | Compare raw versus enhanced prompt without changing required subject/action/duration; document failures |
| F4.4 | E4 Orchestration: small-model optimization | Mot1One | M3 / P1 | F4.1 | Selected VM model meets agreed latency/memory gate alongside web/DB services |
| F5.1 | E5 Web alpha: accounts and application skeleton | justnevermark | M3 / P0 | M2, D2.1 | Register/login/logout/reset/verification flow works; database migrations and admin view exist |
| F5.2 | E5 Web alpha: private upload and ownership | justnevermark | M3 / P0 | F5.1, D2.4 | Validated owned uploads; other users cannot access or reuse them |
| F5.3 | E5 Web alpha: generation and history UI | justnevermark | M3 / P0 | F5.2, F4.2 | Upload/story/duration form, queued/running/errors, cancellation, history and MP4 download work |
| F5.4 | E5 Web alpha: capability-driven presets | justnevermark | M3 / P0 | F2.3, F5.3 | UI and MCP advertise only tested presets; ten-second/second orientation added only after validation |
| F5.5 | E5 Web alpha: administrator recovery controls | justnevermark | M3 / P0 | F3.4, F5.1 | Admin can pause submissions, inspect attempts and reconcile stuck jobs with audit records |
| F6.1 | E6 Billing: measured credit pricing | justnevermark | M4 / P0 | F2.4 or sufficient measured sample | Versioned quote formula covers measured full-use plan costs; team accepts assumptions |
| F6.2 | E6 Billing: transactional credit ledger | justnevermark | M4 / P0 | F6.1, F3.3 | Reserve/settle/release/refund/expiry are auditable and concurrency-safe |
| F6.3 | E6 Billing: subscription checkout and portal | justnevermark | M4 / P0 | F5.1, F6.2 | Sandbox purchase, renewal, cancellation and failed payment update entitlements correctly |
| F6.4 | E6 Billing: webhook and refund reconciliation | justnevermark | M4 / P0 | F6.3 | Duplicated/reordered events do not double-grant credits; refund policy and support recovery tested |
| F6.5 | E6 Billing: user quotas and fairness | justnevermark | M4 / P0 | F6.2, F5.4 | Per-user queued/active limits and global capacity prevent one account monopolizing spend |
| F7.1 | E7 Release: concurrency and soak evaluation | Mot1One | M5 / P0 | F6.5, D4.4 | Mock 100-account/10-submit and staged real-job tests report queue, planning, GPU time and correctness |
| F7.2 | E7 Release: security and abuse controls | justnevermark | M5 / P0 | F5.2, F6.4, D4.2 | Ownership, injection, replay, rate-limit and secret-leak checks pass; reporting/deletion exist |
| F7.3 | E7 Release: license and product readiness | justnevermark | M5 / P0 | F2.1, F6.3 | Actual model/component licenses, processing regions, retention, billing terms and customer support are reviewed |
| F7.4 | E7 Release: invited paid launch | justnevermark | M5 / P0 | F7.1–F7.3, D4.3–D4.6 | Begin with 10–20 users; no known credit/data isolation defects; expand toward 100 using measured demand |
| F8.1 | E8 Expansion: lower-cost GPU profile | Mot1One | M6 / P1 | Stable baseline | One 48 GB/quantized profile compared on cost per acceptable clip, speed and quality |
| F8.2 | E8 Expansion: 1080p enhancement | Mot1One | M6 / P1 | Stable delivery | Compare native higher-resolution output against enhancement; score flicker, identity, detail and cost |
| F8.3 | E8 Expansion: upscale job integration | justnevermark | M6 / P1 | F8.2, F6.2 | Separate quoted upscale job, original retained, duration/audio sync preserved |
| F8.4 | E8 Expansion: longer story generation | justnevermark | M6 / P1 | Quality baseline, sufficient budget | Story/shot plan, continuity strategy and native multishot versus stitching benchmark; quote total cost first |
| F8.5 | E8 Expansion: audio and delivery options | Mot1One | M6 / P1 | Stable video profiles | Explicit sound/music/narration scope, rights, sync and cost validated before public exposure |

## 16. The next work session

justnevermark: take F1.1 and then F1.2. Preserve the backend abstraction, add the image asset contract and commit the sanitized VM agent. Keep the mock available.

Mot1One: take F2.1. Bring one exact LTX-2.5 image-to-video workflow that can be reproduced without manual edits, with its full model inventory and a short reference scenario.

PICNIC: take D1.1–D1.3, then D2.2 with Mot1One. Confirm GPU account eligibility, displayed credits, one-worker configuration and shutdown behavior before the first paid experiment.

The first shared milestone is concrete: a five-second real MP4 produced twice from the same documented pipeline, with the output files, measured time and actual cost available to all three teammates. Use that evidence to decide the next batch.

# AI Video Generator

An MCP-based AI video generation server built with **Python** and **FastMCP**.

The project is being developed incrementally, starting with a local proof-of-concept and eventually evolving into a remotely accessible, containerized AI video-generation service.

The initial goal is to evaluate local LLMs such as **Qwen3.5 27B** and **gpt-oss-20B** as agents capable of controlling an AI video-generation workflow through MCP tools.

---

## Project Goals

The project aims to provide an MCP interface for AI video generation, allowing an LLM to perform actions such as:

* Create a video from a prompt
* Check video-generation status
* Retrieve generated videos
* Cancel video-generation jobs
* Eventually work with different video-generation backends

The MCP interface should remain independent from the underlying video-generation implementation.

This allows the project to evolve from a local GPU-based prototype into a remotely deployed service without redesigning the MCP tools.

---

# Project setup

You should have installed python 3.14.7. You can download it from Python Install Manager here: https://www.python.org/downloads/

Install Bionic (the LM Studio agent app): https://lmstudio.ai/

Clone repository to your local machine

Open cloned repository folder with terminal and create local virtual environment:

```
py -m venv .venv
```

Run from root folder:

```
uv sync
```

Check that the server starts:

```
uv run python -m video_mcp.server
```

It should print the FastMCP banner and then sit waiting for input; stop it with
Ctrl+C. This only proves the server starts. Do **not** leave it running: the
transport is stdio, which means the MCP client launches its own copy of the
server and talks to it over that process's stdin/stdout. A server started by
hand in a terminal is not connected to anything.

## Connecting the server to Bionic

Add an MCP server in Bionic's settings with these values:

| Field | Value |
| --- | --- |
| Command | `uv run python -m video_mcp.server` |
| Working directory | your cloned repository folder |
| Env | `AI_VIDEO_MOCK_QUEUED_SECONDS` = `5`, `AI_VIDEO_MOCK_RUNNING_SECONDS` = `120` |

The command must run the server as a module (`-m video_mcp.server`) from the
project root. Pointing it at the script path instead (`python
video_mcp/server.py`) puts the `video_mcp/` folder on `sys.path` rather than the
project root, so `from video_mcp.models import ...` fails, the process dies on
startup, and the client reports `MCP error -32000: Connection closed`.

Bionic stores this as its own JSON (`servers: [...]`), not the `mcpServers`
shape used by most other MCP clients. `mcp.json` in this repository is the
portable version, for clients that read that format; adjust `cwd` to your own
folder.

The `env` values are optional and only control the mock timings. Without them
the job finishes about 10 seconds after it is created, which is too fast to
observe the `running` state.

To confirm it worked, ask the model in a new chat:

```
List every tool you have available, with their exact names.
```

You should get `create_video`, `get_video_status`, `get_video_result` and
`cancel_video`. If the tools are missing, check whether the server process is
actually running while Bionic is open:

```powershell
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like "*video_mcp*" }
```

Nothing listed means the client never started the server, or it crashed on
startup.

## Downloading a model

Change the model install folder to your bigger ssd

https://imgur.com/a/uZWjYU0

Search for qwen 3.5 27B GGUF and download the unsloth version

https://imgur.com/a/5F58WzX

(Both screenshots are from LM Studio; Bionic's model settings are equivalent.)

Note on hardware: Qwen3.5 27B at Q4 is about 17 GB. On a card with less VRAM
than that, most of the model runs on the CPU, and a single tool-calling turn
can take minutes. Check that the GPU is actually being used:

```powershell
nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv -l 2
```

## Testing that the LLM can drive the tools

In chat write:

```
Create a 10 second video of a futuristic city at night in 16:9.
```

It should call the create_video() tool.

The mock job does not finish instantly. With the env values above it stays
queued for 5 seconds and runs for 120, and only then reports `completed`. A
model that handles the workflow correctly will poll `get_video_status` and then
call `get_video_result`.

Raise `AI_VIDEO_MOCK_RUNNING_SECONDS` for scenarios that need a longer window,
such as cancelling a job while it is still running.

## Running the tests

```
uv run pytest
uv run ruff check .
```

# Architecture

The project will be developed in several stages.

### Current target architecture

```text
                 Bionic
                    │
             Local LLM model
          ┌─────────┴─────────┐
          │                   │
     Qwen3.5 27B        gpt-oss-20B
          │                   │
          └─────────┬─────────┘
                    │
                MCP Client
                    │
                  stdio
                    │
                    ▼
              FastMCP Server
                    │
                    ▼
             Video Service
                    │
                    ▼
            Local GPU / Backend
```

The LLM is responsible for understanding the user's request and deciding which MCP tools to use.

The actual video generation is performed by a separate video-generation backend.

---

# Roadmap

## Phase 1 — Local MVP / Proof of Concept

**Status: In progress** — mock backend and LLM evaluation done; real video generation not connected yet.

The first phase focuses entirely on proving that the concept works.

There will be:

* No Docker
* No HTTPS
* No remote deployment
* No Terraform
* No Ansible
* No Jenkins
* No VM

The MCP server will run locally using **stdio transport**.

The video-generation workload will initially use the GPU and other resources available on the developer's PC.

### Initial architecture

```text
Bionic
    │
    │ Local LLM
    ▼
MCP Client
    │
    │ stdio
    ▼
FastMCP Server
    │
    ▼
Video-generation tools
    │
    ▼
Developer PC GPU
```

### Initial MCP tools

The first version will provide a minimal set of tools, for example:

```text
create_video()
get_video_status()
get_video_result()
cancel_video()
```

The first implementation may use a mock/fake video backend.

This is intentional.

Before connecting an actual video-generation model, the project should establish that the selected LLM can reliably:

1. Understand the available MCP tools
2. Select the correct tool
3. Generate valid tool arguments
4. Handle returned job IDs
5. Check job status
6. Handle errors
7. Complete a multi-step video-generation workflow

### LLM evaluation

The initial models to evaluate are:

* Qwen3.5 27B
* gpt-oss-20B

Additional models may be tested later.

The models will be tested through **Bionic** using the same MCP server and the same tool definitions.

The goal is to determine which model provides the best combination of:

* Tool-calling reliability
* Reasoning
* Parameter accuracy
* Context handling
* Speed
* Resource consumption
* Error recovery
* Overall reliability as an MCP agent

---

# Phase 2 — Remote MVP

**Status: Planned**

Once the local proof-of-concept works, the MCP server will be adapted for remote access.

The transport will move from:

```text
stdio
```

to:

```text
Streamable HTTP
```

The service will eventually be exposed through:

```text
HTTPS
```

### Target architecture

```text
                Internet
                    │
                   HTTPS
                    │
                    ▼
             Streamable HTTP
                    │
                    ▼
              FastMCP Server
                    │
                    ▼
             Video Backend
                    │
                    ▼
              GPU / Compute
```

This phase introduces concerns that are not necessary during local development, including:

* HTTPS/TLS
* Authentication
* Authorization
* Secrets management
* Network security
* Request validation
* Logging
* Error handling
* Rate limiting
* Remote configuration

The goal is to make the MCP server usable remotely while keeping the underlying MCP tool interface stable.

---

# Phase 3 — Production MVP

**Status: Planned**

After the remote MVP has been validated, the application will be moved away from the developer's personal PC and deployed to dedicated infrastructure.

This phase introduces:

* Docker
* Virtual machines
* Dedicated GPU compute
* Persistent storage
* Environment configuration
* Service management

### Target architecture

```text
                    Internet
                       │
                      HTTPS
                       │
                       ▼
                 ┌───────────┐
                 │    VM     │
                 │           │
                 │ FastMCP   │
                 │ Server    │
                 └─────┬─────┘
                       │
                       ▼
                 Video Backend
                       │
                       ▼
                  GPU Compute
```

Docker will package the application and its Python dependencies into a reproducible environment.

The development environment and production environment should remain consistent as much as practical.

---

# Phase 4 — Infrastructure & Automation

**Status: Planned**

Once the application is running reliably on dedicated infrastructure, infrastructure automation and CI/CD will be introduced.

Potential technologies include:

* **Terraform** — infrastructure provisioning
* **Ansible** — server configuration and deployment
* **Jenkins** — CI/CD and deployment automation
* GitHub — source control and collaboration

### Target workflow

```text
Developer
    │
    ▼
GitHub
    │
    ▼
CI / Tests
    │
    ▼
Jenkins
    │
    ├── Terraform
    │       │
    │       ▼
    │     Infrastructure
    │
    └── Ansible
            │
            ▼
        VM / Services
            │
            ▼
          Docker
            │
            ▼
       FastMCP Server
            │
            ▼
       Video Backend
            │
            ▼
         GPU Worker
```

The purpose of this phase is to make the system reproducible, deployable, and maintainable rather than manually configured.

---

# Development Strategy

The project intentionally follows an incremental approach.

We do **not** want to solve infrastructure problems before the core application is proven.

The progression is:

```text
1. Prove the MCP concept
        ↓
2. Test local LLMs
        ↓
3. Connect real video generation
        ↓
4. Enable remote access
        ↓
5. Move to dedicated infrastructure
        ↓
6. Containerize
        ↓
7. Automate infrastructure and deployment
```

Each phase should produce a working system before the next layer of complexity is introduced.

---

# Technology Stack

## Initial

* Python
* FastMCP 4.x
* MCP
* Bionic (LM Studio agent app)
* Qwen3.5 27B
* gpt-oss-20B
* Local GPU

## Development

* `uv`
* `pyproject.toml`
* Python virtual environment
* Git
* GitHub
* pytest
* Ruff

## Later

* Streamable HTTP
* HTTPS
* Docker
* Virtual machines
* GPU infrastructure
* Terraform
* Ansible
* Jenkins

The exact video-generation model and backend will be selected after the initial MCP/LLM proof-of-concept.

---

# Project Structure

The project is expected to follow a structure similar to:

```text
AI-video-generator/
│
├── video_mcp/
│   ├── __init__.py
│   ├── server.py        MCP tool layer (thin)
│   ├── video.py         video-generation backend
│   └── models.py        request/response models
│
├── tests/
│   ├── conftest.py
│   ├── test_backend_config.py  timings read from the environment
│   ├── test_models.py          request validation and terminal states
│   ├── test_server.py          tool layer, via an in-memory MCP client
│   ├── test_stdio.py           real subprocess launch over stdio
│   └── test_video.py           backend job lifecycle
│
├── mcp.json
├── pyproject.toml
├── uv.lock
├── .gitignore
└── readme.md
```

The package is named `video_mcp`, not `mcp`. A local package called `mcp` shadows
the installed `mcp` SDK that FastMCP depends on, which breaks both the server and
the test suite when anything runs from the project root.

Subpackages (`tools/`, `services/`, `models/`) can be introduced later if the
flat modules grow. Docker-related files are not needed during Phase 1 and will
become relevant during the deployment phase.

---

# Development Environment

A dedicated Python environment will be used during development.

The project should not install its dependencies globally into the developer's system Python installation.

`uv` will be used to manage the project environment and dependencies.

For example:

```bash
uv sync
```

This creates/updates the project's isolated environment based on `pyproject.toml` and `uv.lock`.

The virtual environment should not be committed to Git.

---

# MCP Transport

## Phase 1

```text
stdio
```

stdio is used because the MCP server is running locally and the main objective is rapid development and testing.

## Phase 2+

```text
Streamable HTTP
```

Streamable HTTP will be introduced when the MCP server needs to be accessed remotely.

The MCP tools themselves should remain largely independent of the transport.

For example:

```python
@mcp.tool
def create_video(
    prompt: str,
    duration: int = 5,
    aspect_ratio: str = "16:9",
): ...
```

The same logical tool should be usable regardless of whether the MCP server is accessed through stdio or Streamable HTTP.

---

# Design Principles

### 1. Keep the MCP layer thin

MCP tools should expose a clean interface to the LLM.

Complex video-generation logic should live in services/backend components rather than directly inside the MCP tool implementation.

### 2. Keep the video backend replaceable

The MCP server should not be tightly coupled to one video-generation implementation.

Possible future backends include:

```text
Local video model
ComfyUI
Remote video-generation API
Dedicated GPU worker
```

### 3. Keep the LLM replaceable

The MCP server should not be designed around a specific LLM.

The same MCP tools should be testable with:

```text
Qwen3.5 27B
gpt-oss-20B
Other local models
Future models
```

### 4. Introduce infrastructure only when needed

The project will start locally and become progressively more production-oriented.

There is no need to introduce Docker, HTTPS, Terraform, Ansible, Jenkins, or cloud infrastructure before the core application has been validated.

---

# Current Status

**Phase 1 — Local MVP / Proof of Concept**

The current focus is:

* [x] Create project structure
* [x] Configure Python environment
* [x] Configure `pyproject.toml`
* [x] Install FastMCP 4.x
* [x] Create basic stdio MCP server
* [x] Implement `create_video()` mock tool
* [x] Implement `get_video_status()`, `get_video_result()`, `cancel_video()`
* [x] Mock backend with real job state and error cases
* [x] Test suite covering the backend and the tool layer
* [x] Connect MCP client to Bionic
* [x] Test Qwen3.5 27B
* [x] Test gpt-oss-20B
* [x] Compare tool-calling performance
* [ ] Select initial LLM
* [x] Select video-generation backend: LTX-2.5 on RunPod serverless
* [x] Connect real video generation

## Real video generation (RunPod)

The MCP server runs on the Oracle VM with `VIDEO_BACKEND=runpod`. It sends a
fixed LTX-2.5 ComfyUI workflow and the image to a RunPod serverless endpoint
that scales to zero, and saves the returned MP4. Setup and cost details:
[deploy/runpod/README.md](deploy/runpod/README.md) and
[deploy/vm/README.md](deploy/vm/README.md).

Make a video from the PC (uploads the image, waits, downloads the MP4 to
`data/outputs/`; needs `VM_HOST` and `VM_SSH_KEY` in `.env`):

```bash
uv run python scripts/generate_video.py data/incoming/photo.png "The character walks along the path. The camera tracks backward."
uv run python scripts/generate_video.py data/incoming/photo.png "..." --agent   # through Gemma
```

First measured job, 3 October 2026 (`photo.png`, cold worker):

| | |
| --- | --- |
| Output | 1024x576, 24 fps, 121 frames (5.04 s), H.264, silent, 1.8 MB |
| RunPod | 33 s waiting for the worker + 73 s rendering = 106 s billed |
| Cost | $0.037 (48 GB A40/A6000 tier), versus $0.54 per clip on the LTX API |
| Gemma 3 12B planning on the VM CPU | 7 min 48 s before `create_video` (not billed by RunPod) |

## Implemented tools

| Tool | Returns | Errors |
| --- | --- | --- |
| `list_video_models()` | the active backend's single preset | — |
| `register_image(filename)` / `register_image_base64(image_base64)` | asset normalized to a 1280x720 JPEG | not ~16:9 (within 2% is center-cropped), too small or large, not an image |
| `estimate_video_cost(plan)` | estimate, without dispatching | invalid plan or unknown asset |
| `create_video(plan)` | queued job with `job_id` | invalid plan, another job active, daily limit reached |
| `get_video_status(job_id)` | queued, running, completed, failed, cancelled or unknown | unknown `job_id` |
| `get_video_result(job_id)` | video path and download URL for a completed job | unknown `job_id`, job not completed yet |
| `cancel_video(job_id)` | cancelled job | unknown `job_id`, job already finished, backend cannot cancel |

`VIDEO_BACKEND` selects `runpod`, `comfy` (desktop ComfyUI with the paid LTX
API node) or `demo` (a prepared video, clearly labelled as not generated).

## LLM evaluation results

Each model was run through the same scenarios against the same mock backend.
Both **Qwen3.5 27B** and **gpt-oss-20B** passed all eight.

| # | Scenario | What it tests | Qwen3.5 27B | gpt-oss-20B |
| --- | --- | --- | --- | --- |
| 1 | "Create a 10 second video of a futuristic city at night in 16:9." | tool selection, argument accuracy | pass | pass |
| 2 | Ask for the video immediately after creating it | does it poll, or give up on the error | pass | pass |
| 3 | Ask for a 5 minute video | recovery from the duration limit | pass | pass |
| 4 | Ask about a job id that was never created | recovery from an unknown id | pass | pass |
| 5 | Create a video, then cancel it while it is running | multi-step state handling | pass | pass |
| 6 | Create two videos, then ask about the second | keeping two job ids apart | pass | pass |
| 7 | Ask for an unsupported aspect ratio | recovery from an invalid enum | pass | pass |
| 8 | Cancel a job that has already completed | terminal-state error handling | pass | pass |

Because both models pass every scenario, capability is not what separates them.
The useful comparison is in the softer measures, which should be recorded per
run: wall time and number of turns to completion, whether the job_id was carried
between calls without prompting, instruction adherence, memory use, and
overclaiming.

Overclaiming is worth watching closely. The tools return only `prompt`,
`duration`, `aspect_ratio`, `video_path` and `message` — nothing describing the
imagery. A model that reports what the video *looks like* has invented it. In
testing, Qwen3.5 27B did exactly that on one run, describing snow-covered pines
and a frozen stream that no tool ever returned, and dropped the mock/placeholder
caveat it had correctly relayed on an earlier run.

### Running the scenarios

Use a fresh chat for each scenario, or a previous job id in the context will be
what you are testing. Repeat each scenario about three times; tool calling is
nondeterministic and a single pass proves little.

Scenarios 2 and 5 need the mock job to still be running when you take your turn.
Raise `AI_VIDEO_MOCK_RUNNING_SECONDS` to 600 for those, and for scenario 5 tell
the model not to wait:

```
Create a 10 second video of a snowy forest. Do not wait for it to finish and do
not check its status — just give me the job id.
```

Otherwise the model polls the job to completion inside its own turn, and there
is never a running job left for you to cancel.


---

# Long-Term Vision

The final system is intended to become a remotely accessible MCP-based AI video-generation service.

The long-term architecture may look like:

```text
                    User / AI Agent
                          │
                          ▼
                    MCP Client
                          │
                       HTTPS
                          │
                          ▼
                 ┌─────────────────┐
                 │   FastMCP API    │
                 └────────┬────────┘
                          │
                    Job Management
                          │
                 ┌────────┴────────┐
                 │                 │
                 ▼                 ▼
           Video Queue        Other Services
                 │
                 ▼
            GPU Worker(s)
                 │
                 ▼
          Video Generation
                 │
                 ▼
          Storage / Result
```

The exact architecture will evolve as the project progresses.

The primary objective is to keep the system **modular, testable, replaceable, and deployable** while avoiding unnecessary complexity during the early development stages.

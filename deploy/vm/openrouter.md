# Move the VM planner to OpenRouter

The VM agent sends only the text prompt, MCP tool schemas and MCP results to
OpenRouter. Image bytes stay between the web app, VM agent, MCP service and
RunPod. The agent still validates tool arguments and the MCP service still
controls spending and submits `/run` jobs to RunPod.

## Account and model

1. Sign in to [OpenRouter](https://openrouter.ai/). Open [API Keys](https://openrouter.ai/settings/keys) and create a standard API key named `aivideo-oracle-vm`. Set a small monthly spending limit. Copy the key when it appears; OpenRouter cannot show its full value again.
2. Add a small amount on OpenRouter's [Credits page](https://openrouter.ai/credits) for paid requests. This is separate from RunPod credit and its API key.
3. Open the [Gemini 3.1 Flash Lite model page](https://openrouter.ai/google/gemini-3.1-flash-lite). The model slug used by this agent is `google/gemini-3.1-flash-lite`. Check its live price before use. The agent requires reliable JSON schema output for MCP decisions.

Do not use a *management* API key for inference. Do not put the key into Git,
RunPod endpoint settings, the web browser, or chat messages.

## VM configuration

On the Oracle VM, add these variables to the agent's existing private
`/home/ubuntu/mcp-agent/.env` file. Edit the file locally on the VM; do not
copy it into the repository or print its contents to the terminal.
For example, open it with `nano ~/mcp-agent/.env` after signing in as `ubuntu`.

```dotenv
OPENROUTER_API_KEY=<paste your standard OpenRouter API key>
OPENROUTER_MODEL=google/gemini-3.1-flash-lite
```

Keep the existing `AGENT_API_TOKEN` and `MCP_URL` values. The existing MCP
configuration keeps `RUNPOD_API_KEY` and `RUNPOD_ENDPOINT_ID`; the OpenRouter
key never goes to RunPod. Old `OLLAMA_MODEL` and `OLLAMA_URL` entries are no
longer used by the agent.

From your PC, deploy the agent code with the existing command:

```bash
deploy/vm/deploy.sh ubuntu@<vm-tailscale-ip> /path/to/ssh-key.key
```

That script deploys the Python files but not systemd units. From your PC, copy
the updated unit to the VM:

```bash
scp -i /path/to/ssh-key.key deploy/vm/agent/aivideo-agent.service ubuntu@<vm-tailscale-ip>:~/aivideo-agent.service
```

Then on the VM:

```bash
sudo install -m 644 ~/aivideo-agent.service /etc/systemd/system/aivideo-agent.service
sudo systemctl daemon-reload
sudo systemctl restart aivideo-agent
cd ~/mcp-agent && .venv/bin/python check-agent.py
```

`check-agent.py` calls `/readyz`, which verifies the OpenRouter key and MCP
connection without creating a video. To check the selected model without
spending RunPod credit, send a `/chat` prompt asking for a plain text answer.
For an end-to-end video check, use `check-agent.py --image ... --prompt ...` as
shown in [README.md](README.md); that creates a billable RunPod job.
The `/readyz` response must name `google/gemini-3.1-flash-lite` (or your selected
OpenRouter model). A response naming `LLM_Gemma3_12B` means the VM is still
running the previous agent code, even when `/healthz` reports `running`.

If the website runs on your PC, forward port 8100 from the PC to the VM in a
separate terminal before starting the website worker:

```bash
ssh -N -o ExitOnForwardFailure=yes -L 8100:127.0.0.1:8100 -i /path/to/ssh-key.key ubuntu@<vm-tailscale-ip>
```

On the PC, `curl http://127.0.0.1:8100/healthz` should then return
`{"status":"running"}`. If it does not, check `systemctl status aivideo-agent`
and `journalctl -u aivideo-agent -n 50 --no-pager` on the VM. A website and
worker that both run on the VM connect to port 8100 directly on VM localhost.
For a PC website, set its `AGENT_URL` to `http://127.0.0.1:8100` so the worker
uses the same local port as the SSH forward. Restart the local website and
worker after changing that setting.

After readiness and one real job succeed, you can stop and disable the old
`ollama` service if nothing else on the VM uses it:

```bash
sudo systemctl disable --now ollama
```

The Gemma-named text encoder in `deploy/runpod/start-cached.sh` is part of the
LTX video workflow on the GPU host. Leave that model cache in place.

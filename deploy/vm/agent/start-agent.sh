#!/bin/sh
set -eu

cd /home/ubuntu/mcp-agent

exec /home/ubuntu/mcp-agent/.venv/bin/python -m uvicorn agent:app \
    --host 127.0.0.1 \
    --port 8100 \
    --workers 1 \
    --timeout-graceful-shutdown 30

#!/bin/sh
set -eu

cd /home/ubuntu/ai-video-mcp

exec /home/ubuntu/ai-video-mcp/.venv/bin/python -m video_mcp.server

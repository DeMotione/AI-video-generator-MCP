Put this folder in your ComfyUI/custom_nodes

from ConfyUI Desktop terminal run this command to install missing python packages:
    python -m pip install -r custom_nodes/ltx_api/requirements.txt

Install FFmpeg, including ffprobe, and ensure both are on your PC’s PATH.
Put your LTX API key in ltx_api_key.txt beside the custom node’s __init__.py, or set LTX_API_KEY for the ComfyUI process. Restart ComfyUI.

In seperate git bash:
First things first for sanity check in git bash run: 
   curl http://127.0.0.1:8188/avg/health

if it returns 404 -> debug it.

If works then run:
   export COMFY_URL="http://127.0.0.1:8188"
   export PUBLIC_BASE_URL="https://YOUR-PC-TAILSCALE-HOSTNAME"
   uv run python -m video_mcp.server

*NOTE Set COMFY_URL to the actual address used by your ComfyUI Desktop instance. FastMCP uses port 8001. (if not you can check which port FastMCP is for you or in another bash you could run tailscale serve --bg 8001, don't remember if it was right).

This should create connection with VM.
In VM before running agent.py don't forget to set MCP_URL = "https://YOUR-PC-TAILSCALE-HOSTNAME/mcp"

once in agent.py in VM test registration and estimation without generating. In agent write paste this prompt:

Register photo.png using register_image. Using the returned asset_id,
estimate a five-second, 16:9 silent video with this prompt:
"The character walks slowly along the orchard path. The camera follows smoothly."
Show me the estimate. Do not call create_video yet. 

this prompt could be the test for paid LTX api key:

Create the video using that same plan. Submit it once, then poll
get_video_status every five seconds until completed or failed.
If completed, call get_video_result and show the download URL.
If the status is unknown, stop and report it without resubmitting.

then the output video suppose to be in this project folder, e. g., data/outputs
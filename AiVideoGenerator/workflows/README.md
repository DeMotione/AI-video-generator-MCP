# Connect your working ComfyUI workflow

This folder intentionally contains no invented LTX graph. Use the exact local-GPU workflow you already tested.

1. Open your working workflow in ComfyUI. Export it in **API format** (not the ordinary editor/layout JSON). Depending on the ComfyUI version, enable developer options to reveal the API export command.
2. Save it here as `local.json`. Make sure the workflow has an image loader, a positive prompt input, and an output node that saves an MP4 or WebM video. A preview-only output is insufficient.
3. From the AiVideoGenerator project root, inspect the export:

   ```bash
   uv run python backend/manage.py inspect_workflow workflows/local.json
   ```

4. Set the node IDs and input names in the root `.env`. Example only:

   ```dotenv
   COMFY_URL=http://127.0.0.1:8188
   COMFY_WORKFLOW_PATH=workflows/local.json
   COMFY_IMAGE_NODE_ID=12
   COMFY_IMAGE_INPUT=image
   COMFY_PROMPT_NODE_ID=18
   COMFY_PROMPT_INPUT=text
   COMFY_OUTPUT_NODE_ID=45
   COMFY_VIDEO_OUTPUT_KEY=
   ```

   Replace **12, 18, and 45** with the IDs in your graph. Some nodes use `prompt` rather than `text`. Choose the positive prompt node, not the negative prompt node. An optional output key selects a specific video output list. Auto-detection recognizes `videos`, `gifs`, `images`, and `avg_video`; exactly one saved `.mp4`, `.webm`, or `.mov` must match. MP4/WebM are recommended for browser playback; MOV playback depends on the browser and codec.

5. Start ComfyUI, then check the connection without rendering:

   ```bash
   uv run python backend/manage.py check_renderer
   ```

6. Restart the Django server and worker after changing `.env` or your workflow.

Only the mapped image and prompt are replaced. Your exported resolution, duration, frame count, model, seed, and other settings remain in effect. Use a five-second, 16:9 workflow if you want to preserve the original foundation preset. API exports can fix a seed that the editor normally changes between runs; change it in the workflow when you want different variations.

Use the local model workflow, not the earlier paid `AVG_LTX25` API node, if you want rendering on your PC's GPU. The website submits whichever graph you configure; a graph containing paid provider nodes will still call those providers.

This adapter expects ComfyUI's standard `/upload/image`, `/prompt`, `/history/{id}`, and `/view` HTTP routes. Custom output nodes with other response formats may need a small adapter change. Your existing graph was not supplied here, so a live GPU render still needs to be checked with it.

Your browser never connects to ComfyUI directly. The Django backend and worker do. For localhost, run all three processes on the PC. Later, a backend on a VM will need a private network route to that PC; `127.0.0.1` would then refer to the VM.

# Container start command for the LTX 2.5 ComfyUI worker on RunPod serverless.
#
# The endpoint's RunPod model cache holds Lightricks/LTX-2.5 on the host disk,
# where downloading it is not billed. The stock bootstrap ignores that cache
# and downloads ~40 GB on every cold start, which is billed GPU time. Linking
# the five files the workflow needs into ComfyUI's model folders makes the
# bootstrap's "already present" check skip those downloads. Anything missing
# from the cache is still downloaded, so a cache miss costs time, not a crash.
set -eu

cache="${RUNPOD_MODEL_CACHE:-/runpod-volume/huggingface-cache/hub}/models--Lightricks--LTX-2.5/snapshots"
models="${COMFY_MODEL_ROOT:-/comfyui/models}"

snapshot=""
if [ -n "${MODEL_REVISION:-}" ] && [ -d "$cache/$MODEL_REVISION" ]; then
    snapshot="$cache/$MODEL_REVISION/"
else
    snapshot="$(ls -d "$cache"/*/ 2>/dev/null | head -n 1 || true)"
fi

if [ -n "$snapshot" ]; then
    for file in \
        diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors \
        text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors \
        vae/ltx-2.5-video-vae-bf16.safetensors \
        vae/ltx-2.5-audio-vae-bf16.safetensors \
        latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors
    do
        if [ -e "$snapshot$file" ]; then
            mkdir -p "$models/$(dirname "$file")"
            ln -sfn "$snapshot$file" "$models/$file"
            echo "avg: using cached $file"
        else
            echo "avg: $file is not in the model cache; bootstrap will download it"
        fi
    done
else
    echo "avg: no RunPod model cache under $cache; bootstrap will download models"
fi

exec /start.sh

# Test Results — 2026-09-15

Manual end-to-end verification of the AI-video-generator MCP stack after
merging `upstream/main` (7 commits, 20 files).

## Automated suite

`uv run pytest -q` → **122 passed, 0 failed** (6.7s)

| File | Result |
|---|---|
| test_models.py | 46 passed |
| test_video.py | 33 passed |
| test_server.py | 23 passed |
| test_contract.py | 10 passed |
| test_backend_config.py | 6 passed |
| test_stdio.py | 4 passed |

Upstream shipped this suite at 83 passed / 39 failed. All 39 failures were one
bug in `test_models.py`: `pytest.raises(field_validator)` passes pydantic's
decorator where an exception class belongs, so pytest raised `TypeError` during
context-manager setup and those cases never executed. Swapped to
`ValidationError`; they now run and pass. The bug is still present upstream.

## Live pipeline

Verified over MCP-over-HTTP against the real server, then over Tailscale:

- `list_video_models`, `register_image`, `estimate_video_cost` — OK
- Validation rejects bad input cleanly: non-16:9 image, unknown filename,
  malformed UUID, `duration != 5`
- MCP handshake over `https://desktop-75m5q04.tail11535b.ts.net/mcp` — 6 tools
- ComfyUI `/avg/health` → `ready: true`, preset `ltx25-fast-5s-16x9-v1`

## Generation timings

Two billed renders via LTX `ltx-2-5-fast`, 1280×720, 24fps:

| Job | Submit → file on disk | Size |
|---|---|---|
| 57c18144 | **23s** | 0.13 MB |
| c6f79a45 | **42s** | 1.71 MB |

Both delivered exactly 5.000000s / 120 frames. Cost $0.54 each ($0.09/sec ×
6 generated seconds); the 6th second is trimmed by ffmpeg and discarded, so
~17% of every charge is thrown away.

A third submission failed at 401 before the real API key was installed —
`provider_id: null`, not billed.

## Overall

The pipeline works end to end: MCP tool call → ComfyUI → `AVG_LTX25` → LTX API
→ ffmpeg trim → mp4 on disk. Generation is fast (under a minute), validation is
strict and fails with useful messages, and the per-job journal makes retries
idempotent so polling can't double-bill.

Not yet exercised: the Oracle VM (`llm-gemma3-12b`) as an MCP client. Transport
is proven — the tailnet endpoint completes a full handshake — but `agent.py`
has never run against it.

## Known issues

1. **`photo.png` can never register.** It is 1672×941; `video.py` requires
   `width*9 == height*16` exactly. Width 1672 is not divisible by 16, so no
   integer height works. Cropped to 1664×936 as `photo_16x9.png`.
2. **`/avg/health` reports `ready: true` with a placeholder key.** `readiness()`
   only checks the key is non-empty, never that it authenticates.
3. **Auth failures are reported as possibly billed.** The node wraps every
   submission exception in "may already be billed", so a 401 (definitely free)
   looks like a timeout (possibly charged).
4. **A failed submission bricks its job_id.** The journal is written before the
   API call, so a retry finds `provider_id: null` and refuses forever.
5. **`estimate_video_cost` computes nothing.** `VideoEstimate()` returns a
   hardcoded $0.54. Correct only while duration and resolution stay locked.

# RunPod: dashboard steps only

The code installs the lightweight worker automatically. You do not need Git, chmod or repeated Terminal setup commands.

1. Create/start an **A40 48 GB** Pod using a **Python 3.11+ NVIDIA PyTorch/CUDA template**. Upstream reports roughly 44 GB generation VRAM before scorer overhead: a 48 GB A40 may still run out of memory. No real generation has been validated on it.
2. Attach your global/network volume at **`/workspace`**. This preserves repository files, dependencies and any provisioned models/media. Container disk is disposable; deleting a Pod can remove it. Persistent storage can cost money even when GPU compute is stopped.
3. Add **HTTP port `8091`** in the Pod settings.
4. Add **TCP port `22`** if your chosen template supports SSH. This bootstrap starts the worker only; it does not install or start SSH. Keep the template's SSH service configuration if you need it.
5. Add **`UGC_REMOTE_API_KEY`** as a private, nonempty environment variable. Keep a secure copy for the controller. Do not paste the value in chat.
6. Paste this exact **Container Start Command**:

   ```bash
   bash -lc 'set -o pipefail; curl -fsSL --retry 3 https://raw.githubusercontent.com/alejousaky-maker/Projectreview/main/project-review-ugc/remote_worker/runpod_bootstrap.sh | bash'
   ```

7. Save/restart the Pod. Inspect the logs: expect `[bootstrap]` messages followed by `[worker] Starting authenticated worker on HTTP port 8091`. The command uses HTTPS ZIP downloads, never `git clone` or `chmod`.
8. Open the **8091 HTTP service** from the Connect panel. The browser has no Bearer header, so **Unauthorized is expected**. Use the controller's connection test to authenticate.
9. Copy the service URL, typically `https://<POD_ID>-8091.proxy.runpod.net` (no `/health` suffix).
10. In your **controller app's environment settings**, set `UGC_REMOTE_API_URL` to that URL and `UGC_REMOTE_API_KEY` to the same worker key. For ElevenLabs add `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` and optionally `ELEVENLABS_MODEL_ID=eleven_multilingual_v2`. Save/restart the controller.
11. In the studio click **Test GPU Connection**. The setup page shows worker, CUDA, models and persona status. A connected worker is not proof that video generation is ready.

## What works automatically and what remains missing

Bootstrap installs only the small controller/worker dependencies. It updates application source from the repository ZIP while preserving `.env`, persona configuration/media, dependencies, models and outputs. Dependency wheels are first installed on container `/tmp`, then copied to the volume without chmod/copystat. No code editing or chmod is required on resets. It does not install the external CUDA model stack or download huge models. Reference media and model weights are still absent from this repository. Real generation remains blocked until they are provisioned; the status panel reports this clearly. Adding a GPU alone does not remove that blocker. See README for the exact upstream asset inventory.

Only set `UGC_MODELS_DIR`, `UGC_PROJECTS_DIR`, `UGC_ML_ENV_PYTHON`, `UGC_SYNCNET_WEIGHTS` or `WHISPER_URL` in RunPod when those assets/interpreter/services actually exist. The worker checks them; setting paths does not provision anything. ElevenLabs normally runs on the controller; its key is not needed on RunPod when the controller sends prepared audio.

## Manual versus Auto

**Manual** is the default. Start and stop the Pod in the RunPod dashboard. Closing a browser tab does **not** stop billing. To stop, select your Pod and click **Stop**; verify its status. Avoid **Terminate** unless you intend to delete it and understand which storage survives.

**Auto** is optional: add `RUNPOD_API_KEY` and `RUNPOD_POD_ID` only to the controller. Set `RUNPOD_IDLE_SHUTDOWN_MINUTES=5` and `RUNPOD_MAX_SESSION_MINUTES=30`. Then explicitly select Auto in the studio. It starts the configured existing Pod when a generation job needs it, reuses it, and stops it on idle or at the hard session limit (even if a job is running). Jobs and session deadlines persist. Start/stop events are logged. The controller must remain running for its timer to operate. Normal controller shutdown attempts a stop; process kills, host outages, API outages or revoked credentials can prevent that. Always verify the Pod stopped in RunPod; these are application safety controls, not a billing guarantee. Do not mix manual and auto jobs on the same Pod concurrently.

## Troubleshooting

- **ERR_CONNECTION_RESET / worker offline:** confirm the Pod is Running, HTTP 8091 is exposed, and the start command is saved. Read Container Logs for missing Python, missing key, dependency download failures, or port conflicts. Restart after fixing dashboard settings. Models missing should not prevent the health API from starting.
- **`/health` says Unauthorized:** expected when opened directly in a browser. Use Test GPU Connection. If that rejects authentication, check the keys match exactly and restart after changing them.
- **ZIP download fails:** ensure the repository is publicly reachable and GitHub/raw/codeload HTTPS traffic is allowed. Never disable TLS verification.
- **Volume permissions:** this startup does not need executable bits. Python files and shell scripts must still be readable, and `/workspace` must be writable. If the volume is read-only, fix the volume attachment in RunPod.
- **Port occupied:** stop the previous worker or restart the Pod; the entrypoint reports a clear error rather than launching a duplicate.
- **CUDA not detected:** use a GPU CUDA/PyTorch template and set `UGC_ML_ENV_PYTHON` only if a separate functioning ML environment is installed. Controller readiness does not imply CUDA readiness.

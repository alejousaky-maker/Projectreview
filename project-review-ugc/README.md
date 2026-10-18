# Project Review UGC Studio

A working FastAPI controller, minimal browser studio, asynchronous disk-backed jobs, script previews, local upstream adapter, authenticated remote GPU worker, and FFmpeg editor. No creator footage has been generated in this environment.

## Mac install — first time in Terminal

1. Open **Terminal** using Spotlight (Command + Space, type Terminal).
2. Type `cd `, drag the `project-review-ugc` folder into Terminal, then press Return.
3. Run `./setup.sh`. This installs the lightweight controller, not huge models.
4. Activate the environment with `source .venv/bin/activate`, then run `python doctor.py`.
5. Add your creator's head-and-shoulders photo as `personas/project_review/reference.jpg` and a clean 3–15 second single-speaker recording as `reference.wav`. Do not use empty placeholder files. Missing media does not block the UI.
6. Start with `uvicorn app:app --host 0.0.0.0 --port 8090 --workers 1`.
7. On your own computer, open `http://localhost:8090`. In cloud onboarding the app is validated through internal HTTP requests; the onboarding UI does not provide a web preview.

Choose **Preview script only** to test without a GPU. Dry runs have status `dry_run` and never show a video. Generate video jobs fail with a clear setup error until a backend and persona are usable. Durations are speech estimates, not guarantees.

## Backend setup

Copy `.env.example` to `.env` and edit it locally. Never commit secrets. The optional LLM URL must be the full OpenAI-compatible chat-completions endpoint; set its model and key. Invalid/unavailable LLM responses fall back to deterministic copy. Deterministic copy is a brand-safe template, not an intelligent interpretation of arbitrary topics or every style/tone; use an LLM for bespoke scripts.

On a Mac without NVIDIA, the controller/UI/editor works, but upstream CUDA generation does not. Supply `UGC_REMOTE_API_URL` and `UGC_REMOTE_API_KEY` pointing at your own worker. The worker has its own provisioned persona image and models. The controller sends the exact script and optional prepared TTS audio over authenticated HTTPS; it does not upload persona photos. Transport private worker traffic over HTTPS or a trusted private network. The controller itself is intended for trusted use, with one process; add deployment authentication and durable queue infrastructure before exposing it publicly.

On an NVIDIA worker run `./setup.sh --gpu` to install upstream packages in a separate `.gpu-venv`. Set `UGC_ML_ENV_PYTHON` to that environment's absolute Python path. Upstream requirements are unpinned and broad; dependency resolution and CUDA compatibility need validation on the chosen GPU image. No weights download automatically during setup.

Required external assets, from upstream `factory/config.py`:

- `$UGC_PROJECTS_DIR/ID-LoRA/ID-LoRA-2.3/scripts/inference_two_stage_hq.py` and its own dependencies.
- `$UGC_MODELS_DIR/ltx-2.3/ltx-2.3-22b-dev.safetensors` and `id-lora-talkvid/lora_weights.safetensors`.
- `$UGC_PROJECTS_DIR/ComfyUI/models/text_encoders/comfy_gemma_3_12B_it`, `upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors`, and `loras/ltx-2.3-22b-distilled-lora-384.safetensors`.
- SyncNet original `syncnet_python` package and `syncnet_v2.model` (set `UGC_SYNCNET_WEIGHTS`), InsightFace buffalo_l and CUDA ONNX runtime.
- A Whisper server at `WHISPER_URL` exposing `POST /transcribe`, or upstream local Whisper fallbacks; additional scorer models as described in the upstream README (NISQA, ECAPA, UTMOS, LPIPS, RAFT, DINOv2).

Upstream reports approximately **44 GB generation VRAM** for the 22B bf16 model, before scorer contention. This machine has no NVIDIA GPU and cannot validate that stack. Main-path speech is generated jointly by LTX; external TTS is not required. ComfyUI folders hold weights; a running ComfyUI server is not required for our adapter. Optional Anthropic scene description is not required.

The exact inspected runner is `python examples/run_persona_example.py --persona-dir <path> --scripts <json-list> --best-of 1 --frames 121 --gpu 0 --output <directory>`. We invoke it without shell interpolation, keep upstream unchanged, capture stdout/stderr/exit code, and isolate candidate outputs per job. Its revision is pinned in `scripts/upstream-revision.txt`. Its gate may retain best-effort takes after retries: existence of a final video does not certify quality. Inspect the gate report in stdout before publication.

## Generic remote worker

`remote_worker/Dockerfile` uses an NVIDIA PyTorch CUDA image. Build from this project directory, mount model/project folders and persona media, set the model paths and worker key, and expose port 8091 behind HTTPS. `bash remote_worker/start.sh` starts the authenticated API without requiring executable permissions. Docker/GPU image installation has not been tested here. Provider-specific RunPod/Vast/Modal/Lambda deployment is intentionally separate from the HTTP contract.

Worker API: authenticated `POST /generate`, poll `GET /jobs/{job_id}`, then download `GET /videos/{job_id}`. Use the same nonempty key on worker and controller. No key is required for local script preview. The worker fails closed if its key is missing. Remote jobs use the controller-built script, avoiding divergent script regeneration.

## Editing, captions and brand accuracy

Upstream gates, trims and concatenates generated segments. The wrapper editor accepts one or more clips, normalizes audio, crops/scales to 1080×1920, concatenates, optionally mixes music and burns short captions. Caption timing uses word-weighted estimates over actual duration, not forced alignment; review timing or integrate Whisper alignment before publishing. Trusted Python callers can pass music to `editor.edit`; the public generation endpoint rejects filesystem music paths.

Default scene bible deliberately uses no product props, avoiding fabricated product details. `config.BRAND_RULES` encodes all three product types, rigid adhesive NFC discs, compact stands, no invented QR, pay once/no subscription and one-tap Google routing. Real product depiction needs supplied product references and human review; this talking-head upstream does not guarantee accurate product rendering. Testimonial styles must never fabricate personal experience.

## API and files

`GET /health`, `POST /generate` (202), `GET /jobs/{id}`, `GET /videos/{id}`. Requests support topic, audience, business_type, style, tone, duration (15–35), cta_style, persona, backend, best_of, frames, gpu, captions, dry_run. Output is `outputs/<job_id>/final.mp4`. Jobs and errors persist as `jobs/<job_id>.json`; interrupted jobs fail clearly at restart. A completed job requires a real, nonempty video with a video stream and positive duration confirmed by FFprobe. Threads are suitable for one-process local use, not a multi-user production queue.

```
project-review-ugc/
├── app.py / web.html
├── generate.py / script_builder.py / backend_router.py
├── config.py / doctor.py / upstream_adapter.py / editor.py
├── setup.sh / requirements.txt / .env.example
├── README.md / CODEX.md
├── personas/project_review/ (persona.json, scene_bible.json, MEDIA_REQUIRED.md)
├── remote_worker/ (Dockerfile, worker.py, requirements.txt, start.sh)
├── tests/test_app.py
├── scripts/upstream-revision.txt
├── jobs/ / outputs/
└── vendor/ugc-factory-core/ (unchanged upstream checkout)
```

## Troubleshooting

- **xcode-select missing:** run `xcode-select --install`, finish Apple's installer and retry setup.
- **git missing:** Apple Command Line Tools include git; on Linux install your distribution's git package.
- **Python missing:** install Python 3.11+ from python.org, reopen Terminal and retry.
- **FFmpeg missing:** on Mac install Homebrew then `brew install ffmpeg`; on Debian/Ubuntu install the ffmpeg package. FFprobe is also required.
- **CUDA missing / no NVIDIA GPU:** use script preview and configure a remote NVIDIA worker; Apple MPS is not a confirmed upstream backend.
- **Persona incomplete:** provide the two real reference media files at the exact documented paths. Filename/size validation does not certify media quality.
- **Missing model weights:** doctor lists missing generation paths; install authorized upstream assets into configured model folders. Do not download 22B weights onto a small controller machine.
- **Upstream errors:** inspect `outputs/<job_id>/stdout.log` and `stderr.log`, validate the separate GPU Python environment and upstream README; do not disable gate checks to hide failures.
- **Worker 401/503:** configure matching nonempty remote API keys in each machine's `.env`. Do not paste keys into chat.

Run checks with `.venv/bin/python -m unittest discover -s tests -v`. Editor tests use clearly synthetic color/tone fixtures solely to verify FFmpeg, never as generated UGC footage.


## RunPod automatic startup and voice

See [RUNPOD_SETUP.md](RUNPOD_SETUP.md) for the single dashboard bootstrap command. Startup reuses a working .venv Python or falls back to system Python, installing only missing lightweight dependencies into persistent `.worker-deps`. No executable permissions or Git metadata are required. Keep one worker/controller process per directory.

The studio now has persona/voice selection, Manual/Auto GPU mode, Test GPU Connection, stage status, video preview and download. `/setup` shows configuration presence and live authenticated worker status without exposing keys. `/personas`, `POST /gpu/test` and `/gpu/status` power these controls through the controller backend. The browser never contacts RunPod directly.

ElevenLabs is preferred; use `ELEVENLABS_API_KEY`, `ELEVENLABS_VOICE_ID` and optional `ELEVENLABS_MODEL_ID`. Persona JSON supports `display_name`, `voice_provider`, `voice_id` and `enabled`. Voice output is stored in `outputs/<job_id>/audio/`, normalized to 48 kHz WAV and sent to the worker. Select Persona reference to avoid external TTS or eSpeak for open-source speech (requires `espeak-ng` installed on the controller). Mock audio exists only in the test helper and cannot be selected for real generation.

**Upstream compatibility:** supplied TTS audio replaces the reference voice only in a job-local persona copy. LTX still generates audio/video jointly; this is voice conditioning, not a deterministic ElevenLabs soundtrack or an audio-driven lip-sync model. We do not silently replace generated speech, claim exact TTS sync, or modify upstream. Exact spoken-audio lip sync requires a separately validated audio-driven backend. Upstream QC may keep best-effort segments; review its logs. Captions use approximate timing.

`runpod_manager.py` supports the RunPod REST API for existing Pod status/start/stop, health wait, persistent session deadline, idle stop, maximum-session stop and normal-shutdown stop. API calls are mocked in tests; no actual RunPod lifecycle or paid generation has been tested. No RunPod API key is needed in Manual mode. Auto mode requires explicit UI selection and credentials. The timers depend on a live controller and functioning RunPod API; always inspect billing/Pod status in the dashboard after failures.

Worker `/health` reports hardware and prerequisite presence independently. `generation_ready` stays false because no real GPU run has been certified; `prerequisites_ready` reports static checks only. Model presence cannot establish checkpoint compatibility, adequate VRAM, valid weights or healthy external transcription.

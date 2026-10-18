Use the existing isolated checkout; do not create a worktree unless requested.
Run ./setup.sh for controller dependencies. Use .venv/bin/python -m unittest discover -s tests.
Start one controller process with .venv/bin/uvicorn app:app --host 0.0.0.0 --port 8090.
Keep vendor/ugc-factory-core unchanged. Adapt its documented CLI, never invent flags.
Never mark a job completed without a probed, nonempty real MP4.
No model downloads without an explicit decision; report actual hardware and asset blockers.
Do not commit .env, creator media, jobs or outputs. Never log secret values.

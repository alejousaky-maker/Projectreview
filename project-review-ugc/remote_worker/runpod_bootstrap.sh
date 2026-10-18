#!/usr/bin/env bash
set -euo pipefail
trap 'echo "[bootstrap] ERROR: startup failed at line $LINENO; inspect the preceding log message" >&2' ERR
bootstrap_key="${UGC_REMOTE_API_KEY:-}"
[[ -n "${bootstrap_key//[[:space:]]/}" ]] || { echo '[bootstrap] ERROR: Add UGC_REMOTE_API_KEY to RunPod environment variables' >&2; exit 1; }
cd /workspace
command -v python3 >/dev/null || { echo '[bootstrap] ERROR: Choose a Python 3.11+ CUDA/PyTorch template' >&2; exit 1; }
python3 -c 'import sys; assert sys.version_info >= (3,11), "Choose a Python 3.11+ CUDA/PyTorch template"'
echo '[bootstrap] Downloading Projectreview main ZIP (no Git or chmod required)'
  python3 - <<'DOWNLOAD'
import pathlib,shutil,tempfile,urllib.request,zipfile
workspace=pathlib.Path('/workspace')
with tempfile.TemporaryDirectory(prefix='.projectreview-download-',dir=workspace) as tmp:
    archive=pathlib.Path(tmp)/'source.zip'
    urllib.request.urlretrieve('https://github.com/alejousaky-maker/Projectreview/archive/refs/heads/main.zip',archive)
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            path=pathlib.PurePosixPath(item.filename)
            if path.is_absolute() or '..' in path.parts or not path.parts or path.parts[0]!='Projectreview-main':
                raise SystemExit('Unsafe or unexpected repository ZIP layout')
        source.extractall(tmp)
    extracted=pathlib.Path(tmp)/'Projectreview-main'
    if not (extracted/'project-review-ugc/remote_worker/start.sh').is_file():raise SystemExit('Repository ZIP has no worker startup script')
    destination=workspace/'Projectreview'
    if not destination.exists():
        shutil.move(str(extracted),str(destination))
    else:
        # Update only published source; never delete persistent or user-provided data.
        for source in extracted.rglob('*'):
            if not source.is_file():continue
            relative=source.relative_to(extracted)
            target=destination/relative
            if target.exists() and ('personas' in relative.parts or source.name=='.env'):continue
            if target.is_symlink() or not target.resolve().is_relative_to(destination.resolve()):
                raise SystemExit('Refusing to overwrite a source path outside the checkout')
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,target)
DOWNLOAD
echo '[bootstrap] Source ready; persistent models, persona media and secrets preserved'
cd /workspace/Projectreview/project-review-ugc
[[ -f remote_worker/start.sh ]] || { echo '[bootstrap] ERROR: Existing Projectreview is incomplete; use a complete checkout' >&2; exit 1; }
exec bash remote_worker/start.sh

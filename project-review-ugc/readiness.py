"""Conservative prerequisites, separate from proof of successful generation."""
import importlib.util
import os
import shutil
import subprocess
import sys
from config import UPSTREAM
from doctor import report
from personas import list_personas
from voice import configured

def worker_status():
    machine=report();gpu=machine['gpu'];gpu_name=None
    if gpu['cuda']:
        try:
            import torch
            gpu_name=torch.cuda.get_device_name(0)
        except Exception:pass
    if not gpu_name and shutil.which('nvidia-smi'):
        try:
            gpu_name=subprocess.run(['nvidia-smi','--query-gpu=name','--format=csv,noheader'],capture_output=True,text=True,timeout=5).stdout.strip().split('\n')[0] or None
        except (OSError,subprocess.TimeoutExpired):pass
    upstream=(UPSTREAM/'examples/run_persona_example.py').is_file()
    # Check the actual ML interpreter, not just the lightweight controller environment.
    python=os.getenv('UGC_ML_ENV_PYTHON',sys.executable)
    check="import importlib.util,json; print(json.dumps([m for m in ['torch','numpy','scipy','cv2','soundfile','PIL','insightface','onnxruntime','python_speech_features','syncnet_python','torchvision','lpips','speechbrain','pandas','huggingface_hub','requests','yaml'] if importlib.util.find_spec(m) is None]))"
    try:
        import json
        process=subprocess.run([python,'-c',check],capture_output=True,text=True,timeout=20)
        packages=json.loads(process.stdout) if process.returncode==0 else ['working ML interpreter']
    except (OSError,ValueError,subprocess.TimeoutExpired):packages=['working ML interpreter']
    assets=list(machine['missing_generation_assets'])
    from pathlib import Path
    models=Path(os.getenv('UGC_MODELS_DIR',str(Path.home()/'models'))).expanduser()
    sync=Path(os.getenv('UGC_SYNCNET_WEIGHTS',str(models/'syncnet_v2.model'))).expanduser()
    if not sync.is_file() or sync.stat().st_size==0:assets.append('SyncNet weights')
    insight=Path.home()/'.insightface/models/buffalo_l'
    if not insight.is_dir() or not list(insight.glob('*.onnx')):assets.append('InsightFace buffalo_l weights')
    persons=list_personas();persona_ready=any(p['status']=='ready' for p in persons)
    missing=assets+['Python package: '+m for m in packages]
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):missing.append('FFmpeg/FFprobe')
    if not (os.getenv('WHISPER_URL') or importlib.util.find_spec('whisper')):missing.append('Whisper server or local model/runtime')
    return {'ok':True,'role':'remote_gpu_worker','gpu_available':bool(gpu_name or gpu['cuda']),
      'cuda_available':gpu['cuda'],'gpu_name':gpu_name,'persona_ready':persona_ready,'upstream_ready':upstream,
      'models_ready':not assets,'elevenlabs_configured':configured(),'generation_ready':False,
      'prerequisites_ready':bool(gpu['cuda'] and upstream and persona_ready and not missing),
      'missing':missing+([] if persona_ready else ['Persona reference image/audio']),
      'personas':persons,
      'note':'Prerequisites are checked, but generation_ready remains false until a real GPU generation has been validated.'}

import importlib.util
from pathlib import Path
import json
import os
import platform
import shutil
import subprocess
import sys
from config import ROOT, UPSTREAM, persona_status

def report():
    gpu={'torch':False,'cuda':False,'mps':False}
    if importlib.util.find_spec('torch'):
        try:
            import torch
            gpu.update(torch=True,cuda=torch.cuda.is_available(),mps=bool(hasattr(torch.backends,'mps') and torch.backends.mps.is_available()))
        except Exception as exc:
            gpu['error']=str(exc)
    ml_python=os.getenv('UGC_ML_ENV_PYTHON')
    if ml_python and Path(ml_python).resolve()!=Path(sys.executable).resolve():
        try:
            result=subprocess.run([ml_python,'-c',"import json,torch; print(json.dumps({'torch':True,'cuda':torch.cuda.is_available(),'mps':False}))"],capture_output=True,text=True,timeout=20)
            gpu=json.loads(result.stdout) if result.returncode==0 else {'torch':False,'cuda':False,'mps':False}
        except (OSError,ValueError,subprocess.TimeoutExpired):gpu={'torch':False,'cuda':False,'mps':False}
    models=Path(os.getenv('UGC_MODELS_DIR',str(Path.home()/'models'))).expanduser()
    projects=Path(os.getenv('UGC_PROJECTS_DIR',str(Path.home()/'projects'))).expanduser()
    required=[models/'ltx-2.3/ltx-2.3-22b-dev.safetensors',models/'id-lora-talkvid/lora_weights.safetensors',
      projects/'ID-LoRA/ID-LoRA-2.3/scripts/inference_two_stage_hq.py',projects/'ComfyUI/models/text_encoders/comfy_gemma_3_12B_it',
      projects/'ComfyUI/models/upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors',projects/'ComfyUI/models/loras/ltx-2.3-22b-distilled-lora-384.safetensors']
    missing=[str(p) for p in required if not p.exists() or (p.is_file() and p.stat().st_size==0) or (p.is_dir() and not any(p.iterdir()))]
    mac=platform.system()=='Darwin'
    classification=('LOCAL_CUDA_READY' if gpu['cuda'] and not missing and persona_status()['status']=='ready' else
                    'PARTIAL_SETUP' if gpu['cuda'] else 'MAC_CONTROLLER_ONLY' if mac else 'CPU_ONLY_NOT_RECOMMENDED')
    ram=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES') if hasattr(os,'sysconf') else None
    chip=subprocess.run(['sysctl','-n','machdep.cpu.brand_string'],capture_output=True,text=True).stdout.strip() if mac else None
    return {'os':platform.platform(),'architecture':platform.machine(),'mac_chip':chip,'ram_bytes':ram,
      'python':platform.python_version(),'git':shutil.which('git'),'ffmpeg':shutil.which('ffmpeg'),
      'nvidia_smi':shutil.which('nvidia-smi'),'gpu':gpu,'disk_free_bytes':shutil.disk_usage(ROOT).free,
      'upstream_present':(UPSTREAM/'examples/run_persona_example.py').is_file(),'persona':persona_status(),
      'missing_generation_assets':missing,'classification':classification,
      'variables':{k:bool(os.getenv(k)) for k in ['UGC_REMOTE_API_URL','UGC_REMOTE_API_KEY','UGC_LLM_API_URL','UGC_LLM_MODEL','UGC_LLM_API_KEY','UGC_MODELS_DIR','UGC_PROJECTS_DIR','UGC_ML_ENV_PYTHON','WHISPER_URL']},
      'note':'This machine can run the controller/UI/editor layer, but heavy video generation should use an NVIDIA backend unless a compatible MPS implementation is explicitly confirmed.' if not gpu['cuda'] else 'CUDA detected; external packages, scorer weights and model compatibility still require generation validation.'}
if __name__=='__main__':
    print(json.dumps(report(),indent=2))

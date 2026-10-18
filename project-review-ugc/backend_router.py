import os
from doctor import report
class SetupRequired(Exception):
    def __init__(self,message,code='setup_required'):
        super().__init__(message); self.code=code

def route(backend='auto'):
    if backend not in ('auto','local_upstream','remote_gpu'):
        raise SetupRequired('Unknown generation backend')
    if backend=='auto':
        if report()['gpu']['cuda']: return 'local_upstream'
        if os.getenv('UGC_REMOTE_API_URL'): return 'remote_gpu'
        raise SetupRequired('No CUDA GPU or remote GPU URL configured. The UI and script builder work; video generation needs an NVIDIA backend.')
    if backend=='remote_gpu' and not os.getenv('UGC_REMOTE_API_URL'):
        raise SetupRequired('Set UGC_REMOTE_API_URL in .env to your GPU worker address.')
    if backend=='local_upstream' and not report()['gpu']['cuda']:
        raise SetupRequired('Local upstream requires a CUDA-enabled NVIDIA GPU and PyTorch.')
    return backend

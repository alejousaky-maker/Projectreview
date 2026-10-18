"""Authenticated controller-to-worker transport; keys never leave the backend."""
import os
from urllib.parse import urlsplit
import httpx
from backend_router import SetupRequired

def connection():
    base=os.getenv('UGC_REMOTE_API_URL','').rstrip('/')
    key=os.getenv('UGC_REMOTE_API_KEY','')
    if not base or not key:raise SetupRequired('Configure UGC_REMOTE_API_URL and UGC_REMOTE_API_KEY in controller settings','remote_config_missing')
    url=urlsplit(base)
    if url.scheme not in ('http','https') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise SetupRequired('Worker URL must be a plain HTTP(S) service URL without credentials','remote_url_invalid')
    if url.scheme!='https' and url.hostname not in ('localhost','127.0.0.1'):
        raise SetupRequired('Use an HTTPS RunPod proxy URL to protect your worker key','remote_url_invalid')
    return base,{'Authorization':'Bearer '+key}

def worker_health():
    try:
        base,headers=connection()
        with httpx.Client(timeout=15,headers=headers) as client:
            response=client.get(base+'/health')
        if response.status_code in (401,403):return {'online':False,'error':'Worker rejected the API key; use the same key in both environments.'}
        if response.status_code!=200:return {'online':False,'error':f'Worker returned HTTP {response.status_code}'}
        data=response.json()
        if data.get('role')!='remote_gpu_worker':return {'online':False,'error':'URL does not point to a compatible GPU worker'}
        allowed=['ok','role','gpu_available','cuda_available','gpu_name','persona_ready','upstream_ready','models_ready','elevenlabs_configured','generation_ready','prerequisites_ready','missing','personas']
        return {'online':True,**{k:data[k] for k in allowed if k in data}}
    except SetupRequired as exc:return {'online':False,'error':str(exc)}
    except (httpx.HTTPError,ValueError,TypeError):return {'online':False,'error':'Worker is offline or returned invalid health data. Check Pod status, port 8091 and startup logs.'}

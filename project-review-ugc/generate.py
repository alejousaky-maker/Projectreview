import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
import httpx
from config import JOBS, OUTPUTS
from backend_router import route, SetupRequired
from script_builder import build_script
from editor import probe
log=logging.getLogger('ugc.jobs')
LOCK=threading.Lock()
GPU_LOCK=threading.Lock()

def save(job):
    with LOCK:
        target=JOBS/(job['job_id']+'.json');tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(job,indent=2));tmp.replace(target)

def read(job_id):
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id): raise FileNotFoundError(job_id)
    return json.loads((JOBS/(job_id+'.json')).read_text())

def run(job, request):
    output=OUTPUTS/job['job_id'];output.mkdir(exist_ok=True)
    def update(stage,progress):
        job.update(status='running',stage=stage,progress=progress);save(job)
    try:
        update('script',10)
        script=build_script(**{k:request[k] for k in ['topic','audience','business_type','tone','duration','cta_style','style','frames']})
        (output/'script.json').write_text(json.dumps(script,indent=2))
        (output/'scripts.json').write_text(json.dumps(script['segments']))
        if request['dry_run']:
            job.update(status='dry_run',stage='script and command plan ready; no video generated',progress=100,script=script)
            from upstream_adapter import command
            job['command']=command(request,output)
            save(job);return
        backend=route(request['backend']);update(backend,20)
        if backend=='local_upstream':
            from upstream_adapter import generate
            with GPU_LOCK:
                final=generate(request,output,script['segments'])
        else:
            final=remote(request,output,job,update)
        probe(final)
        job.update(status='completed',stage='finished',progress=100,output_video=f"/videos/{job['job_id']}")
    except Exception as exc:
        log.error(json.dumps({'event':'job_failed','job_id':job['job_id'],'error':str(exc)}))
        job.update(status='failed',stage='failed',error={'code':getattr(exc,'code','generation_failed'),'message':str(exc)})
    save(job)

def remote(request,output,job,update):
    base=os.environ['UGC_REMOTE_API_URL'].rstrip('/')
    headers={'Authorization':'Bearer '+os.getenv('UGC_REMOTE_API_KEY','')}
    with httpx.Client(timeout=60,headers=headers) as client:
        payload=dict(request,backend='local_upstream')
        response=client.post(base+'/generate',json=payload);response.raise_for_status()
        jid=response.json()['job_id']
        for _ in range(2160):
            response=client.get(base+'/jobs/'+jid);response.raise_for_status();state=response.json()
            if state['status']=='failed': raise SetupRequired(str(state['error']),'remote_failed')
            if state['status']=='completed':
                target=output/'final.mp4'
                with client.stream('GET',base+'/videos/'+jid) as download:
                    download.raise_for_status()
                    with target.open('wb') as f:
                        for chunk in download.iter_bytes(): f.write(chunk)
                return target
            update('remote: '+state['stage'],state['progress']);time.sleep(10)
    raise SetupRequired('Remote generation timed out','remote_timeout')

def submit(request):
    job={'job_id':uuid.uuid4().hex,'status':'queued','progress':0,'stage':'queued','output_video':None,'error':None}
    save(job)
    threading.Thread(target=run,args=(dict(job),request),daemon=True).start()
    return job

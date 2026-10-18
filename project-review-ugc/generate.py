import base64
import json
import logging
import os
import threading
import time
import uuid
import wave
from pathlib import Path
import httpx
from config import JOBS, OUTPUTS
from backend_router import route, SetupRequired
from script_builder import build_script
from editor import probe
from voice import prepare_voice
from remote_client import connection
from runpod_manager import manager
log=logging.getLogger('ugc.jobs')
LOCK=threading.Lock()
GPU_LOCK=threading.Lock()

def save(job):
    with LOCK:
        target=JOBS/(job['job_id']+'.json');tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(job,indent=2));tmp.replace(target)

def read(job_id):
    if len(job_id)!=32 or any(c not in '0123456789abcdef' for c in job_id):raise FileNotFoundError(job_id)
    return json.loads((JOBS/(job_id+'.json')).read_text())

def run(job,request):
    output=OUTPUTS/job['job_id'];output.mkdir(exist_ok=True)
    acquired=False
    def update(stage,progress):
        job.update(status='running',stage=stage,progress=progress)
        if stage in job['stages']:job['stages'][stage]='running'
        save(job)
    try:
        update('Script',5)
        if request.get('_segments'):
            script={'source':'controller','segments':request['_segments']}
        else:
            script=build_script(**{k:request[k] for k in ['topic','audience','business_type','tone','duration','cta_style','style','frames']})
        (output/'script.json').write_text(json.dumps(script,indent=2))
        (output/'scripts.json').write_text(json.dumps(script['segments']))
        job['stages']['Script']='done'
        if request['dry_run']:
            job.update(status='dry_run',stage='Script preview; no voice credits or GPU used',progress=100,script=script)
            from upstream_adapter import command
            job['command']=command(request,output);save(job);return
        backend=route('remote_gpu' if request.get('gpu_mode')=='auto' else request['backend'])
        # Reject incomplete worker/persona before spending TTS credits or starting a GPU.
        from personas import persona_details
        if backend=='local_upstream':
            details=persona_details(request['persona'])
            if details['status']!='ready':raise SetupRequired('Persona incomplete: '+', '.join(details['missing']))
        elif request.get('voice_provider','elevenlabs')=='reference':
            # Reference voice lives on worker; no controller copy is needed.
            pass
        if backend=='remote_gpu':
            if request.get('gpu_mode')=='auto':
                manager.acquire();acquired=True;health=manager.wait_until_healthy()
            else:
                from remote_client import worker_health
                health=worker_health()
            if not health.get('online'):raise SetupRequired(health.get('error','Worker is offline'),'remote_offline')
            if not health.get('prerequisites_ready'):
                raise SetupRequired('Worker connected, but generation prerequisites are incomplete. Open Setup & status for missing models/persona/runtime.', 'worker_incomplete')
            chosen=next((p for p in health.get('personas',[]) if p['id']==request['persona']),None)
            if not chosen or chosen.get('status')!='ready':raise SetupRequired('Selected worker persona is incomplete or disabled','persona_incomplete')
        update('Voice',12)
        if request.get('_voice_b64'):
            audio=output/'audio';audio.mkdir(exist_ok=True)
            path=audio/'speech.wav';path.write_bytes(base64.b64decode(request['_voice_b64'],validate=True))
            try:
                with wave.open(str(path)) as wav:
                    if wav.getnframes()==0:raise ValueError('empty audio')
            except (wave.Error,ValueError,EOFError):raise SetupRequired('Controller voice is not valid WAV audio','voice_invalid') from None
            voice={'path':str(path),'provider':'controller','mock':False}
        elif backend=='remote_gpu' and request.get('voice_provider')=='reference':voice=None
        else:voice=prepare_voice(script['segments'],request['persona'],output,request.get('voice_provider','elevenlabs'))
        if voice:
            if voice['mock']:raise SetupRequired('Mock voice cannot be used for real generation','mock_only')
            request=dict(request,_voice_path=voice['path'])
            job['voice']={k:v for k,v in voice.items() if k!='path'}
        job['stages']['Voice']='conditioning prepared' if voice else 'worker persona reference'
        update('GPU',20)
        if backend=='local_upstream':
            from upstream_adapter import generate
            with GPU_LOCK:
                update('Avatar',30);job['stages']['Lip Sync']='upstream QC during generation'
                final=generate(request,output,script['segments'])
        else:final=remote(request,output,job,update,script['segments'])
        update('Export',95)
        if not Path(final).is_file() or not Path(final).stat().st_size:raise SetupRequired('Final MP4 is missing','missing_output')
        probe(final)
        job['stages'].update(GPU='done',Avatar='done',**{'Lip Sync':'upstream gates ran; review best-effort warnings',
            'Captions':'estimated timing' if request['captions'] else 'off','Export':'done'})
        job.update(status='completed',stage='finished',progress=100,output_video=f"/videos/{job['job_id']}")
    except Exception as exc:
        code=getattr(exc,'code','generation_failed')
        # Do not serialize HTTP exceptions, request headers or signed URLs into logs/UI.
        message=str(exc) if isinstance(exc,SetupRequired) else 'Generation failed. Inspect worker logs and setup status.'
        log.error(json.dumps({'event':'job_failed','job_id':job['job_id'],'code':code}))
        job.update(status='failed',stage='failed',error={'code':code,'message':message})
    finally:
        if acquired:manager.release()
    save(job)

def remote(request,output,job,update,segments):
    base,headers=connection()
    payload={k:v for k,v in request.items() if not k.startswith('_')}
    payload.update(backend='local_upstream',gpu_mode='manual')
    voice=base64.b64encode(Path(request['_voice_path']).read_bytes()).decode() if request.get('_voice_path') else None
    with httpx.Client(timeout=60,headers=headers) as client:
        response=client.post(base+'/render',json={'request':payload,'segments':segments,'voice_b64':voice})
        if response.status_code!=202:raise SetupRequired(f'Worker rejected generation (HTTP {response.status_code}); check setup status','remote_failed')
        jid=response.json()['job_id']
        if not isinstance(jid,str) or len(jid)!=32 or any(c not in '0123456789abcdef' for c in jid):raise SetupRequired('Invalid worker job response','remote_invalid')
        for _ in range(2160):
            if request.get('gpu_mode')=='auto' and manager.snapshot()['state'] in ('Stopped','Error'):
                raise SetupRequired('GPU session stopped or reached its safety limit','runpod_session_stopped')
            response=client.get(base+'/jobs/'+jid)
            if response.status_code!=200:raise SetupRequired(f'Unable to read worker job (HTTP {response.status_code})','remote_failed')
            state=response.json()
            if state['status']=='failed':raise SetupRequired(str(state.get('error',{}).get('message','Worker generation failed')),'remote_failed')
            if state['status']=='completed':
                target=output/'final.mp4'
                with client.stream('GET',base+'/videos/'+jid) as download:
                    if download.status_code!=200:raise SetupRequired('Worker video download failed','remote_download')
                    with target.open('wb') as f:
                        for chunk in download.iter_bytes():f.write(chunk)
                return target
            job['stages'].update(state.get('stages',{}));update('Avatar',min(90,state.get('progress',25)))
            time.sleep(10)
    raise SetupRequired('Remote generation timed out','remote_timeout')

def submit(request):
    job={'job_id':uuid.uuid4().hex,'status':'queued','progress':0,'stage':'queued','output_video':None,'error':None,
         'stages':{s:'waiting' for s in ['Script','Voice','GPU','Avatar','Lip Sync','Captions','Export']}}
    save(job);threading.Thread(target=run,args=(dict(job),request),daemon=True).start()
    return job

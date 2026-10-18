import os
import re
import subprocess
import sys
from pathlib import Path
from config import ROOT, UPSTREAM, persona_status
from doctor import report
from backend_router import SetupRequired
from editor import edit

def command(request, output):
    cmd=[os.getenv('UGC_ML_ENV_PYTHON',sys.executable),str(UPSTREAM/'examples/run_persona_example.py'),
      '--persona-dir',str(Path(request.get('_persona_dir',ROOT/'personas'/request['persona']))),'--scripts',str(output/'scripts.json'),
      '--best-of',str(request['best_of']),'--frames',str(request['frames']),
      '--gpu',str(request['gpu']),'--output',str(output/'upstream')]
    return cmd

def generate(request, output, segments):
    import json
    (output/'execution.json').write_text(json.dumps({'command':command(request,output),'exit_code':None,'outputs':[]},indent=2))
    status=persona_status(request['persona'])
    if status['missing']: raise SetupRequired('Persona incomplete: '+', '.join(status['missing']))
    missing=report()['missing_generation_assets']
    if missing: raise SetupRequired('Missing model assets or external repositories: '+', '.join(missing))
    from readiness import worker_status
    readiness=worker_status()
    if readiness['missing']:raise SetupRequired('GPU worker prerequisites missing: '+', '.join(readiness['missing']), 'worker_incomplete')
    if request.get('_voice_path'):
        import shutil
        private_persona=output/'persona';private_persona.mkdir(exist_ok=True)
        original=ROOT/'personas'/request['persona']
        for name in ('persona.json','scene_bible.json','reference.jpg'):
            shutil.copyfile(original/name,private_persona/name)
        shutil.copyfile(request['_voice_path'],private_persona/'reference.wav')
        request=dict(request,_persona_dir=str(private_persona))
    env=os.environ.copy();env['UGC_RESULTS_DIR']=str(output/'candidates')
    for name in ('UGC_VIDEO_GPU','UGC_VIDEO_GPU_2','UGC_EVAL_GPU','UGC_TTS_GPU'):
        env[name]=str(request['gpu'])
    with (output/'stdout.log').open('w') as stdout,(output/'stderr.log').open('w') as stderr:
        result=subprocess.run(command(request,output),cwd=UPSTREAM,env=env,stdout=stdout,stderr=stderr,timeout=21600)
    (output/'execution.json').write_text(json.dumps({'command':command(request,output),'exit_code':result.returncode,'outputs':[str(p) for p in output.rglob('*.mp4')]},indent=2))
    if result.returncode:
        raise SetupRequired(f'Upstream exited with code {result.returncode}; inspect {output.name}/stderr.log', 'upstream_failed')
    text=(output/'stdout.log').read_text()
    match=re.search(r'^FINAL: (.+)$',text,re.M)
    if not match: raise SetupRequired('Upstream did not report a final MP4','missing_output')
    source=Path(match.group(1)).resolve()
    if not source.is_relative_to(output.resolve()) or not source.is_file() or source.suffix.lower()!='.mp4' or not source.stat().st_size:
        raise SetupRequired('Upstream final MP4 missing or outside job directory','missing_output')
    return edit([source],output/'final.mp4',music=request.get('music'),captions=request['captions'],lines=segments)

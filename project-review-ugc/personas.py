"""Persona metadata and media validation; never return server file paths."""
import json
import re
from config import ROOT

def persona_details(persona_id):
    result={'id':persona_id,'display_name':persona_id,'voice_provider':'elevenlabs','voice_id':'','enabled':True,
            'status':'Persona incomplete','missing':[]}
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',persona_id):
        result['missing']=['invalid persona id'];return result
    directory=ROOT/'personas'/persona_id
    for filename in ('persona.json','scene_bible.json','reference.jpg','reference.wav'):
        path=directory/filename
        if not path.is_file() or path.stat().st_size==0:result['missing'].append(filename)
    try:
        data=json.loads((directory/'persona.json').read_text())
        if not isinstance(data,dict):raise ValueError('not an object')
        result.update(display_name=str(data.get('display_name',data.get('name',persona_id))),
                      voice_provider=data.get('voice_provider','elevenlabs'),voice_id=str(data.get('voice_id','')),
                      enabled=data.get('enabled',True) is True)
        bible=json.loads((directory/'scene_bible.json').read_text())
        if not isinstance(bible,dict):raise ValueError('invalid scene bible')
    except (OSError,ValueError,TypeError):
        result['missing'].append('valid persona/scene JSON')
    if not result['enabled']:result['missing'].append('persona disabled')
    if not result['missing']:result['status']='ready'
    return result

def list_personas():
    return [persona_details(p.name) for p in sorted((ROOT/'personas').iterdir())
            if p.is_dir() and re.fullmatch(r'[A-Za-z0-9_-]{1,80}',p.name)]

"""Voice preparation. Upstream consumes this as conditioning, not forced speech."""
import os
import re
import shutil
import subprocess
import wave
from pathlib import Path
import httpx
from backend_router import SetupRequired
from config import ROOT
from personas import persona_details

def configured():
    return bool(os.getenv('ELEVENLABS_API_KEY') and (os.getenv('ELEVENLABS_VOICE_ID') or any(p['voice_id'] for p in __import__('personas').list_personas())))

def prepare_voice(segments, persona, output, provider='elevenlabs', mock=False):
    audio=Path(output)/'audio';audio.mkdir(exist_ok=True)
    target=audio/'speech.wav'
    if mock:
        with wave.open(str(target),'wb') as wav:
            wav.setparams((1,2,24000,0,'NONE','not compressed'));wav.writeframes(b'\0\0'*24000)
        return {'path':str(target),'provider':'mock','mock':True}
    if provider=='reference':
        source=ROOT/'personas'/persona/'reference.wav'
        if not source.is_file() or not source.stat().st_size:raise SetupRequired('Persona reference.wav is missing','voice_missing')
    elif provider=='espeak':
        binary=shutil.which('espeak-ng') or shutil.which('espeak')
        if not binary:raise SetupRequired('Open-source TTS requires espeak-ng on the controller','tts_missing')
        source=audio/'espeak.wav'
        subprocess.run([binary,'-w',str(source),' '.join(segments)],check=True,capture_output=True)
    else:
        key=os.getenv('ELEVENLABS_API_KEY','');voice=persona_details(persona)['voice_id'] or os.getenv('ELEVENLABS_VOICE_ID','')
        if not key or not voice:raise SetupRequired('Add ELEVENLABS_API_KEY and ELEVENLABS_VOICE_ID in controller secrets, or select Persona reference','elevenlabs_missing')
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',voice):raise SetupRequired('Invalid ElevenLabs voice ID','voice_invalid')
        source=audio/'speech.mp3'
        try:
            with httpx.Client(timeout=120) as client:
                response=client.post('https://api.elevenlabs.io/v1/text-to-speech/'+voice,
                    headers={'xi-api-key':key},params={'output_format':'mp3_44100_128'},
                    json={'text':' '.join(segments),'model_id':os.getenv('ELEVENLABS_MODEL_ID') or 'eleven_multilingual_v2'})
                if response.status_code!=200:raise SetupRequired(f'ElevenLabs returned HTTP {response.status_code}; check voice access and credit balance','elevenlabs_failed')
                source.write_bytes(response.content)
        except httpx.HTTPError:
            raise SetupRequired('ElevenLabs request failed; check network and service availability','elevenlabs_unreachable') from None
    if not shutil.which('ffmpeg'):raise SetupRequired('FFmpeg is required to prepare voice audio','ffmpeg_missing')
    try:
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(source),'-af','loudnorm=I=-16:TP=-1.5:LRA=11',
                        '-ar','48000','-ac','2',str(target)],check=True,capture_output=True)
    except subprocess.CalledProcessError:raise SetupRequired('Voice audio could not be decoded by FFmpeg','voice_invalid') from None
    return {'path':str(target),'provider':provider,'mock':False,
            'note':'Used as upstream reference conditioning; LTX regenerates speech jointly with video.'}

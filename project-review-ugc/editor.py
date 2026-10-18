import json
import subprocess
from pathlib import Path

def probe(path):
    result=subprocess.run(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)],capture_output=True,text=True,check=True)
    data=json.loads(result.stdout)
    if not any(s['codec_type']=='video' for s in data['streams']) or float(data['format'].get('duration',0))<=0:
        raise ValueError('Output is not a playable video')
    return data

def edit(clips, output, music=None, captions=False, lines=None):
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    normalized=[]
    for i,clip in enumerate(clips):
        probe(clip)
        target=output.parent/f'edit_{i}.mp4'
        subprocess.run(['ffmpeg','-v','error','-y','-i',str(clip),'-vf',
          'scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,setsar=1,fps=24',
          '-af','loudnorm=I=-16:TP=-1.5:LRA=11','-c:v','libx264','-preset','fast','-threads','2',
          '-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',str(target)],check=True)
        normalized.append(target)
    listing=output.parent/'concat.txt'
    listing.write_text(''.join("file '"+str(p.resolve()).replace("'", "'\\''")+"'\n" for p in normalized))
    assembled=output.parent/'assembled.mp4'
    subprocess.run(['ffmpeg','-v','error','-y','-f','concat','-safe','0','-i',str(listing),'-c','copy',str(assembled)],check=True)
    args=['ffmpeg','-v','error','-y','-i',str(assembled)]
    if music:
        args+=['-stream_loop','-1','-i',str(music),'-filter_complex','[1:a]volume=0.08[m];[0:a][m]amix=inputs=2:duration=first[a]','-map','0:v','-map','[a]']
    if captions and lines:
        # Estimated timings are explicitly approximate; use alignment for publication accuracy.
        duration=float(probe(assembled)['format']['duration']); total=sum(len(x.split()) for x in lines)
        def stamp(t):
            ms=round(t*1000);return f'{ms//3600000:02}:{ms//60000%60:02}:{ms//1000%60:02},{ms%1000:03}'
        cursor=0; entries=[]
        for i,line in enumerate(lines):
            end=cursor+duration*len(line.split())/total
            entries.append(f'{i+1}\n{stamp(cursor)} --> {stamp(end)}\n{line}\n');cursor=end
        sub=output.parent/'captions.srt';sub.write_text('\n'.join(entries))
        args+=['-vf',"subtitles=captions.srt:force_style='Alignment=2,MarginV=180,FontSize=18,Outline=2'",'-c:v','libx264','-threads','2']
    else: args+=['-c:v','copy']
    args+=['-c:a','aac','-movflags','+faststart',str(output.resolve())]
    subprocess.run(args,cwd=output.parent,check=True)
    probe(output)
    return output

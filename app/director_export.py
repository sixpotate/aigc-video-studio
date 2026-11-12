"""Resolution-aware encoding; captions are rendered after image enlargement."""
import os
import pathlib
from settings import WORKSPACE,CREATE_NO_WINDOW
from director_schema import export_settings, output_size
from video_timing import subtitle_phrases
from worker import timestamp


def validate_clip(path,seconds,settings=None):
    """Only a decodable container with the requested audio/video counts as complete."""
    import json,subprocess
    if not path.is_file() or not path.stat().st_size:raise ValueError('镜头视频为空或未保存完整。')
    response=subprocess.run(['ffprobe','-v','error','-show_entries','stream=codec_type,width,height:format=duration','-of','json',str(path)],
                            capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=15,creationflags=CREATE_NO_WINDOW)
    if response.returncode:raise ValueError('镜头视频无法读取，需要重新导出。')
    info=json.loads(response.stdout);streams=info.get('streams',[])
    video=next((s for s in streams if s.get('codec_type')=='video'),{})
    if (video.get('width'),video.get('height'))!=output_size(settings):raise ValueError('镜头导出尺寸与作品设置不一致。')
    if not any(s.get('codec_type')=='audio' for s in streams):raise ValueError('镜头视频缺少音轨。')
    duration=float(info.get('format',{}).get('duration',0))
    if seconds<=0 or abs(duration-seconds)>.25:raise ValueError('镜头视频时长与对白时长不一致。')
    return {'duration':duration,'width':video['width'],'height':video['height'],'audio':True}


def subtitles(shot, audio, path, settings=None, captions=None):
    ratio=export_settings(settings)['ratio']
    w,h=(540,960) if ratio=='9:16' else ((960,540) if ratio=='16:9' else (540,540))
    margin=90 if ratio=='9:16' else 38
    header=f'''[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Dialogue,Microsoft YaHei,30,&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,-1,0,0,0,100,100,0,0,1,2,1,2,28,28,{margin},1
Style: Label,Microsoft YaHei,18,&H00FFFFFF,&H00FFFFFF,&H00202020,&H00000000,0,0,0,0,100,100,0,0,1,2,0,8,20,20,18,1
Style: OS,Microsoft YaHei,28,&H00FFFFFF,&H00FFFFFF,&H005A5045,&H805A5045,-1,0,0,0,100,100,0,0,3,8,0,2,28,28,{margin},1
Style: Punch,Microsoft YaHei,34,&H0066E8FF,&H00FFFFFF,&H00332818,&H80000000,-1,0,0,0,100,100,0,0,1,3,1,8,30,30,70,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''
    def clean(value):return value.replace('\\','／').replace('{','（').replace('}','）').replace('\n',' ')
    events=[f'Dialogue: 0,0:00:00.00,{timestamp(audio["seconds"])},Label,,0,0,0,,AI生成 · 虚构故事']
    if shot['text']:
        name=shot.get('subtitle_name') or ('旁白' if shot.get('speaker_id')=='narrator' else shot.get('role',{}).get('name',''))
        prefix=(name+'：') if (captions or {}).get('speaker_name') and name else ''
        kind=shot.get('speech_kind','dialogue');style='OS' if kind=='os' else 'Dialogue'
        if kind=='os':prefix=(name+' · 内心：') if name else '内心：'
        phrases=subtitle_phrases(shot['text']);weights=[len(p)+2 for p in phrases];cursor=audio['speech_start']
        for i,(phrase,weight) in enumerate(zip(phrases,weights)):
            end=cursor+audio['speech_seconds']*weight/sum(weights)
            display=audio['seconds'] if i==len(phrases)-1 else end
            events.append(f'Dialogue: 0,{timestamp(cursor)},{timestamp(display)},{style},,0,0,0,,{clean(prefix+phrase)}');cursor=end
    if shot.get('onscreen_text'):
        label=clean(shot['onscreen_text']);label=r'\N'.join(label[i:i+16] for i in range(0,len(label),16))
        position=r'{\an5\pos('+f'{w//2},{h//2}'+')}' if shot.get('visual_only') else ''
        events.append(f'Dialogue: 2,0:00:00.00,{timestamp(audio["seconds"] if shot.get("visual_only") else min(3,audio["seconds"]))},Punch,,0,0,0,,{position}{label}')
    path.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')


def encode_command(video, audio, ass, seconds, target, settings=None):
    w,h=output_size(settings);relative=pathlib.Path(os.path.relpath(ass, WORKSPACE)).as_posix()
    filters=f"scale={w}:{h}:flags=lanczos,setsar=1,setpts=PTS-STARTPTS,fps=25,ass=filename='{relative}'"
    return ['ffmpeg','-y','-v','error','-i',video,'-i',audio,'-map','0:v','-map','1:a','-vf',filters,
            '-t',seconds,'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-ar','48000','-movflags','+faststart',target]

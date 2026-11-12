import json, os, pathlib, re, subprocess, sys, time
from video_timing import plan_timing, subtitle_phrases
from video_assembly import concat_command

from settings import APP_DIR, WORKSPACE, VIDEO_DIR
LOCAL = WORKSPACE/'work/local_test'
MOTION_TOOLS = WORKSPACE/'work/motion_test'
PORTABLE_PYTHON = WORKSPACE/'runtime/python/python.exe'
PORTABLE_FFMPEG = WORKSPACE/'runtime/ffmpeg'
CREATE_NO_WINDOW = 0x08000000
if PORTABLE_FFMPEG.is_dir():
    os.environ['PATH']=str(PORTABLE_FFMPEG)+os.pathsep+os.environ.get('PATH','')
os.environ.setdefault('PYTHONNOUSERSITE','1')
os.environ['HF_HOME'] = str(LOCAL/'hf-cache')
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def run(cmd, quiet=False):
    if not quiet:
        print('正在处理：' + pathlib.Path(str(cmd[-1])).name, flush=True)
    subprocess.run([str(x) for x in cmd], check=True, creationflags=CREATE_NO_WINDOW)


def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)], creationflags=CREATE_NO_WINDOW))


def timestamp(value):
    h=int(value//3600); m=int(value%3600//60); s=value%60
    return f'{h}:{m:02d}:{s:05.2f}'


def safe_name(text):
    text=re.sub(r'[<>:"/\\|?*]+','_',text).strip(' .')
    return text[:48] or '未命名短剧'


def main(job_path):
    job=json.loads(pathlib.Path(job_path).read_text(encoding='utf-8'))
    run_id=time.strftime('%Y%m%d_%H%M%S')
    work=WORKSPACE/'work/app_runs'/run_id
    audio=work/'audio'; audio.mkdir(parents=True,exist_ok=True)
    output_dir=pathlib.Path(job.get('output_dir') or VIDEO_DIR); output_dir.mkdir(parents=True,exist_ok=True)
    raw=WORKSPACE/f'outputs/motion_test/ep{int(job["template"]):02d}_motion.mp4'
    if not raw.exists(): raise FileNotFoundError(raw)

    print('1/4 正在加载本地情感配音模型……',flush=True)
    import torch, soundfile as sf
    from qwen_tts import Qwen3TTSModel
    model=Qwen3TTSModel.from_pretrained(str(LOCAL/'models/Qwen3-TTS-1.7B-CustomVoice'),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa')
    roles=('boss','robot','boss','robot')
    emotions=(
        '自然、有管理者的命令感，开头平稳，句尾略加强调。',
        '年轻男声，冷静认真，像在精确执行指令，疑问处有轻微上扬。',
        '明显惊讶或犹豫，情绪有起伏，语速稍快。',
        '年轻男声，镇定记录，结论部分略带幽默的重音。',
    )
    if job.get('video_mood') == 'reversal':
        emotions = (
            '语气由平静逐渐转为坚定，节奏自然。',
            '语气克制，句间自然停顿。',
            '语气惊讶，随后逐渐平稳。',
            '语气坚定，结尾自然收束。',
        )
    raw_audio=[]
    for i,(text,role,instruct) in enumerate(zip(job['lines'],roles,emotions),1):
        print(f'生成配音 {i}/4',flush=True)
        speaker='Uncle_Fu' if role=='boss' else 'Dylan'
        torch.manual_seed(int(job['episode'])*100+i)
        wavs,sr=model.generate_custom_voice(text=text,language='Chinese',speaker=speaker,instruct=instruct,max_new_tokens=min(1000,max(220,len(text)*12)))
        path=audio/f'line_{i:02d}_{role}_raw.wav'; sf.write(path,wavs[0],sr); raw_audio.append(path)
    del model
    torch.cuda.empty_cache()

    print('2/4 正在调整台词节奏……',flush=True)
    original_durations=[duration(src) for src in raw_audio]
    factor,slots=plan_timing(original_durations,float(job.get('video_duration',12.25)))
    timing=dict(tempo=factor,raw_seconds=original_durations,clip_seconds=slots,total_seconds=sum(slots))
    (work/'timing.json').write_text(json.dumps(timing,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TIMING '+json.dumps(timing),flush=True)
    fitted=[]
    for i,src in enumerate(raw_audio,1):
        dst=audio/f'line_{i:02d}_fitted.wav'
        filters=['aresample=24000',f'atempo={factor:.6f}','asetpts=PTS-STARTPTS','adelay=120','apad',f'atrim=end_sample={round(slots[i-1]*24000)}','asetpts=PTS-STARTPTS']
        run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',src,'-af',','.join(filters),'-ar','24000','-ac','1',dst],quiet=True)
        fitted.append(dst)

    print('3/4 正在跟踪人物并生成口型……',flush=True)
    py=PORTABLE_PYTHON if PORTABLE_PYTHON.is_file() else LOCAL/'venv/Scripts/python.exe'
    transforms=work/'face_transforms.npy'; contact=work/'motion_contact.jpg'
    run([py,MOTION_TOOLS/'track_motion.py',raw,'--transforms',transforms,'--contact',contact],quiet=True)
    motion_loop=work/'motion_loop.mp4'
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',raw,'-filter_complex','[0:v]split[a][b];[b]reverse[r];[a][r]concat=n=2:v=1:a=0[v]','-map','[v]','-an','-c:v','libx264','-crf','18',motion_loop],quiet=True)
    clips=[]
    for i,(text,role) in enumerate(zip(job['lines'],roles),1):
        clip=work/f'clip_{i:02d}.mp4'; clips.append(clip)
        if role=='boss':
            lips=work/f'lips_{i:02d}.mp4'
            run([py,MOTION_TOOLS/'sync_motion.py',raw,'--audio',fitted[i-1],'--transforms',transforms,'--output-dir',work,'--out',lips.stem,'--offset','0','--duration',slots[i-1]],quiet=True)
            vf='scale=600:1067,crop=540:960:60:0' if i==3 else 'null'
            run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',lips,'-vf',vf,'-r','25','-t',slots[i-1],'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',clip],quiet=True)
        else:
            vf='scale=600:1067,crop=540:960:60:70' if i==2 else 'scale=540:960'
            run(['ffmpeg','-y','-hide_banner','-loglevel','error','-stream_loop','-1','-i',motion_loop,'-i',fitted[i-1],'-vf',vf,'-r','25','-t',slots[i-1],'-map','0:v','-map','1:a','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-ar','48000','-ac','2',clip],quiet=True)

    print('4/4 正在添加字幕并输出成片……',flush=True)
    ass=work/'captions.ass'; total=sum(slots)
    header='''[Script Info]\nScriptType: v4.00+\nPlayResX: 540\nPlayResY: 960\nWrapStyle: 0\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\nStyle: Brand,Microsoft YaHei,20,&H00FFFFFF,&H00FFFFFF,&H00222222,&H70000000,-1,0,0,0,100,100,0,0,1,2,0,8,18,18,42,1\nStyle: Hook,Microsoft YaHei,29,&H00FFFFFF,&H00FFFFFF,&H00222222,&H70000000,-1,0,0,0,100,100,0,0,1,2,1,8,28,28,86,1\nStyle: Dialogue,Microsoft YaHei,31,&H00FFFFFF,&H00FFFFFF,&H00222222,&H70000000,-1,0,0,0,100,100,1,0,1,2,1,2,25,25,105,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'''
    def clean_ass(s): return str(s).replace('\\','／').replace('{','（').replace('}','）').replace('\n',' ')
    events=[f'Dialogue: 0,{timestamp(0)},{timestamp(total)},Brand,,0,0,0,,AI生成 · 虚构故事',f'Dialogue: 0,{timestamp(0)},{timestamp(min(3,slots[0]))},Hook,,0,0,0,,{clean_ass(job["hook"])}']
    cursor=0
    for i,text in enumerate(job['lines']):
        phrases=subtitle_phrases(text)
        weights=[len(p)+2 for p in phrases]
        speech=original_durations[i]/factor
        elapsed=.12
        for phrase_index,(phrase,weight) in enumerate(zip(phrases,weights)):
            end=elapsed+speech*weight/sum(weights)
            display_end=slots[i] if phrase_index==len(phrases)-1 else min(end,slots[i])
            events.append(f'Dialogue: 0,{timestamp(cursor+elapsed)},{timestamp(cursor+display_end)},Dialogue,,0,0,0,,{clean_ass(phrase)}')
            elapsed=end
        cursor+=slots[i]
    ass.write_text(header+'\n'.join(events)+'\n',encoding='utf-8')
    joined=work/'joined.mp4'
    run(concat_command(clips,slots,joined),quiet=True)
    final=output_dir/f'{run_id}_第{int(job["episode"]):02d}集_{safe_name(job["title"])}.mp4'
    ass_rel=ass.relative_to(WORKSPACE).as_posix()
    from settings import SIZES
    output_width,output_height=SIZES.get(str(job.get('output_resolution','540')),SIZES['540'])['9:16']
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-i',joined,'-vf',f"setpts=PTS-STARTPTS,fps=25,tpad=stop_mode=clone:stop_duration=0.2,trim=duration={total},scale={output_width}:{output_height}:flags=lanczos,ass=filename='{ass_rel}'",'-t',total,'-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-movflags','+faststart',final],quiet=True)
    cover=final.with_name(final.stem+'_封面.jpg')
    run(['ffmpeg','-y','-hide_banner','-loglevel','error','-ss','1','-i',final,'-frames:v','1',cover],quiet=True)
    run(['ffmpeg','-v','error','-i',final,'-f','null','NUL'],quiet=True)
    print('成片位置：'+str(final),flush=True)


if __name__=='__main__':
    if len(sys.argv)!=2:
        raise SystemExit('用法：worker.py job.json')
    main(sys.argv[1])

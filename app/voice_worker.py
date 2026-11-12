"""Cache natural speech separately from speed and pauses for inexpensive previews."""
import json,math,os,pathlib,subprocess,sys
from settings import WORKSPACE,CREATE_NO_WINDOW
from director_schema import EMOTIONS,speech_key,audio_key
from production_errors import fatal_error,failure
from progress_writer import write_progress, atomic_json
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(WORKSPACE/'work/local_test/hf-cache'))


def fit_audio(shot,folder,raw_dir):
    import soundfile as sf
    import numpy as np
    key=audio_key(shot);output=folder/(key+'.wav');meta=folder/(key+'.json')
    if output.is_file() and meta.is_file():
        result=json.loads(meta.read_text(encoding='utf-8'))
        if result.get('pause_analysis_version')!=1:
            from dialogue_timing import pause_windows,VERSION
            wave,sr=sf.read(output)
            result.update(pause_windows=pause_windows(wave,sr,result['speech_start'],result['speech_seconds']),pause_analysis_version=VERSION)
            temporary=meta.with_suffix('.partial.json');temporary.write_text(json.dumps(result,ensure_ascii=False),'utf-8');temporary.replace(meta)
        return result
    speech_seconds=0
    if shot['text']:
        raw=raw_dir/(speech_key(shot)+'.wav');adjusted=raw_dir/(key+'_speed.wav')
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(raw),'-af',f'atempo={shot["speed"]},asetpts=PTS-STARTPTS','-ar','24000','-ac','1',str(adjusted)],check=True,creationflags=CREATE_NO_WINDOW)
        wave,sr=sf.read(adjusted);speech_seconds=len(wave)/sr
    else:wave=np.zeros(0);sr=24000
    requested=shot.get('duration');minimum=requested if requested is not None else (1. if shot['text'] else 3.)
    seconds=math.ceil(max(minimum,speech_seconds+shot['pause_before']+shot['pause_after'])*25)/25
    if seconds>60:raise ValueError(f'这句配音长达{seconds:.1f}秒，可能发生重复或异常停顿，请重试这一句；不会截断对白。')
    padded=np.zeros(round(seconds*sr),dtype=np.float32)
    start=round(shot['pause_before']*sr);padded[start:start+len(wave)]=wave
    if shot.get('speech_kind')=='chorus' and len(wave):
        combined=padded.copy()
        for rate,delay,gain in [(1.025,.025,.38),(.978,.049,.34)]:
            layer=np.interp(np.arange(0,len(padded),rate),np.arange(len(padded)),padded);at=round(delay*sr);n=min(len(layer),len(padded)-at);combined[at:at+n]+=layer[:n]*gain
        padded=combined*min(1,.89/max(float(np.max(abs(combined))),1e-6))
    temporary=output.with_suffix('.partial.wav');sf.write(temporary,padded,sr);temporary.replace(output)
    result=dict(audio=output.name,seconds=seconds,speech_seconds=speech_seconds,speech_start=shot['pause_before'],key=key,
                requested_seconds=requested,extended=bool(requested is not None and seconds>requested+.04))
    from dialogue_timing import pause_windows,VERSION
    result.update(pause_windows=pause_windows(padded,sr,shot['pause_before'],speech_seconds),pause_analysis_version=VERSION)
    meta.write_text(json.dumps(result,ensure_ascii=False),encoding='utf-8')
    return result


def main(job):
    import soundfile as sf
    folder=pathlib.Path(job['folder']);folder.mkdir(parents=True,exist_ok=True)
    target=pathlib.Path(job['result']);results={}
    def checkpoint():
        atomic_json(target,results)
    def failed(shot,exc):
        if not job.get('isolate_errors') or fatal_error(exc):raise exc
        results[shot['id']]={'error':failure('audio',exc)};checkpoint()
    def report(value,message,shot):
        if not job.get('progress'):return
        write_progress(job['progress'],dict(progress=value,message=message,shot_id=shot['id']))
    raw_dir=folder/'voice_cache';raw_dir.mkdir(exist_ok=True)
    missing=[s for s in job['shots'] if s['text'] and not (raw_dir/(speech_key(s)+'.wav')).is_file()]
    if missing:
        import torch
        from qwen_tts import Qwen3TTSModel
        torch.set_num_threads(4)
        model=Qwen3TTSModel.from_pretrained(str(WORKSPACE/'work/local_test/models/Qwen3-TTS-1.7B-CustomVoice'),device_map='cuda:0',dtype=torch.bfloat16,attn_implementation='sdpa')
        try:
            for index,shot in enumerate(missing):
                try:
                    report(3+int(6*index/len(missing)),f'配音 {index+1}/{len(missing)} · 正在生成角色语音…',shot)
                    torch.manual_seed(int(speech_key(shot)[:8],16))
                    from voice_catalog import generation_voice,process_voice
                    speaker,style=generation_voice(shot['voice'])
                    waves,sr=model.generate_custom_voice(text=shot['text'],language='Chinese',speaker=speaker,instruct=EMOTIONS[shot['emotion']]+' '+shot['emotion_note']+' '+style,max_new_tokens=750)
                    raw_target=raw_dir/(speech_key(shot)+'.wav');raw_temp=raw_target.with_suffix('.partial.wav')
                    sf.write(raw_temp,process_voice(waves[0],sr,shot['voice']),sr);raw_temp.replace(raw_target)
                except Exception as exc:failed(shot,exc)
        finally:
            del model;torch.cuda.empty_cache()
    for index,shot in enumerate(job['shots']):
        if shot['id'] in results:continue
        try:
            report(9+int(3*index/len(job['shots'])),f'配音整理 {index+1}/{len(job["shots"])} · 正在适配语速、停顿与时长…',shot)
            results[shot['id']]=fit_audio(shot,folder,raw_dir);checkpoint()
        except Exception as exc:failed(shot,exc)
    checkpoint()


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')))

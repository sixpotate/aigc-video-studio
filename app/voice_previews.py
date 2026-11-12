"""Cached fixed-text voice previews sharing the app's exclusive model queue."""
import json, threading, uuid
from settings import WORKSPACE, APP_DIR, PYTHON
from voice_catalog import VOICES, PREVIEW_DIR, preview_shot, validate_voice
from director_schema import audio_key
from process_control import run_child
from runtime_health import assert_runtime_allowed


class VoicePreviews:
    def __init__(self,jobs):self.jobs=jobs

    def snapshot(self):
        result={}
        for voice in VOICES:
            key=audio_key(preview_shot(voice));audio=PREVIEW_DIR/(key+'.wav');meta=PREVIEW_DIR/(key+'.json')
            if audio.is_file() and meta.is_file():result[voice]='/voice-preview/'+audio.name
        return result

    def start(self,data):
        voices=data.get('voices',[data.get('voice')])
        if not isinstance(voices,list) or not 1<=len(voices)<=len(VOICES):raise ValueError('请选择需要试听的音色。')
        voices=list(dict.fromkeys(validate_voice(voice) for voice in voices))
        with self.jobs.lock:
            if self.jobs.state['running']:raise ValueError('请等待当前任务完成，或先停止生成。')
            available=self.snapshot();missing=[v for v in voices if v not in available]
            if not missing:return self.jobs.snapshot()
            assert_runtime_allowed()
            work=WORKSPACE/'work/voice_preview_runs'/uuid.uuid4().hex;work.mkdir(parents=True)
            job=dict(shots=[preview_shot(v) for v in missing],folder=str(PREVIEW_DIR),result=str(work/'result.json'),preview=True)
            path=work/'job.json';path.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
            self.jobs.cancel.clear()
            self.jobs.state.update(running=True,status='running',task_kind='voice_preview',character_id=None,progress=0,
                                   message=f'正在本地生成 {len(missing)} 种音色试听，首次加载需要等待…')
            self.jobs._save()
            self.jobs.thread=threading.Thread(target=self._run,args=(path,),daemon=True);self.jobs.thread.start()
            return self.jobs.snapshot()

    def _run(self,path):
        try:
            run_child([PYTHON,'-u',APP_DIR/'voice_worker.py',path],self.jobs.cancel.is_set,path.parent/'worker.log')
            with self.jobs.lock:
                if self.jobs.cancel.is_set():self.jobs.state.update(status='stopped',message='已停止音色试听生成，完成的试听仍保留。')
                else:self.jobs.state.update(status='done',progress=100,message='音色试听已保存到本机，可以直接播放。')
        except InterruptedError:
            with self.jobs.lock:self.jobs.state.update(status='stopped',message='已停止音色试听生成。重试会复用已准备好的原声。')
        except Exception as exc:
            with self.jobs.lock:self.jobs.state.update(status='error',message=str(exc))
        finally:
            with self.jobs.lock:self.jobs.state['running']=False;self.jobs._save()

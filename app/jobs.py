"""Validation, project persistence and one cancellable local generation queue."""
import copy
import json
import pathlib
import subprocess
import threading
import time
import uuid
import secrets
import re
from characters import CharacterStore, model_ready, normalize_role
from portrait_spec import inspect_role, normalize_generation
from settings import APP_DIR, CHARACTER_DIR, CURRENT, CREATE_NO_WINDOW, PYTHON, ROLES, SIZES, STORAGE, VIDEO_DIR, WORKSPACE
from runtime_health import assert_runtime_allowed, runtime_status

def director_task_started_at(state):
    """Return the current director job's creation time without changing state."""
    if not state.get('running') or state.get('task_kind') != 'director':return None
    value=state.get('director_work')
    if not isinstance(value,str):return None
    try:
        path=pathlib.Path(value).resolve()
        root=(WORKSPACE/'work/director_runs').resolve()
        if path.parent != root or not re.fullmatch(r'[a-f0-9]{32}',path.name):return None
        return (path/'job.json').stat().st_mtime
    except (OSError,ValueError):return None


def video_phase(text):
    milestones = [
        ('1/4 正在加载', 5, '正在加载本地情感配音模型…'),
        ('生成配音 1/4', 15, '正在生成第1段配音…'),
        ('生成配音 2/4', 25, '正在生成第2段配音…'),
        ('生成配音 3/4', 35, '正在生成第3段配音…'),
        ('生成配音 4/4', 45, '正在生成第4段配音…'),
        ('2/4 正在调整', 55, '正在调整台词节奏…'),
        ('3/4 正在跟踪', 65, '正在跟踪人物并生成口型…'),
        ('4/4 正在添加', 90, '正在添加字幕并输出视频…'),
    ]
    for marker, progress, message in reversed(milestones):
        if marker in text:
            return progress, message
    return 0, '正在启动本地视频流程…'


def validate(data):
    script = str(data.get('script', '')).strip()
    if not script or len(script) > 6000:
        raise ValueError('请输入剧本，长度不超过6000字。')
    settings = data.get('settings', {})
    if not isinstance(settings, dict):
        raise ValueError('画面设置格式不正确。')
    try:
        count, template = int(settings.get('count', 6)), int(settings.get('template', 1))
    except (ValueError, TypeError):
        raise ValueError('镜头数量或动作模板格式不正确。')
    ratio, resolution = settings.get('ratio', '9:16'), str(settings.get('resolution', '540'))
    if not 1 <= count <= 12 or not 1 <= template <= 6:
        raise ValueError('镜头数量应为1至12，动作模板应为1至6。')
    if resolution not in SIZES or ratio not in SIZES[resolution]:
        raise ValueError('不支持这个画面比例或分辨率。')
    if settings.get('style', 'template') != 'template':
        raise ValueError('目前仅支持现有3D模板，日系和国漫生成尚未接入。')
    try:
        video_duration = float(settings.get('video_duration', 12.25))
    except (ValueError, TypeError):
        raise ValueError('请选择有效的视频时长。')
    if video_duration not in (12.25, 30):
        raise ValueError('视频时长支持约12秒或30秒。')
    video_mood = settings.get('video_mood', 'daily')
    if video_mood not in ('daily', 'reversal'):
        raise ValueError('请选择有效的配音情绪。')
    chars = data.get('characters', ROLES)
    if not isinstance(chars, list):
        raise ValueError('角色列表格式不正确。')
    characters = []
    for source in chars:
        role = normalize_role(source)
        role['image'] = source.get('image')
        if role['image']:
            import re
            if not re.fullmatch(r'/characters/media/[a-zA-Z0-9_-]{1,48}/[a-f0-9]{32}\.png',role['image']):
                raise ValueError('角色形象文件无效。')
        characters.append(role)
    if len({r['id'] for r in characters}) != len(characters):
        raise ValueError('角色编号不能重复。')
    source = settings.get('source','template')
    if source not in ('template','character'):
        raise ValueError('请选择有效的画面来源。')
    lead = settings.get('lead_character','')
    if source == 'character':
        role = next((r for r in characters if r['id']==lead and r.get('image')), None)
        if role is None or not (CHARACTER_DIR/role['image'].removeprefix('/characters/media/')).is_file():
            raise ValueError('请先为主角生成人物形象，再使用角色立绘分镜。')
    return dict(title=str(data.get('title', '')).strip()[:60] or '未命名漫剧', script=script, characters=characters,
                settings=dict(count=count, template=template, ratio=ratio, resolution=resolution, style='template',source=source,lead_character=lead,video_duration=video_duration,video_mood=video_mood))


class Jobs:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.state = dict(running=False, status='idle', message='准备好后，开始生成第一组分镜。', progress=0, project=None, video=None)
        self.thread = None
        self.characters = CharacterStore()
        self._restore()
        from director_jobs import Director
        self.director = Director(self)
        from voice_previews import VoicePreviews
        self.voice_previews = VoicePreviews(self)
        from story_jobs import StoryWorkshop
        self.story = StoryWorkshop(self)

    def _restore(self):
        if not CURRENT.exists():
            return
        try:
            saved = json.loads(CURRENT.read_text(encoding='utf-8'))
            self.state.update(saved)
            self.state['running'] = False
            if self.state['status'] in ('running', 'stopping'):
                self.state.update(status='stopped', message='上次任务已中断，已保留完成的分镜。')
            project = self.state.get('project')
            if project:
                for shot in project['shots']:
                    if shot['status'] in ('pending', 'running'):
                        shot['status'] = 'ready' if shot.get('image') else 'cancelled'
        except (ValueError, OSError, KeyError):
            pass

    def snapshot(self):
        with self.lock:
            story = self.story.snapshot()
            from image_engine import capabilities
            return dict(copy.deepcopy(self.state), task_started_at=director_task_started_at(self.state), characters=self.characters.list(), character_model_ready=model_ready(),image_engine=capabilities(),director=self.director.snapshot(),voice_previews=self.voice_previews.snapshot(),story=story,runtime_safety=runtime_status())

    def _save(self):
        CURRENT.parent.mkdir(parents=True, exist_ok=True)
        temp = CURRENT.with_suffix('.tmp')
        temp.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding='utf-8')
        temp.replace(CURRENT)
        project = self.state['project']
        if project:
            (STORAGE / project['id'] / 'project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')

    def set_text_encoder(self, data):
        from image_engine import set_encoder
        with self.lock:
            if self.state['running']:
                raise ValueError('请等待当前任务完成或停止后，再切换文字理解方式。')
            set_encoder(data.get('id'))
            return self.snapshot()

    def set_image_engine(self, data):
        from image_engine import set_engine
        with self.lock:
            if self.state['running']:
                raise ValueError('请等待当前任务完成或停止后，再切换绘图模型。')
            set_engine(data.get('id'))
            return self.snapshot()

    def generate(self, data):
        # Projects only need their selected cast, never the entire uncapped library.
        if 'character_ids' in data:
            ids = data['character_ids']
            if not isinstance(ids,list) or any(not isinstance(i,str) for i in ids):
                raise ValueError('出镜角色编号格式不正确。')
            data = {**data, 'characters':[self.characters.get(i) for i in dict.fromkeys(ids)]}
        spec = validate(data)
        with self.lock:
            if self.state['running']:
                raise ValueError('已有任务正在运行，请等待完成或停止。')
            project_id = uuid.uuid4().hex
            (STORAGE / project_id).mkdir(parents=True, exist_ok=True)
            paragraphs = [line.strip() for line in spec['script'].splitlines() if line.strip()]
            count = spec['settings']['count']
            shots = []
            for i in range(count):
                start = i * len(paragraphs) // count
                end = max(start + 1, (i + 1) * len(paragraphs) // count)
                shots.append(dict(id=i+1, index=i, text='\n'.join(paragraphs[start:end]), status='pending', revision=0, image=None))
            self.state['project'] = dict(**spec, id=project_id, shots=shots, created=time.strftime('%Y-%m-%d %H:%M:%S'))
            self.state['video'] = None
            self._start(list(range(count)))
            return self.snapshot()

    def regenerate(self, data):
        with self.lock:
            if self.state['running']:
                raise ValueError('请先等待当前任务完成或停止。')
            project = self.state['project']
            if not project or data.get('project_id') != project['id']:
                raise ValueError('分镜项目已变化，请刷新页面后重试。')
            try:
                index = int(data['shot_id']) - 1
                if not 0 <= index < len(project['shots']):
                    raise ValueError()
            except (KeyError, TypeError, ValueError):
                raise ValueError('镜头编号无效。')
            project['shots'][index]['revision'] += 1
            project['shots'][index]['status'] = 'pending'
            self._start([index])
            return self.snapshot()

    def _start(self, indices):
        self.cancel.clear()
        self.state.update(running=True, status='running', progress=0, task_kind='storyboard', character_id=None, message='正在准备分镜素材…')
        self._save()
        self.thread = threading.Thread(target=self._render, args=(indices,), daemon=True)
        self.thread.start()

    def _render(self, indices):
        failed = False
        try:
            for done, index in enumerate(indices):
                if self.cancel.is_set():
                    break
                with self.lock:
                    project = self.state['project']
                    shot = project['shots'][index]
                    shot['status'] = 'running'
                    self.state['message'] = f'正在生成镜头 {index+1:02d} · {done+1}/{len(indices)}'
                    name = f'shot_{index+1:02d}_v{shot["revision"]+1}.png'
                    target = STORAGE / project['id'] / name
                    spec_path = WORKSPACE / 'work/app_ui' / f'{project["id"]}_shot.json'
                    spec_path.write_text(json.dumps(dict(project=project, shot=shot, target=str(target)), ensure_ascii=False), encoding='utf-8')
                result = self._process([str(PYTHON), str(APP_DIR/'storyboard_worker.py'), str(spec_path)])
                with self.lock:
                    if self.cancel.is_set():
                        break
                    if result != 0:
                        shot['status'] = 'error'
                        raise RuntimeError(f'镜头 {index+1:02d} 生成失败，请查看运行日志。')
                    shot.update(status='ready', image=f'/media/{project["id"]}/{name}')
                    self.state['progress'] = round((done+1)/len(indices)*100)
                    self._save()
        except Exception as exc:
            failed = True
            with self.lock:
                self.state.update(status='error', message=str(exc))
        finally:
            with self.lock:
                project = self.state['project']
                for shot in project['shots']:
                    if shot['status'] in ('pending', 'running'):
                        shot['status'] = 'ready' if shot.get('image') else 'cancelled'
                if self.cancel.is_set():
                    self.state.update(status='stopped', message='已停止。已完成的分镜仍可预览和导出。')
                elif not failed:
                    self.state.update(status='done', progress=100, message='分镜已完成，可单格重做或批量导出。')
                self.state['running'] = False
                self._save()

    def _process(self, command, report_video=False, progress_path=None):
        from process_control import ManagedProcess
        from runtime_health import RunHealth
        log_path = WORKSPACE / 'work/app_ui/last_run.log'
        health=RunHealth(command,log_path);managed=ManagedProcess();process=None
        try:
            health.start()
            log_path.parent.mkdir(parents=True,exist_ok=True)
            with log_path.open('a', encoding='utf-8') as log:
                start_offset=log.tell();last_report=0;stop_started=None
                process=managed.start(command,cwd=WORKSPACE,stdout=log,stderr=subprocess.STDOUT,creationflags=CREATE_NO_WINDOW)
                while process.poll() is None:
                    health.tick()
                    if self.cancel.is_set():
                        if progress_path:progress_path.with_suffix('.cancel').touch(exist_ok=True)
                        if stop_started is None:stop_started=time.monotonic()
                        if not progress_path or time.monotonic()-stop_started>=30:
                            managed.close()
                            health.finish('cancelled','用户停止任务，已清理本任务进程。');return -1
                        time.sleep(.1);continue
                    time.sleep(.1)
                    if report_video and time.monotonic()-last_report>1:
                        last_report=time.monotonic()
                        with log_path.open('r',encoding='utf-8',errors='replace') as reader:
                            reader.seek(start_offset);progress,message=video_phase(reader.read())
                        with self.lock:
                            if self.state['status']=='running':self.state.update(progress=progress,message=message)
                    if progress_path and progress_path.is_file():
                        try:
                            detail=json.loads(progress_path.read_text(encoding='utf-8'))
                            with self.lock:
                                if self.state['status']=='running':self.state.update(progress=detail['progress'],message=detail['message'])
                        except (OSError,ValueError,KeyError):pass
                managed.close()
                health.finish('cancelled' if self.cancel.is_set() else 'failed' if process.returncode else 'completed')
                return process.returncode
        except BaseException as exc:
            try:managed.close()
            finally:health.finish('cancelled' if isinstance(exc,InterruptedError) else 'failed',str(exc))
            raise

    def character_action(self, action, data):
        with self.lock:
            if self.state['running']:
                raise ValueError('请等待当前任务完成或先停止。')
            if action=='save':
                self.characters.save(data)
            elif action in ('archive','restore'):
                self.characters.archive(data.get('id'), restore=action=='restore')
            elif action=='choose':
                self.characters.choose(data.get('id'),data.get('image'))
            return self.snapshot()

    def portrait(self, data):
        with self.lock:
            if self.state['running']:
                raise ValueError('已有任务正在运行，请先完成或停止。')
            if not model_ready():
                raise ValueError('本地绘图模型尚未准备好，请等待安装完成。')
            role = self.characters.get(data.get('id'))
            errors = [i['message'] for i in inspect_role(role) if i['severity']=='error']
            if errors:
                raise ValueError(' '.join(errors))
            assert_runtime_allowed()
            generation = normalize_generation(data, role, CHARACTER_DIR, lambda: secrets.randbelow(2**31))
            version = uuid.uuid4().hex
            folder = CHARACTER_DIR/role['id']
            folder.mkdir(parents=True,exist_ok=True)
            work = WORKSPACE/'work/app_ui'
            work.mkdir(parents=True,exist_ok=True)
            progress_path = work/f'portrait_{version}_progress.json'
            job = dict(role=role,**generation,target=str(folder/f'{version}.png'),progress_path=str(progress_path))
            from image_engine import selected, preferred_flux_engine
            job.update(engine=selected(), reference_engine=preferred_flux_engine())
            job_path = work/f'portrait_{version}.json'
            job_path.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
            self.cancel.clear()
            self.state.update(running=True,status='running',progress=0,task_kind='character',character_id=role['id'],message='正在准备绘制人物…')
            self._save()
            self.thread=threading.Thread(target=self._portrait,args=(job,job_path,progress_path,version),daemon=True)
            self.thread.start()
            return self.snapshot()

    def _portrait(self, job, job_path, progress_path, version):
        try:
            result = self._process([str(PYTHON),'-u',str(APP_DIR/'portrait_worker.py'),str(job_path)],progress_path=progress_path)
            with self.lock:
                if self.cancel.is_set():
                    self.state.update(status='stopped',message='人物绘制已停止，之前的形象仍保留。')
                elif result:
                    detail=json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {}
                    self.state.update(status='error',message=detail.get('message','人物绘制失败，请查看运行日志。'))
                else:
                    if not pathlib.Path(job['target']).is_file():
                        raise RuntimeError('绘图任务未输出图片。')
                    generation = {k:job[k] for k in ('mode','strength','reference_image','quality','pose_guide','face_refine','content_check','edit_instruction') if k in job}
                    detail=json.loads(progress_path.read_text(encoding='utf-8')) if progress_path.exists() else {}
                    generation.update(review_status='pending',compiler=detail.get('result',{}).get('plan',{}).get('version','unknown'))
                    self.characters.publish(job['role']['id'],f"/characters/media/{job['role']['id']}/{version}.png",job['role'],job['seed'],generation)
                    self.state.update(status='done',progress=100,message=f"{job['role']['name']}的图片已保存，请核对外貌、服装和姿势。")
        except Exception as exc:
            with self.lock:
                self.state.update(status='error',message=str(exc))
        finally:
            with self.lock:
                self.state['running']=False
                self._save()

    def stop(self):
        with self.lock:
            if self.state['running']:
                self.cancel.set()
                self.state.update(status='stopping', message='正在停止当前任务…')
            return self.snapshot()

    def reset(self):
        with self.lock:
            if self.state['running']:
                raise ValueError('请先停止生成，再重置工作台。')
            self.state.update(project=None, progress=0, status='idle', message='工作台已重置，已导出的文件仍保留。', video=None)
            self._save()
            return self.snapshot()

    def video(self, data):
        with self.lock:
            if self.state['running']:
                raise ValueError('请等待当前任务完成。')
            project = self.state['project']
            if not project:
                raise ValueError('请先生成分镜。')
            if project['settings'].get('source')=='character':
                raise ValueError('角色立绘分镜目前支持图片导出，新的角色动作和口型视频尚未接入。')
            lines = [x.strip() for x in project['script'].splitlines() if x.strip()]
            if len(lines) != 4:
                raise ValueError('配音视频需要四行台词，依次为角色甲、角色乙、角色甲、角色乙。')
            lines = [re.sub(r'^(?:角色甲|角色乙)\s*[：:]\s*', '', line) for line in lines]
            if any(not line or len(line) > 80 for line in lines):
                raise ValueError('每行请输入1至80字的对白，不含动作说明。')
            assert_runtime_allowed()
            job = dict(episode=7, title=project['title'], hook=project['title'], template=project['settings']['template'], lines=lines,
                       video_duration=project['settings'].get('video_duration', 12.25),
                       video_mood=project['settings'].get('video_mood', 'daily'), output_resolution=project['settings'].get('resolution','540'), output_dir=str(VIDEO_DIR))
            path = WORKSPACE / 'work/app_ui/video_job.json'
            path.write_text(json.dumps(job, ensure_ascii=False), encoding='utf-8')
            self.cancel.clear()
            self.state.update(running=True, status='running', progress=0,task_kind='video',character_id=None, message='正在加载模型并制作配音视频，首次加载可能较慢…')
            self._save()
            self.thread = threading.Thread(target=self._video, args=(path,), daemon=True)
            self.thread.start()
            return self.snapshot()

    def _video(self, path):
        try:
            result = self._process([str(PYTHON), '-u', str(APP_DIR/'worker.py'), str(path)], report_video=True)
            with self.lock:
                if self.cancel.is_set():
                    self.state.update(status='stopped', message='视频生成已停止。')
                elif result:
                    self.state.update(status='error', message='视频生成失败，详情见工作目录中的运行日志。')
                else:
                    latest = max(VIDEO_DIR.glob('*.mp4'), key=lambda p:p.stat().st_mtime)
                    self.state.update(status='done', progress=100, video=latest.name, message='配音视频已完成，点击“视频文件夹”查看。')
        except Exception as exc:
            with self.lock:
                self.state.update(status='error', message=str(exc))
        finally:
            with self.lock:
                self.state['running'] = False
                self._save()

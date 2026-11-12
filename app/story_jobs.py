"""Authoring projects share the existing exclusive, cancellable GPU queue."""
import copy
import json
import pathlib
import re
import secrets
import threading
import uuid
import hashlib
import time
from datetime import datetime
from settings import APP_DIR, WORKSPACE, PYTHON, WRITING_LLM, WRITING_MODEL_NAME, TRANSLATION_RUNTIME, PROJECTS_DIR
from story_schema import brief_spec, validate_document, director_project, issues, ASSET_SLOTS, character_profile
from director_schema import valid_id
from story_worker import write
from runtime_health import assert_runtime_allowed

STORY_DIR = PROJECTS_DIR/'创作项目'
CURRENT = WORKSPACE/'work/story_workshop/current.json'


class StoryWorkshop:
    def __init__(self, jobs):
        self.jobs = jobs
        self.document = None
        self.active = None
        self.last_result = None
        self.research_cache = {}
        self.research_lock = threading.Lock()
        try:
            self.document = json.loads(CURRENT.read_text('utf-8'))
        except (OSError, ValueError):
            pass
        for index,episode in enumerate((self.document or {}).get('episodes', []),1):
            episode['number']=index
        run_id = (self.document or {}).get('last_run_id', '')
        if (self.document or {}).get('job_pending') and isinstance(run_id,str) and re.fullmatch(r'[a-f0-9]{32}',run_id):
            folder=WORKSPACE/'work/story_runs'/run_id
            if folder.is_dir():
                (folder/'progress.cancel').touch(exist_ok=True)
                self.active=folder
                self._adopt()
                self.document['job_pending']=False
                self.active=None
                self._save()

    def _save(self):
        if self.document:
            write(STORY_DIR/self.document['id']/'story.json', self.document)
            write(CURRENT, self.document)

    def _adopt(self):
        if not self.active:
            return
        try:
            raw = (self.active/'result.json').read_text('utf-8')
            if raw == self.last_result:
                return
            candidate = json.loads(raw)
        except (OSError, ValueError):
            return
        if candidate['id'] != self.document['id']:
            return
        for index, episode in enumerate(candidate.get('episodes', []), 1):
            episode['number'] = index
        for asset in candidate.get('generated_assets', []):
            self.jobs.characters.register_asset(asset)
        candidate['revision'] = self.document.get('revision', 0)+1
        self.document = candidate
        self.last_result = raw
        self._save()

    def snapshot(self):
        self._adopt()
        return dict(document=copy.deepcopy(self.document),
            model_ready=WRITING_LLM.is_file() and TRANSLATION_RUNTIME.is_file(),model_name=WRITING_MODEL_NAME,
            issues=issues(self.document) if self.document and self.document.get('characters') else [])

    def idle(self):
        if self.jobs.state['running']:
            raise ValueError('已有任务正在运行，请完成或停止后再操作。')

    def catalogue(self):
        items = []
        for path in STORY_DIR.glob('*/story.json'):
            try:
                doc = json.loads(path.read_text('utf-8'))
                items.append(dict(id=doc['id'], title=doc['title'], updated=path.stat().st_mtime))
            except (OSError, ValueError, KeyError):
                pass
        return dict(projects=sorted(items, key=lambda x:x['updated'], reverse=True))

    def open(self, data):
        with self.jobs.lock:
            self.idle()
            path = STORY_DIR/valid_id(data.get('id'), '创作工程')/'story.json'
            if not path.is_file():
                raise ValueError('找不到该创作工程。')
            candidate = json.loads(path.read_text('utf-8'))
            self._save()
            self.document, self.active, self.last_result = candidate, None, None
            self._save()
            return self.jobs.snapshot()

    def save(self, data):
        with self.jobs.lock:
            self.idle()
            if not self.document or data.get('id') != self.document['id'] or data.get('revision') != self.document.get('revision', 0):
                raise ValueError('创作工程已被其他页面修改，请刷新后重试。')
            candidate = validate_document(data, self.jobs.characters)
            candidate.pop('integrity', None)
            if self.document.get('brief', {}).get('input_mode') == 'script':
                # Source provenance is server-owned, even when an older editor saves a project.
                for key in ('source_script', 'source_units', 'coverage', 'research', 'integrity'):
                    if key in self.document:
                        candidate[key] = copy.deepcopy(self.document[key])
                # Refresh only source location hints for legacy projects when
                # every original span still has the identical stable ID.
                # Dialogue and source spans remain server-owned and unchanged.
                from script_director import refresh_existing_scene_hints
                refresh_existing_scene_hints(candidate)
            # Worker metadata and completion status are server-owned.
            for key in ('generated_assets', 'complete', 'created', 'last_run_id', 'director_projects', 'director_sources'):
                if key in self.document:
                    candidate[key] = copy.deepcopy(self.document[key])
            candidate['revision'] = self.document.get('revision', 0)+1
            candidate['job_pending'] = False
            self.document, self.active = candidate, None
            self._save()
            return self.jobs.snapshot()

    def _research_inputs(self, data):
        value = data.get('brief', data)
        if not isinstance(value, dict):
            raise ValueError('作品资料格式不正确。')
        from director_schema import text
        title = text(value.get('title', ''), 60, '作品名称', True)
        mode = value.get('work_mode', 'original')
        if mode not in ('original', 'existing'):
            raise ValueError('请选择原创作品或已有作品。')
        script = text(value.get('script', ''), 60000, '完整剧本')
        ids = value.get('role_ids', [])
        if not isinstance(ids, list) or len(ids) > 8 or any(not isinstance(i, str) for i in ids):
            raise ValueError('作品角色列表无效。')
        roles = [self.jobs.characters.get(i) for i in dict.fromkeys(ids)]
        actors = [{k: r.get(k, '') for k in ('name', 'description', 'outfit', 'personality')} for r in roles]
        inputs = dict(title=title, mode=mode, characters=actors, script=script)
        key = hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return key, inputs

    def research(self, data):
        from work_research import research_context
        key, inputs = self._research_inputs(data)
        # Network reads do not hold the GPU/state lock. A slow search must not block Stop.
        if not self.research_lock.acquire(blocking=False):
            raise ValueError('正在查找参考资料，请等待本次查找完成。')
        try:
            cached = self.research_cache.get(key)
            if cached and time.time()-cached[0] < 1800:
                return dict(research=copy.deepcopy(cached[1]))
            result = research_context(**inputs)
            self.research_cache = {key: (time.time(), result)}
            return dict(research=result)
        finally:
            self.research_lock.release()

    def start(self, data):
        with self.jobs.lock:
            self.idle()
            mode = data.get('mode', 'write')
            if mode not in ('write', 'script', 'resume', 'portraits', 'pack', 'review'):
                raise ValueError('创作任务类型无效。')
            # Refuse heavy work before replacing the current document or saving roles.
            assert_runtime_allowed()
            tasks = []
            if mode in ('write', 'script'):
                brief = brief_spec(data.get('brief'))
                if mode == 'script' and brief.get('input_mode') != 'script':
                    raise ValueError('请填写作品名称，选择角色，然后粘贴完整剧本。')
                actors = []
                if mode == 'script':
                    for index, role_id in enumerate(brief['role_ids'], 1):
                        role = self.jobs.characters.get(role_id)
                        if any(a['name'] == role['name'] for a in actors):
                            raise ValueError('本作品中有同名角色，请先为他们设置不同名称。')
                        image = role.get('image') or ''
                        actors.append(dict(key=f'c{index}', name=role['name'],
                            description=role.get('description') or '沿用用户已保存的角色形象与特征。',
                            outfit=role.get('outfit', ''), personality=role.get('personality', ''),
                            role_id=role_id, reference_image=image, assets={'front':image} if image else {},
                            role_snapshot=copy.deepcopy(role)))
                self._save()
                self.document = dict(id=uuid.uuid4().hex, schema_version=1, revision=1, brief=brief,
                    title=brief['title'] or '新故事', characters=actors, scenes=[], episodes=[],
                    created=datetime.now().isoformat(timespec='seconds'), complete=False)
                if mode == 'script':
                    self.document['source_script'] = brief['script']
                    key, _ = self._research_inputs({'brief': brief})
                    cached = self.research_cache.get(key)
                    if brief['online_research'] and cached and cached[1].get('sources') and time.time()-cached[0] < 1800:
                        self.document['research'] = copy.deepcopy(cached[1])
            else:
                if not self.document or data.get('id') != self.document['id'] or data.get('revision') != self.document.get('revision', 0):
                    raise ValueError('请先保存当前创作工程，再开始任务。')
                if mode == 'resume' and self.document.get('complete'):
                    raise ValueError('分镜已经写完，可直接编辑或新建故事。')
                if mode in ('portraits', 'pack'):
                    if not self.document.get('characters'):
                        raise ValueError('请先完成角色与剧本规划。')
                    from characters import model_ready
                    if not model_ready():
                        raise ValueError('本地绘图模型不完整，请使用完整安装目录。')
                    for actor_index,actor in enumerate(self.document['characters']):
                        if mode == 'pack' and actor['key'] != data.get('character_key'):
                            continue
                        if actor.get('role_id'):
                            role = self.jobs.characters.get(actor['role_id'])
                        else:
                            role = self.jobs.characters.save(character_profile(actor,self.document['brief']['style'],actor_index))
                            actor['role_id'] = role['id']
                        if not actor.get('reference_image') and role.get('image'):
                            actor['reference_image'] = role['image']
                            actor.setdefault('assets', {})['front'] = role['image']
                        if mode == 'portraits':
                            if not actor.get('reference_image'):
                                tasks.append(dict(character_key=actor['key'], role=role, slot='front', seed=secrets.randbelow(2**31)))
                            continue
                        if not actor.get('reference_image'):
                            raise ValueError('请先准备角色主形象，再生成参考图候选。')
                        slot = data.get('slot')
                        if slot not in ASSET_SLOTS or slot == 'front':
                            raise ValueError('请选择侧面、全身或表情参考图。')
                        variant = copy.deepcopy(role)
                        source=next((v for v in role.get('images',[]) if v['image']==actor['reference_image']),{})
                        for key in ('description','outfit','style','framing','look','priorities'):
                            if key in source:variant[key]=copy.deepcopy(source[key])
                        if slot=='full':variant['framing']='full'
                        variant.setdefault('look', {})
                        changes = {'side': ('pose', '侧身站立，侧面轮廓清晰'), 'full': ('pose', '全身正面站立，双脚完整入镜'),
                                   'happy': ('expression', '开心微笑'), 'angry': ('expression', '皱眉生气'), 'serious': ('expression', '严肃平静')}
                        field, phrase = changes[slot]
                        variant['look'][field] = phrase
                        tasks.append(dict(character_key=actor['key'], role=variant, slot=slot,
                                          reference=actor['reference_image'], seed=secrets.randbelow(2**31)))
                    if not tasks and not (self.document['brief'].get('input_mode') == 'script' and any(not s.get('asset_id') for s in self.document.get('scenes', []))):
                        self._save()
                        self.jobs.state.update(message='角色主形象已齐备。')
                        return self.jobs.snapshot()
            if mode == 'review' and data.get('after_review') == 'produce':
                episode = data.get('episode', 1)
                if type(episode) is not int or not 1 <= episode <= len(self.document.get('episodes', [])):
                    raise ValueError('请选择有效的集数。')
            self.active = WORKSPACE/'work/story_runs'/uuid.uuid4().hex
            self.active.mkdir(parents=True, exist_ok=True)
            self.document['last_run_id']=self.active.name
            self.document['job_pending']=True
            self.last_result = None
            progress = self.active/'progress.json'
            worker_mode = ('script' if self.document['brief'].get('input_mode') == 'script' else 'write') if mode in ('write', 'script', 'resume') else ('review' if mode == 'review' else 'portraits')
            job = dict(mode=worker_mode,
                document=copy.deepcopy(self.document), tasks=tasks, work=str(self.active),
                progress=str(progress), result=str(self.active/'result.json'))
            from image_engine import selected, preferred_flux_engine
            job.update(engine=selected(), reference_engine=preferred_flux_engine())
            if mode == 'review' and data.get('after_review') == 'produce':
                job['produce_after_review'] = data.get('episode', 1)
            job['auto_prepare'] = mode in ('write', 'script') and data.get('auto_prepare') is True
            if mode == 'resume':
                job['auto_prepare'] = bool(self.document.get('auto_prepare'))
            self.document['auto_prepare'] = job['auto_prepare']
            job['document']['auto_prepare'] = job['auto_prepare']
            job['prepare_scenes'] = mode == 'portraits' and self.document['brief'].get('input_mode') == 'script'
            path = self.active/'job.json'
            write(path, job)
            self._save()
            self.jobs.cancel.clear()
            self.jobs.state.update(running=True, status='running', progress=0,
                task_kind='story', character_id=None, message='正在准备本地创作任务…')
            self.jobs._save()
            self.jobs.thread = threading.Thread(target=self._run, args=(path, progress), daemon=True)
            self.jobs.thread.start()
            return self.jobs.snapshot()

    def _run(self, path, progress):
        followup = None
        try:
            code = self.jobs._process([str(PYTHON), '-u', str(APP_DIR/'story_worker.py'), str(path)], progress_path=progress)
            with self.jobs.lock:
                self._adopt()
                initial=json.loads(path.read_text('utf-8'))
                automate=not code and not self.jobs.cancel.is_set() and initial.get('auto_prepare') and self.document.get('complete')
                if automate:
                    assert_runtime_allowed()
                    tasks=[]
                    for index,actor in enumerate(self.document['characters']):
                        role=self.jobs.characters.get(actor['role_id']) if actor.get('role_id') else self.jobs.characters.save(character_profile(actor,self.document['brief']['style'],index))
                        actor['role_id']=role['id']
                        if not actor.get('reference_image'):
                            tasks.append(dict(character_key=actor['key'],role=role,slot='front',seed=secrets.randbelow(2**31)))
                    next_job=dict(initial,mode='portraits',tasks=tasks,document=copy.deepcopy(self.document),prepare_scenes=True)
                    path=self.active/'assets_job.json';write(path,next_job);self._save()
            if automate:
                code=self.jobs._process([str(PYTHON),'-u',str(APP_DIR/'story_worker.py'),str(path)],progress_path=progress)
            with self.jobs.lock:
                self._adopt()
                detail = json.loads(progress.read_text('utf-8')) if progress.is_file() else {}
                if self.jobs.cancel.is_set():
                    self.jobs.state.update(status='stopped', message='已停止，已完成段落和角色素材已保存，可继续。')
                else:
                    self.jobs.state.update(status='error' if code else 'done',
                        progress=self.jobs.state['progress'] if code else 100,
                        message=detail.get('message', '本次创作任务结束。'))
                    if not code and initial.get('produce_after_review'):
                        followup = dict(id=self.document['id'], revision=self.document.get('revision', 0), episode=initial['produce_after_review'])
        except Exception as exc:
            with self.jobs.lock:
                self.jobs.state.update(status='error', message=str(exc))
        finally:
            with self.jobs.lock:
                self.jobs.state['running'] = False
                self.document['job_pending']=False
                self._save()
                self.jobs._save()
        if followup:
            try:
                with self.jobs.lock:
                    if self.jobs.cancel.is_set() or self.jobs.state['running'] or self.document['id'] != followup['id'] or self.document.get('revision',0) != followup['revision']:
                        return
                    self.produce(followup)
            except Exception as exc:
                with self.jobs.lock:
                    self.jobs.state.update(status='error', message=str(exc))
                    self.jobs._save()

    def commit(self, data):
        with self.jobs.lock:
            self.idle()
            if not self.document or data.get('id') != self.document['id'] or data.get('revision') != self.document.get('revision', 0):
                raise ValueError('请先保存当前创作工程。')
            project = director_project(self.document, data.get('episode', 1), self.jobs.characters)
            from director_schema import digest,render_key,DIRECTOR_DIR
            episode=str(data.get('episode',1))
            source=digest(dict(title=project['title'],script=project['script'],export=project['export'],sound=project['sound'],
                               shots=[render_key(s,project['export'],project['captions']) for s in project['shots']]))
            if any(s.get('sound_cues') for s in project['shots']):
                from sound_library import mix_identity
                source=digest(dict(source=source, mix=[mix_identity(s) for s in project['shots']]))
            linked=self.document.get('director_projects',{}).get(episode)
            if linked:
                target=DIRECTOR_DIR/valid_id(linked,'作品')/'project.json'
                if target.is_file():
                    existing=json.loads(target.read_text('utf-8'))
                    previous=self.document.get('director_sources',{}).get(episode)
                    if not previous:
                        previous=digest(dict(title=existing['title'],script=existing['script'],export=existing['export'],sound=existing['sound'],
                            shots=[render_key(s,existing['export'],existing['captions']) for s in existing['shots']]))
                    if previous==source and existing.get('authoring',{}).get('document_id')==self.document['id']:
                        self.jobs.director.open_project({'id':linked})
                        self.document.setdefault('director_sources',{})[episode]=source
                        self._save();return self.jobs.snapshot()
            self.jobs.director._save()
            self.jobs.director.save(project)
            self.document.setdefault('director_projects', {})[episode] = project['id']
            self.document.setdefault('director_sources',{})[episode]=source
            self._save()
            return self.jobs.snapshot()

    def produce(self,data):
        """Use the same validated director queue without requiring another workbench."""
        with self.jobs.lock:
            self.idle()
            if not self.document or not self.document.get('complete'):
                raise ValueError('请先完成故事初稿。')
            if data.get('id') != self.document['id'] or data.get('revision') != self.document.get('revision', 0):
                raise ValueError('作品已更新，请刷新后重新生成。')
            from story_integrity import current
            if self.document['brief'].get('input_mode') == 'script' and not current(self.document):
                return self.start(dict(mode='review', id=self.document['id'], revision=self.document.get('revision', 0),
                    episode=data.get('episode', 1), after_review='produce'))
            blocking=[x['message'] for x in issues(self.document) if x['level']=='error']
            if blocking:raise ValueError(' '.join(blocking))
            assert_runtime_allowed()
            self.commit(data)
            if self.jobs.director.project.get('final'):
                self.jobs.state.update(status='done',progress=100,message='这一集已有成片，可直接试看或下载。')
                self.jobs._save();return self.jobs.snapshot()
            return self.jobs.director.start(dict(mode='all',project=copy.deepcopy(self.jobs.director.project)))

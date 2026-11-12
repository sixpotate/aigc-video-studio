"""Director project storage integrated with the existing exclusive GPU queue."""
import copy,json,pathlib,threading,uuid
from settings import APP_DIR,WORKSPACE,PYTHON
from director_schema import DIRECTOR_CURRENT,DIRECTOR_DIR,validate_project,render_key,audio_key,motion_ready,export_settings
from runtime_health import assert_runtime_allowed

class Director:
    def __init__(self,jobs):
        self.jobs=jobs;self.project=None;self.active_work=None
        try:self.project=json.loads(DIRECTOR_CURRENT.read_text(encoding='utf-8'))
        except (OSError,ValueError):pass
        # A reboot loses Python threads, not completed assets. Recover only this project's persisted job.
        active=jobs.state.get('director_work')
        if active and self.project:
            path=pathlib.Path(active).resolve();root=(WORKSPACE/'work/director_runs').resolve()
            if path.is_relative_to(root) and (path/'job.json').is_file():
                try:
                    job=json.loads((path/'job.json').read_text('utf-8'))
                    if job.get('project',{}).get('id')==self.project['id']:
                        self.active_work=path;self._adopt()
                        for shot in self.project['shots']:
                            if shot.get('result',{}).get('status')=='running':
                                shot['result'].update(status='pending',error=None)
                        self._save();self.active_work=None;jobs.state.pop('director_work',None)
                except (OSError,ValueError,KeyError):pass

    def _save(self):
        if not self.project:return
        folder=DIRECTOR_DIR/self.project['id'];folder.mkdir(parents=True,exist_ok=True)
        for path in (DIRECTOR_CURRENT,folder/'project.json'):
            path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp')
            temporary.write_text(json.dumps(self.project,ensure_ascii=False,indent=2),encoding='utf-8');temporary.replace(path)

    def _adopt(self):
        if not self.active_work or not self.project:return
        try:result=json.loads((self.active_work/'result.json').read_text(encoding='utf-8'))
        except (OSError,ValueError):return
        for shot in self.project['shots']:
            item=result.get('shots',{}).get(shot['id'])
            if item and item['signature']==render_key(shot,self.project.get('export'),self.project.get('captions')):
                shot['result']={**shot.get('result',{}),**item}
        if result.get('final'):self.project['final']=result['final']

    def snapshot(self):
        self._adopt()
        from director_plan import public_status
        return dict(project=copy.deepcopy(self.project),motion_ready=motion_ready(),production_status=public_status())

    def catalogue(self):
        items=[]
        for path in DIRECTOR_DIR.glob('*/project.json'):
            try:
                p=json.loads(path.read_text('utf-8'));items.append(dict(id=p['id'],title=p['title'],shots=len(p['shots']),updated=path.stat().st_mtime))
            except (OSError,ValueError,KeyError):continue
        return dict(projects=sorted(items,key=lambda p:p['updated'],reverse=True))

    def open_project(self,data):
        from director_schema import valid_id
        with self.jobs.lock:
            if self.jobs.state['running']:raise ValueError('请等待当前任务完成或停止后再切换作品。')
            path=DIRECTOR_DIR/valid_id(data.get('id'),'项目')/'project.json'
            if not path.is_file():raise ValueError('这个作品不存在。')
            candidate=json.loads(path.read_text('utf-8'));validate_project(candidate,self.jobs.characters)
            self._save();self.project=candidate;self.active_work=None;self._save()
            self.jobs.state.update(status='done' if candidate.get('final') else 'idle',progress=100 if candidate.get('final') else 0,message='作品已打开，可继续预览或编辑。')
            return self.jobs.snapshot()

    def save(self,data):
        with self.jobs.lock:
            if self.jobs.state['running']:raise ValueError('请等待当前任务完成或停止后再修改。')
            spec=validate_project(data,self.jobs.characters)
            old=self.project if self.project and self.project['id']==spec['id'] else None
            if old and data.get('revision')!=old.get('revision',0):raise ValueError('作品已在其他页面更新，请刷新后重试，避免覆盖新修改。')
            for shot in spec['shots']:
                prior=next((s for s in old['shots'] if s['id']==shot['id']),None) if old else None
                if prior and render_key(prior,old.get('export'),old.get('captions'))==render_key(shot,spec['export'],spec['captions']):shot['result']=copy.deepcopy(prior.get('result',{}))
                elif prior and audio_key(prior)==audio_key(shot):
                    shot['result']={k:v for k,v in prior.get('result',{}).items() if k in ('audio','seconds','duration_extended')}
                # Retiming a line must not discard an already corrected first
                # frame and silently return to the rejected original composition.
                if prior and prior.get('result',{}).get('preflight',{}).get('reference_adjusted'):
                    from director_reference import reference_key
                    if (not shot.get('reuse_motion_from') and shot['speaker_id']==prior.get('speaker_id')
                            and reference_key(prior,old.get('export'))==reference_key(shot,spec['export'])):
                        recovered={k:v for k,v in prior['result'].items() if k in ('reference','preflight','reference_retry_count')}
                        shot.setdefault('result',{}).update(copy.deepcopy(recovered))
                        shot['result']['signature']=render_key(shot,spec['export'],spec['captions'])
            same=old and spec['title']==old['title'] and export_settings(old.get('export'))==spec['export'] and [render_key(s,spec['export'],spec['captions']) for s in spec['shots']]==[render_key(s,old.get('export'),old.get('captions')) for s in old['shots']]
            same=same and [s.get('voice_mode','shot') for s in old['shots']]==[s['voice_mode'] for s in spec['shots']]
            same=same and old.get('sound',{'track':'none','level':-18,'duck':True,'fade':1})==spec['sound'] and old.get('script','')==spec['script'] and old.get('aliases','')==spec['aliases']
            from sound_library import mix_identity
            same=same and [mix_identity(s) for s in old['shots']]==[mix_identity(s) for s in spec['shots']]
            spec['final']=copy.deepcopy(old.get('final')) if same else None
            unchanged=same and old.get('authoring')==spec.get('authoring')
            unchanged=unchanged and [{k:s.get(k) for k in ('reference_images','story_beat','scene_name')} for s in old['shots']]==[{k:s.get(k) for k in ('reference_images','story_beat','scene_name')} for s in spec['shots']]
            spec['revision']=(old.get('revision',0) if old else 0)+(0 if unchanged else 1)
            self.project=spec;self.active_work=None;self._save()
            if not old:self.jobs.state.update(status='idle',progress=0,message='作品已保存，镜头可逐一试听、预览和生成。')
            return self.jobs.snapshot()

    def start(self,data):
        with self.jobs.lock:
            mode=data.get('mode')
            if mode not in ('reference','audio','voices','shot','all','assemble'):raise ValueError('生成类型无效。')
            if mode not in ('all','assemble','voices') and data.get('shot_id') not in [s.get('id') for s in data.get('project',{}).get('shots',[])]:raise ValueError('找不到需要生成的镜头。')
            if mode not in ('audio','voices','reference','assemble') and not motion_ready():raise ValueError('本地动作模型或运行环境不完整。当前便携包未包含动作模型，请使用完整工作区。')
            assert_runtime_allowed()
            from director_schema import drawing_options
            project=copy.deepcopy(data['project'])
            for shot in project.get('shots',[]):
                if shot.get('reference_layout')=='generated':shot.update(drawing_options(shot))
            self.save(project)
            work=WORKSPACE/'work/director_runs'/uuid.uuid4().hex;work.mkdir(parents=True,exist_ok=True)
            progress=work/'progress.json'
            job=dict(project=copy.deepcopy(self.project),mode=mode,shot_id=data.get('shot_id'),work=str(work),progress=str(progress))
            from image_engine import selected, preferred_flux_engine
            job.update(engine=selected(),reference_engine=preferred_flux_engine())
            path=work/'job.json';path.write_text(json.dumps(job,ensure_ascii=False),encoding='utf-8')
            self.active_work=work;self.jobs.state['director_work']=str(work);self.jobs.cancel.clear()
            self.jobs.state.update(running=True,status='running',progress=0,task_kind='director',character_id=None,message='正在准备自定义角色创作…')
            self.jobs._save()
            self.jobs.thread=threading.Thread(target=self._run,args=(path,progress),daemon=True);self.jobs.thread.start()
            return self.jobs.snapshot()

    def _run(self,path,progress):
        try:
            result=self.jobs._process([str(PYTHON),'-u',str(APP_DIR/'director_worker.py'),str(path)],progress_path=progress)
            with self.jobs.lock:
                self._adopt()
                detail=json.loads(progress.read_text(encoding='utf-8')) if progress.is_file() else {}
                if self.jobs.cancel.is_set():self.jobs.state.update(status='stopped',message='已停止，已完成的配音、动作和镜头已保留。')
                elif detail.get('partial'):self.jobs.state.update(status='partial',progress=detail.get('progress',0),message=detail.get('message','部分镜头未完成，可重试未完成镜头。'))
                elif result:self.jobs.state.update(status='error',message=detail.get('message','生成失败，请查看任务日志。'))
                else:self.jobs.state.update(status='done',progress=100,message=detail.get('message','制作完成。'))
        except Exception as exc:
            with self.jobs.lock:self.jobs.state.update(status='error',message=str(exc))
        finally:
            with self.jobs.lock:
                self.jobs.state['running']=False;self._save();self.active_work=None
                self.jobs.state.pop('director_work',None);self.jobs._save()

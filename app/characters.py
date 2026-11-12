"""Persistent, editable character library with immutable portrait versions."""
import copy
import hashlib
import json
import re
import threading
import uuid
from datetime import datetime
from settings import CHARACTER_DIR, CHARACTER_MODEL, CHARACTER_CONFIG, TRANSLATION_LLM, TRANSLATION_RUNTIME, CURRENT, ROLES
from portrait_spec import FRAMINGS, normalize_look
from portrait_prompt import PRIORITIES, DEFAULT_PRIORITIES
from voice_catalog import role_voice, validate_voice
from visual_styles import SOFT_PHOTO, SOFT_PHOTO_LABEL

STYLES = {'anime': '日系插画', 'guoman': '国漫插画', '3d': '3D动画', 'realistic': '写实',
          SOFT_PHOTO: SOFT_PHOTO_LABEL}


def normalize_role(data):
    if not isinstance(data, dict):
        raise ValueError('角色设定格式不正确。')
    role = {}
    for key, label, limit, required in [('name','名称',30,True), ('description','外貌描述',1200,False),
            ('outfit','服装',150,False), ('personality','性格',150,False)]:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value.strip()) > limit or (required and not value.strip()):
            raise ValueError(f'请填写角色{label}，不超过{limit}字。')
        role[key] = value.strip()
    role['look'] = normalize_look(data.get('look', {}))
    role['framing'] = data.get('framing', 'half')
    if role['framing'] not in FRAMINGS:
        raise ValueError('请选择头像、半身或全身构图。')
    if not role['description'] and not role['look']:
        raise ValueError('请至少选择一项明确特征，或填写外貌描述。')
    role['style'] = data.get('style', '3d')
    if role['style'] not in STYLES:
        raise ValueError('请选择支持的角色画风。')
    priorities=data.get('priorities',DEFAULT_PRIORITIES)
    if not isinstance(priorities,list) or len(priorities)>3 or any(not isinstance(k,str) or k not in PRIORITIES for k in priorities):
        raise ValueError('请最多选择三项需要优先落实的特征。')
    role['priorities']=list(dict.fromkeys(priorities))
    role['id'] = str(data.get('id') or uuid.uuid4().hex)
    if 'voice' in data:role['voice']=validate_voice(data['voice'])
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}', role['id']):
        raise ValueError('角色编号无效。')
    return role


def visual_key(role):
    spec = {k:role.get(k, '') for k in ('description','outfit','style')}
    # Keep existing half-body versions current until their actual visual settings change.
    if role.get('framing', 'half') != 'half':
        spec['framing'] = role['framing']
    if role.get('look'):
        spec['look'] = role['look']
    if sorted(role.get('priorities',DEFAULT_PRIORITIES))!=sorted(DEFAULT_PRIORITIES):
        spec['priorities']=sorted(role['priorities'])
    return hashlib.sha256(json.dumps(spec,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


def model_ready():
    from image_engine import selected,ready
    if selected()!='legacy':return ready()
    required = [CHARACTER_MODEL/'dreamshaper_8.safetensors',
        *(CHARACTER_CONFIG/p for p in ('model_index.json','text_encoder/config.json','unet/config.json','vae/config.json','scheduler/scheduler_config.json','tokenizer/vocab.json','tokenizer/merges.txt','tokenizer/tokenizer_config.json')),
        TRANSLATION_LLM,TRANSLATION_RUNTIME,
        *(TRANSLATION_RUNTIME.parent/p for p in ('ggml-base.dll','libllama.dll','ggml-cuda.dll','cublas64_13.dll','cublasLt64_13.dll'))]
    return all(path.is_file() for path in required)


class CharacterStore:
    def __init__(self, root=CHARACTER_DIR):
        self.root = root
        self.path = root/'library.json'
        self.lock = threading.RLock()
        self.root.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self.roles = json.loads(self.path.read_text(encoding='utf-8'))
        else:
            initial = ROLES
            try:
                project = json.loads(CURRENT.read_text(encoding='utf-8')).get('project')
                if project and isinstance(project.get('characters'),list):
                    initial = project['characters']
            except (OSError,ValueError):
                pass
            self.roles = [dict(normalize_role(r), images=[], image=None, archived=False, visual_key=None) for r in initial]
            self._write()

    def _write(self):
        temporary = self.path.with_suffix('.tmp')
        temporary.write_text(json.dumps(self.roles,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(self.path)
        from asset_names import try_sync_characters
        try_sync_characters(self.root, self.roles)

    def list(self):
        with self.lock:
            return [dict(copy.deepcopy(r),voice=role_voice(r)) for r in self.roles if not r.get('archived')]

    def get(self, role_id):
        with self.lock:
            for role in self.roles:
                if role['id'] == role_id and not role.get('archived'):
                    return dict(copy.deepcopy(role),voice=role_voice(role))
        raise ValueError('角色不存在或已移除。')

    def save(self, data):
        role = normalize_role(data)
        with self.lock:
            existing = next((r for r in self.roles if r['id']==role['id']), None)
            if existing and existing.get('archived'):
                raise ValueError('请先恢复已移除的角色。')
            if existing is None:
                existing = dict(images=[],image=None,visual_key=None,archived=False)
                self.roles.append(existing)
            if 'voice' not in role:role['voice']=role_voice(existing if existing.get('id') else role)
            existing.update(role, updated=datetime.now().isoformat(timespec='seconds'))
            self._write()
            return copy.deepcopy(existing)

    def archive(self, role_id, restore=False):
        with self.lock:
            for role in self.roles:
                if role['id'] == role_id:
                    role['archived'] = not restore
                    self._write()
                    return self.list()
        raise ValueError('找不到这个角色。')

    def publish(self, role_id, image, spec, seed, generation=None):
        with self.lock:
            role = next(r for r in self.roles if r['id']==role_id)
            if visual_key(role) != visual_key(spec):
                raise ValueError('人物设定已改变，请按最新设定重新绘制。')
            version = dict(image=image, seed=seed, visual_key=visual_key(spec),
                description=spec['description'],outfit=spec.get('outfit',''),style=spec['style'],
                framing=spec.get('framing','half'),look=copy.deepcopy(spec.get('look',{})),generation=generation or {},
                priorities=copy.deepcopy(spec.get('priorities',DEFAULT_PRIORITIES)),
                created=datetime.now().isoformat(timespec='seconds'))
            role['images'].append(version)
            role.update(image=image, visual_key=version['visual_key'])
            self._write()
            return copy.deepcopy(role)

    def portrait_detail(self,role_id,image):
        role=self.get(role_id)
        version=next((v for v in role.get('images',[]) if v['image']==image),None)
        if version is None or not re.fullmatch(r'/characters/media/[a-zA-Z0-9_-]{1,48}/[a-f0-9]{32}\.png',str(image)):
            raise ValueError('找不到这个角色的形象记录。')
        path=(self.root/image.removeprefix('/characters/media/')).with_suffix('.json')
        if not path.is_file():return dict(legacy=True)
        data=json.loads(path.read_text(encoding='utf-8'))
        return {k:data[k] for k in ('translation','plan','encoding','quality','content_check','width','height','review_status','model','engine','prompt','seconds',
                                  'requested_engine','reference_route','reference_engine','generation_prompt','prompt_translation',
                                  'model_sha256','model_source','model_revision',
                                  'text_encoder','encoder_sha256','encoder_source','encoder_revision','encoder_validation') if k in data}

    def register_asset(self, asset):
        """Register a worker-owned variant without replacing a selected master image."""
        with self.lock:
            role = next(r for r in self.roles if r['id'] == asset['role_id'])
            if any(v['image'] == asset['image'] for v in role.get('images', [])):
                return
            spec = asset['spec']
            role.setdefault('images', []).append(dict(image=asset['image'], seed=asset['seed'],
                visual_key=visual_key(spec), description=spec['description'], outfit=spec.get('outfit', ''),
                style=spec['style'], framing=spec.get('framing', 'half'), look=copy.deepcopy(spec.get('look', {})),
                created=datetime.now().isoformat(timespec='seconds'),
                generation=dict(asset_slot=asset['slot'], reference_image=asset.get('source_image', ''), review_status='pending')))
            if not role.get('image') and asset['slot'] == 'front':
                role.update(image=asset['image'], visual_key=visual_key(spec))
            self._write()

    def choose(self, role_id, image):
        with self.lock:
            role = next((r for r in self.roles if r['id']==role_id and not r.get('archived')), None)
            if role is None:
                raise ValueError('找不到这个角色。')
            version = next((v for v in role['images'] if v['image']==image), None)
            if version is None:
                raise ValueError('找不到这个形象版本。')
            role.update(image=image,visual_key=version['visual_key'])
            self._write()
            return copy.deepcopy(role)

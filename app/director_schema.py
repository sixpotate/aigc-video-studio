"""Validated shot specifications and deterministic cache identities."""
import hashlib
import json
import math
import re
import uuid
from settings import APP_DIR, CHARACTER_DIR, WORKSPACE, PROJECTS_DIR
from voice_catalog import VOICES, role_voice

DIRECTOR_DIR = PROJECTS_DIR/'导演项目'
DIRECTOR_CURRENT = WORKSPACE/'work/director_ui/current.json'
MOTION_ROOT = WORKSPACE/'work/motion_test'
MOTION_PYTHON = MOTION_ROOT/'venv/Scripts/python.exe'
EMOTIONS = {'calm':'冷静自然，语气平稳，有正常的语句停顿。', 'confident':'自信果断，重点词清晰有力，结尾有笃定的力量。',
            'angry':'明显愤怒，先压抑后爆发，语调有明显起伏，不要一直大喊。', 'surprised':'明显惊讶，先停顿，随后声调提高，带有难以置信的情绪。',
            'happy':'轻松愉快，带着笑意，语气明亮，重音有活力。', 'sad':'失落难过，低声克制，句尾稍慢，有情绪变化。'}
CAMERAS = {'medium':'Medium shot, keep the camera stationary.', 'close':'Close-up, keep the camera stationary.',
           'push':'Slow gentle camera push in toward the face.', 'reaction':'Static reaction close-up emphasizing the facial expression.',
           'extreme_close':'Tight facial close-up, stationary camera.', 'wide':'Wide shot, full body visible, stationary camera.'}
MAX_CAST = 4
MAX_SHOTS = 300
ACTION_LIMIT = 600
EXPORT_DEFAULT = {'ratio':'9:16','resolution':'540'}
EXPORT_SIZES = {'540':540, '720':720, '1080':1080, '1440':1440}
NATIVE_SIZES = {'9:16':(384,672), '16:9':(672,384), '1:1':(512,512)}


def export_settings(data=None):
    if data is not None and not isinstance(data,dict):raise ValueError('导出设置格式不正确。')
    value = {**EXPORT_DEFAULT, **(data or {})}
    if value.get('ratio') not in NATIVE_SIZES or value.get('resolution') not in EXPORT_SIZES:
        raise ValueError('请选择有效的画面比例和导出分辨率。')
    return {key:value[key] for key in EXPORT_DEFAULT}


def output_size(settings=None):
    value=export_settings(settings);short=EXPORT_SIZES[value['resolution']]
    return (short,short) if value['ratio']=='1:1' else ((short,round(short*16/9)) if value['ratio']=='9:16' else (round(short*16/9),short))


def cast_members(shot):
    return shot.get('cast') or [dict(role=shot['role'],image_hash=shot['image_hash'],action='')]

def digest(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def drawing_options(shot):
    """Resolve a saved task's choices before consulting the current preferences."""
    from image_engine import selected, preferred_flux_engine
    context=shot.get('visual_context') or {}
    return dict(engine=shot.get('engine') or context.get('engine') or selected(),
                reference_engine=shot.get('reference_engine') or context.get('reference_engine') or preferred_flux_engine())


def generated_uses_references(shot):
    # Even an empty-room shot can have an explicit or generated scene anchor.
    context=shot.get('visual_context') or {}
    return (not shot.get('visual_only',False) or bool(shot.get('scene_image')) or
            bool(context.get('scene_key') and shot.get('scene_description')))


def generated_recipe(shot, quantized=False):
    from image_engine import recipe
    return recipe(shot.get('visual_only',False),quantized=quantized,
                  references=generated_uses_references(shot),**drawing_options(shot))


def valid_id(value, label):
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{32}',value):
        raise ValueError(f'{label}编号无效。')
    return value

def number(value, minimum, maximum, label):
    try: value=float(value)
    except (ValueError,TypeError): raise ValueError(f'{label}必须是数字。')
    if not math.isfinite(value) or not minimum<=value<=maximum:raise ValueError(f'{label}应为{minimum}至{maximum}。')
    return value

def text(value, limit, label, required=False):
    if not isinstance(value,str) or len(value.strip())>limit or (required and not value.strip()):
        raise ValueError(f'{label}请填写{1 if required else 0}至{limit}字。')
    return value.strip()

def reference_path(role):
    url=role.get('image') or ''
    if not re.fullmatch(r'/characters/media/[a-zA-Z0-9_-]{1,48}/[a-f0-9]{32}\.png',url):
        raise ValueError(f'请先为「{role["name"]}」生成人物形象。')
    path=CHARACTER_DIR/url.removeprefix('/characters/media/')
    if not path.is_file():raise ValueError('角色图片不存在，请重新选择形象。')
    return path

def validate_project(data, store):
    from director_assets import asset_path
    from director_production import SPEECH_KINDS,EFFECTS,sound_settings,validate_reuse
    if not isinstance(data,dict):raise ValueError('作品格式不正确。')
    project_id=valid_id(data.get('id') or uuid.uuid4().hex,'项目')
    rows=data.get('shots')
    if not isinstance(rows,list) or not 1<=len(rows)<=MAX_SHOTS:raise ValueError(f'请添加1至{MAX_SHOTS}个镜头。')
    shots=[]
    for i,row in enumerate(rows,1):
        if not isinstance(row,dict):raise ValueError('镜头格式不正确。')
        role_ids=row.get('role_ids',[row.get('role_id')])
        if not isinstance(role_ids,list) or not 1<=len(role_ids)<=MAX_CAST or any(not isinstance(r,str) for r in role_ids):
            raise ValueError(f'每个镜头请选择1至{MAX_CAST}名同框角色。')
        if len(set(role_ids))!=len(role_ids):raise ValueError('同框角色不能重复。')
        actions=row.get('actor_actions',{})
        if not isinstance(actions,dict) or any(k not in role_ids for k in actions):raise ValueError('人物动作必须对应已选的同框角色。')
        references=row.get('reference_images',{})
        if not isinstance(references,dict) or any(k not in role_ids for k in references):raise ValueError('固定参考图必须对应已选角色。')
        references=dict(references)
        bible=data.get('visual_bible',{})
        if not isinstance(bible,dict) or not isinstance(bible.get('actors',{}),dict):raise ValueError('作品人物参考记录格式不正确。')
        frozen=bible.get('actors',{}) if isinstance(bible,dict) else {}
        cast=[]
        for role_id in role_ids:
            role=store.get(role_id)
            pinned=frozen.get(role_id,{})
            if not isinstance(pinned,dict):raise ValueError('固定人物参考格式不正确。')
            if pinned.get('image') and not references.get(role_id):references[role_id]=pinned['image']
            if references.get(role_id):
                version=next((v for v in role.get('images',[]) if v['image']==references[role_id]),None)
                if not version:raise ValueError('固定的角色参考图不属于该角色，请重新选择。')
                role={**role,**{k:version[k] for k in ('image','description','outfit','style','framing') if k in version}}
                if pinned.get('image')==references[role_id]:
                    role={**role,**{k:pinned[k] for k in ('description','outfit','style','framing') if k in pinned}}
            reference=reference_path(role)
            cast.append(dict(role={k:role.get(k,'') for k in ('id','name','image','style','description','outfit')},
                image_hash=hashlib.sha256(reference.read_bytes()).hexdigest(),action=text(actions.get(role_id,''),160,'单人动作')))
            if role.get('framing')=='half':cast[-1]['role']['framing']='half'
        speaker=row.get('speaker_id',row.get('role_id') or role_ids[0])
        if speaker!='narrator' and speaker not in role_ids:raise ValueError('说话人必须是本镜头的同框角色，或选择旁白。')
        lead=next((m for m in cast if m['role']['id']==speaker),cast[0]);role=lead['role']
        voice_mode=row.get('voice_mode','shot' if 'voice' in row else 'role')
        if voice_mode not in ('role','shot'):raise ValueError('音色来源无效。')
        voice=role_voice(store.get(role['id'])) if voice_mode=='role' and speaker!='narrator' else row.get('voice','Serena')
        emotion=row.get('emotion','calm');camera=row.get('camera','medium')
        if voice not in VOICES or emotion not in EMOTIONS or camera not in CAMERAS:raise ValueError('请选择有效的声音、情绪和取景。')
        seed=number(row.get('seed',42+i*71),0,2**31-1,'随机种子')
        if int(seed)!=seed:raise ValueError('随机种子必须是整数。')
        face=row.get('face_box')
        if face is not None:
            if not isinstance(face,list) or len(face)!=4:raise ValueError('人脸位置需要左、上、宽、高四个百分比。')
            face=[number(v,0,100,'人脸位置') for v in face]
            if face[2]<5 or face[3]<5 or face[0]+face[2]>100 or face[1]+face[3]>100:raise ValueError('人脸区域必须位于画面内，宽高至少5%。')
        shot=dict(id=valid_id(row.get('id') or uuid.uuid4().hex,'镜头'),role_id=role['id'],
            role={k:role.get(k,'') for k in ('id','name','image','style','description','outfit')},
            image_hash=lead['image_hash'],role_ids=role_ids,speaker_id=speaker,cast=cast,
            actor_actions={m['role']['id']:m['action'] for m in cast if m['action']},
            text=text(row.get('text',''),40,'每镜台词'),action=text(row.get('action',''),ACTION_LIMIT,'人物动作',True),
            voice=voice,voice_mode=voice_mode,emotion=emotion,emotion_note=text(row.get('emotion_note',''),100,'表演补充'),
            duration=None if row.get('duration') is None else number(row['duration'],1,15,'镜头时长'),
            speed=number(row.get('speed',1),.8,1.25,'语速'),pause_before=number(row.get('pause_before',.12),0,2,'开口前停顿'),
            pause_after=number(row.get('pause_after',.3),0,3,'句后停顿'),camera=camera,seed=int(seed),
            lip_sync=bool(row.get('lip_sync',True)),face_box=face)
        kind=row.get('speech_kind','narration' if speaker=='narrator' else 'dialogue')
        if kind not in SPEECH_KINDS:raise ValueError('说话方式无效。')
        scene=text(row.get('scene_image',''),64,'场景素材')
        if scene:asset_path(scene,'background')
        visual_only=row.get('visual_only',False)
        if not isinstance(visual_only,bool):raise ValueError('场景镜头选项无效。')
        if visual_only and not scene:raise ValueError('纯场景镜头需要先选择一张背景图片。')
        animate_scene=row.get('animate_scene',False)
        if not isinstance(animate_scene,bool) or (animate_scene and not visual_only):raise ValueError('环境动作仅适用于纯场景镜头。')
        effect=row.get('effect','none')
        if effect not in EFFECTS:raise ValueError('音效类型无效。')
        shot.update(speech_kind=kind,scene_image=scene,scene_description=text(row.get('scene_description',''),240,'场景说明'),
                    visual_only=visual_only,onscreen_text=text(row.get('onscreen_text',''),100,'画面文字'),
                    subtitle_name=text(row.get('subtitle_name',''),24,'字幕称呼'),effect=effect,
                    effect_time=number(row.get('effect_time',0),0,15,'音效出现时间'),effect_level=number(row.get('effect_level',-12),-36,0,'音效音量'),
                    reuse_motion_from=text(row.get('reuse_motion_from',''),32,'动作来源'),source_shot=text(str(row.get('source_shot','')),16,'原稿镜号'))
        motion_seconds=row.get('motion_seconds',3)
        if motion_seconds not in (3,6):raise ValueError('基础动作长度请选择3秒或6秒。')
        shot['motion_seconds']=motion_seconds
        if animate_scene:shot['animate_scene']=True
        lip_mode=row.get('lip_mode','auto')
        if lip_mode not in ('auto','anime','neural'):raise ValueError('口型方式无效。')
        shot['lip_mode']=lip_mode
        if row.get('reference_layout'):
            if row['reference_layout'] not in ('faces','generated'):raise ValueError('人物同框构图方式无效。')
            shot['reference_layout']=row['reference_layout']
        from story_integrity import MOTIONS
        movement = row.get('camera_motion', 'auto')
        if movement not in MOTIONS:raise ValueError('镜头运动无效。')
        if movement != 'auto':shot['camera_motion'] = movement
        if row.get('start_state'):shot['start_state'] = text(row['start_state'],160,'镜头起始状态')
        if row.get('sound_cues'):
            from sound_library import validate_cues
            shot['sound_cues'] = validate_cues(row['sound_cues'])
        if references:shot['reference_images']=dict(references)
        for key,limit in [('story_beat',120),('scene_name',50)]:
            if row.get(key):shot[key]=text(row[key],limit,'剧情与场景备注')
        if role.get('framing')=='half':shot['role']['framing']='half'
        # Internal snapshots survive saving/reopening a queued or completed job.
        context=row.get('visual_context') if isinstance(row.get('visual_context'),dict) else {}
        for key in ('engine','reference_engine'):
            value=row.get(key) or context.get(key)
            if value is not None:
                from image_engine import ENGINES, resolve_engine
                if key=='engine' and (not isinstance(value,str) or value not in {*ENGINES,'legacy'}):
                    raise ValueError('镜头绘图模型无效。')
                if key=='reference_engine':resolve_engine(reference_engine=value)
                shot[key]=value
        shots.append(shot)
    if len({s['id'] for s in shots})!=len(shots):raise ValueError('镜头编号不能重复。')
    captions=data.get('captions',{})
    if not isinstance(captions,dict) or not isinstance(captions.get('speaker_name',False),bool):raise ValueError('字幕角色名开关无效。')
    validate_reuse(shots)
    result=dict(id=project_id,title=text(data.get('title',''),60,'作品名称') or '自定义角色短剧',shots=shots,
                export=export_settings(data.get('export')),captions={'speaker_name':captions.get('speaker_name',False)},
                sound=sound_settings(data.get('sound')),script=text(data.get('script',''),60000,'原始剧本'),aliases=text(data.get('aliases',''),4000,'角色别名'))
    if data.get('authoring'):
        info=data['authoring']
        if not isinstance(info,dict):raise ValueError('创作来源格式不正确。')
        result['authoring']=dict(document_id=valid_id(info.get('document_id'),'创作工程'),
            episode=int(number(info.get('episode'),1,12,'来源集数')),
            target_seconds=number(info.get('target_seconds'),30,86400 if info.get('input_mode')=='script' else 600,'目标时长'))
        if info.get('input_mode')=='script':result['authoring']['input_mode']='script'
    from director_plan import prepare_project
    return prepare_project(result,data.get('visual_bible'))

def speech_key(shot):
    return digest({k:shot[k] for k in ('text','voice','emotion','emotion_note') } | {'model':'Qwen3-TTS-1.7B-CustomVoice','version':1})

def audio_key(shot):
    value=dict(voice=speech_key(shot),speed=shot['speed'],before=shot['pause_before'],after=shot['pause_after'],version=1)
    if shot.get('duration') is not None:value['duration']=shot['duration']
    if shot.get('speech_kind')=='chorus':value['chorus']=1
    return digest(value)

def shot_key(shot):
    value={k:v for k,v in shot.items() if k!='result'}
    if shot.get('reference_layout')=='generated':
        from image_engine import recipe
        value['first_frame_recipe']=generated_recipe(shot)
        context=shot.get('visual_context') or {}
        if not shot.get('scene_image') and context.get('scene_key') and shot.get('scene_description'):
            value['scene_master_recipe']=recipe(**drawing_options(shot))
        # Cache identity follows the engine that really draws the image, not
        # the requested SDXL label when an unchanged FLUX reference is used.
        value.pop('engine',None);value.pop('reference_engine',None)
        if context:
            value['visual_context']={k:v for k,v in context.items() if k not in ('engine','reference_engine')}
    # Binding is an editing preference; the resolved voice determines the audio.
    value.pop('voice_mode',None)
    if value.get('lip_mode')=='auto' and shot.get('role',{}).get('style')!='anime':value.pop('lip_mode',None)
    for key in ('effect','effect_time','effect_level','sound_cues','source_shot','reference_images','story_beat','scene_name'):value.pop(key,None)
    for key,default in dict(speech_kind='dialogue',scene_image='',scene_description='',visual_only=False,animate_scene=False,onscreen_text='',subtitle_name='',reuse_motion_from='',motion_seconds=3).items():
        if value.get(key)==default:value.pop(key,None)
    if shot.get('speaker_id')=='narrator' and value.get('speech_kind')=='narration':value.pop('speech_kind',None)
    if value.get('duration') is None:value.pop('duration',None)
    members=cast_members(shot)
    # A legacy one-person project keeps its existing clips and completed mix.
    if len(members)==1 and not members[0].get('action') and shot.get('speaker_id',shot['role_id'])==shot['role_id']:
        for key in ('role_ids','speaker_id','cast','actor_actions'):value.pop(key,None)
    return digest(value | {'renderer_version':3 if shot.get('scene_image') else 2})


def render_key(shot, settings=None, captions=None):
    settings=export_settings(settings)
    key=shot_key(shot) if settings==EXPORT_DEFAULT else digest(dict(shot=shot_key(shot),export=settings,version=3))
    return digest(dict(render=key,speaker_name=True,version=1)) if (captions or {}).get('speaker_name') else key

def motion_ready():
    from director_plan import ready_720
    if MOTION_PYTHON.is_file() and ready_720():return True
    model=MOTION_ROOT/'models/distill_fp8'
    return MOTION_PYTHON.is_file() and all((model/f).is_file() for f in ['non_block.safetensors','models_t5_umt5-xxl-enc-fp8.pth','clip-fp8.pth','Wan2.1_VAE.pth',*[f'block_{i}.safetensors' for i in range(40)]])

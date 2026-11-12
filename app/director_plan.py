"""Project visual continuity and automatic coverage; no extra authoring fields."""
import copy
import json
import math
import re
from settings import APP_DIR
from visual_styles import SOFT_PHOTO, SOFT_PHOTO_DIRECTOR_PROMPT

VERSION=1
POLICY_PATH=APP_DIR/'video_models.json'
STYLE_PROMPTS={
    'realistic':'Photorealistic live-action film, believable adult anatomy, natural skin texture, physically plausible light, coherent cinematic color grading.',
    SOFT_PHOTO:SOFT_PHOTO_DIRECTOR_PROMPT,
    '3d':'Consistent cinematic 3D animation, physically based materials, coherent body proportions, natural lighting. Do not mix flat cartoon drawings with realistic characters.',
    'guoman':'统一国漫动画质感，所有人物、场景和道具采用同一种渲染与上色方式，保持人物年龄和身材比例。',
    'anime':'统一日系动画风格，稳定线条与赛璐璐上色，人物、场景和道具画法一致。',
}

def policy():
    try:return json.loads(POLICY_PATH.read_text('utf-8'))
    except (OSError,ValueError):return {'quality_enabled':False}

def ready_720(width=704,height=1280,frames=73,steps=50):
    root=APP_DIR/'work/motion_test/models'
    rules=policy()
    accepted=any(p.get('width')==width and p.get('height')==height and p.get('max_frames',0)>=frames
                 and p.get('steps')==steps for p in rules.get('accepted_profiles',[]))
    return bool(rules.get('quality_enabled') and 'wan22_5b' not in rules.get('blocked_models',{}) and accepted
        and (root/'wan22_5b_bf16/准备完成.json').is_file()
        and (root/'wan22_5b_source/Wan2.2_VAE.pth').is_file())

def shot_kind(shot):
    text=shot.get('action','')+' '+shot.get('scene_description','')
    if shot.get('visual_only') or re.search(r'爆炸|爆破|黑烟|核爆|火焰|闪电|幻化|坍塌',text):return 'effects'
    if re.search(r'奔跑|追逐|搏斗|打斗|挥剑|开枪|跳跃|摔倒|飞出|攻击|砸|撞',text):return 'action'
    if len(shot.get('cast',[]))>1:return 'ensemble'
    return 'dialogue' if shot.get('text') else 'performance'

def profile_for(shot,ratio='9:16'):
    kind=shot_kind(shot)
    # Only accepted local engines are eligible. A missing candidate is never presented as installed.
    size={'9:16':(704,1280),'16:9':(1280,704),'1:1':(960,960)}[ratio]
    if ready_720(*size):
        return dict(id='wan22_5b',model='Wan2.2 · 本地精细制作',kind=kind,width=size[0],height=size[1],
                    fps=24,steps=50,max_seconds=3.,version=VERSION)
    size={'9:16':(384,672),'16:9':(672,384),'1:1':(512,512)}[ratio]
    return dict(id='wan21_distill',model='Wan2.1 · 兼容制作',kind=kind,width=size[0],height=size[1],
                fps=16,steps=4,max_seconds=3.,version=VERSION)


def public_status():
    rules=policy()
    return dict(native_720_ready=ready_720(),message=(
        '当前使用兼容动作模型；新720P模型因稳定性验收中断暂停使用。画面检查和细节修复使用CPU。'
        if rules.get('blocked_models',{}).get('wan22_5b') else
        '动作按本机已验收的模型生成；导出尺寸与原生生成尺寸分别显示。'))

def prepare_project(project,existing=None):
    from director_schema import digest,cast_members
    existing=existing if isinstance(existing,dict) else {}
    first=project['shots'][0]
    style=existing.get('style') or first['role'].get('style','3d')
    if style not in STYLE_PROMPTS:style='3d'
    actors={};scenes={}
    for shot in project['shots']:
        for member in cast_members(shot):
            role=member['role'];actors[role['id']]={**role,'image_hash':member['image_hash']}
        scene_key=digest(dict(image=shot.get('scene_image',''),description=shot.get('scene_description',''),style=style))
        scenes.setdefault(scene_key,dict(description=shot.get('scene_description',''),image=shot.get('scene_image','')))
        # Per-shot identity snapshots prevent a different image of a recurring actor leaking into its neighbours.
        context=dict(version=VERSION,style=style,style_prompt=STYLE_PROMPTS[style],scene_key=scene_key,
                     identities=[{k:m['role'].get(k,'') for k in ('id','name','description','outfit','image')} for m in cast_members(shot)])
        shot['visual_context']=context
        shot['production_profile']=profile_for(shot,project['export']['ratio'])
    project['visual_bible']=dict(version=VERSION,style=style,actors=actors,scenes=scenes)
    return project

def coverage_plan(shot,audio,profile):
    """Cover the complete, unchanged waveform with forward-only visual takes."""
    listener=next((m for m in shot.get('cast',[]) if m['role']['id']!=shot.get('speaker_id')),None)
    dialogue=shot.get('text') and shot.get('speech_kind','dialogue')=='dialogue' and profile['kind'] in ('dialogue','ensemble')
    from dialogue_timing import cut_boundaries,boundary_basis
    pauses=audio.get('pause_windows',[]) if dialogue else []
    bounds=cut_boundaries(audio['seconds'],profile['max_seconds'],pauses)
    plans=[]
    for i,(start,end) in enumerate(zip(bounds,bounds[1:])):
        take=copy.deepcopy(shot);take.pop('result',None)
        take['seed']=(shot['seed']+i*1543)%2147483647
        mode='original' if not i else 'continuation'
        if i and dialogue:
            mode='reaction' if listener and i%2 else 'speaker'
            if mode=='reaction':
                member=copy.deepcopy(listener);member['action']='保持原有位置，听对方说话，以眼神、眉毛和呼吸自然回应，不开口。'
                take.update(role=member['role'],role_id=member['role']['id'],role_ids=[member['role']['id']],
                    cast=[member],speaker_id='narrator',image_hash=member['image_hash'],text='',lip_sync=False,speech_kind='narration',
                    actor_actions={member['role']['id']:member['action']},camera='reaction',camera_motion='static',
                    action=member['action'],start_state='对方说话时，人物安静聆听，视线朝向对方。',face_box=None)
            else:
                member=next((m for m in take.get('cast',[]) if m['role']['id']==take['speaker_id']),None)
                if member:
                    take.update(role=member['role'],role_id=member['role']['id'],role_ids=[member['role']['id']],cast=[member],
                                image_hash=member['image_hash'],actor_actions={},face_box=None)
                take.update(camera='close' if i%2 else 'medium',camera_motion='static',
                    action='在同一位置继续说话，保留当前情绪和衣着，细微表情和头肩活动，不重复上一段已经完成的大动作。',
                    start_state='延续同场戏中人物的状态，视线朝向对话对象。')
            take['visual_context']={**shot.get('visual_context',{}),'identities':[
                {k:m['role'].get(k,'') for k in ('id','name','description','outfit','image')} for m in take.get('cast',[])]}
        elif i:
            take['continuation']=True
            take['start_state']='上一段实际结束后的当前状态，动作继续向前发展，不返回开始姿势。'
        if take.get('camera')=='wide' and profile['kind'] in ('action','effects'):
            take['lip_sync']=False
        seconds=(end-start)/25
        frames=math.ceil((seconds*profile['fps']-1)/4)*4+1
        plans.append(dict(index=i,start=start/25,seconds=seconds,frames=max(5,frames),mode=mode,shot=take,
            cut_basis='opening' if not i else boundary_basis(start,pauses)))
    return plans

def quality_summary(shots):
    values=[s.get('result',{}) for s in shots]
    sizes=sorted({(v.get('native_width',0),v.get('native_height',0)) for v in values if v.get('native_width')})
    return dict(native_sizes=[list(s) for s in sizes],
        reviewed=sum(v.get('quality',{}).get('status')=='passed' for v in values),
        needs_review=sum(v.get('quality',{}).get('status') not in ('passed',None) for v in values),
        ai_upscaled=sum(bool(v.get('enhancement',{}).get('applied')) for v in values),
        total=len(values),version=VERSION)

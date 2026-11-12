"""Project-level sound and reusable motion specifications, separate from the UI."""
import re
from director_assets import asset_path

MUSIC_STYLES={'none':'不加音乐','comedy':'轻快喜剧','suspense':'悬疑计谋'}
EFFECTS={'none':'无','bang':'拍桌 / 砰','ding':'灵光一闪 / 叮','ring':'电话铃声','boing':'滑稽转折','whistle':'口哨','paper':'翻纸'}
SPEECH_KINDS={'dialogue':'角色对白','os':'内心独白（不制作对白口型）','narration':'画外音（不制作对白口型）','chorus':'齐声（叠加人声）'}


_COVER = re.compile(
    r'(?:全封闭|完全封闭|封闭式|全覆盖|不透明).{0,8}(?:头盔|面罩)|'
    r'(?:头盔|面罩).{0,8}(?:全封闭|完全封闭|封闭式|闭合|覆盖口鼻|覆盖整张脸)|'
    r'(?:面甲|面罩).{0,6}(?:遮住|遮挡|覆盖).{0,6}(?:嘴部|嘴唇|口鼻)|'
    r'(?:佩戴|戴着|戴上|戴).{0,5}(?:口罩|防毒面具)|'
    r'(?:嘴部|嘴唇|口鼻).{0,6}(?:被.{0,10})?(?:遮住|遮挡|覆盖)|'
    r'(?:full[- ]face|fully[- ]enclosed|sealed|opaque).{0,10}(?:helmet|mask)|'
    r'(?:mouth|lips).{0,16}(?:covered|concealed)', re.I)
_UNCOVER = re.compile(
    r'(?:摘下|摘掉|取下|脱下|揭开|掀起|抬起).{0,8}(?:头盔|面罩|口罩|防毒面具)|'
    r'(?:露出|露着).{0,6}(?:嘴部|嘴唇|整张脸)|'
    r'(?:removes?|takes? off|lifts?).{0,20}(?:helmet|mask|visor)|'
    r'(?:mouth|lips).{0,8}(?:visible|exposed|uncovered)', re.I)
_NEGATED = re.compile(r'(?:不|没|没有|未|无|并非|不是|不再|not |without )(?:佩戴|戴着|戴|wearing |an? )?\s*$', re.I)


def speaker_mouth_covered(shot):
    """Only explicit speaker-specific coverings bypass visible-mouth synthesis.

    A helmet alone, a detection failure, or another actor's outfit is not enough.
    Current actor directions can expose a mouth hidden by the default costume.
    """
    speaker=shot.get('speaker_id',shot.get('role_id'))
    if speaker=='narrator':return False
    members=shot.get('cast') or [dict(role=shot.get('role',{}),action='')]
    member=next((m for m in members if m.get('role',{}).get('id')==speaker),None)
    if member is None:return False
    role=member['role'];covered=False
    texts=[role.get('description',''),role.get('outfit','')]
    if len(members)==1:texts.append(shot.get('action',''))
    texts.append(member.get('action',''))
    texts.append(shot.get('actor_actions',{}).get(speaker,''))
    for text in texts:
        for clause in re.split(r'[。！？\n；;]',text):
            events=[(m.start(),True,m) for m in _COVER.finditer(clause)]
            events.extend((m.start(),False,m) for m in _UNCOVER.finditer(clause))
            for _,value,match in sorted(events,key=lambda event:event[0]):
                internal_negative=re.search(r'没有|不是|并非|不再|未|\bnot\b|\bwithout\b',match.group(),re.I)
                if not internal_negative and not _NEGATED.search(clause[:match.start()]):covered=value
    return covered


def needs_lip_sync(shot):
    return bool(shot.get('lip_sync',True) and shot.get('text')
        and shot.get('speaker_id')!='narrator'
        and shot.get('speech_kind') not in ('os','narration','chorus')
        and not shot.get('visual_only') and not speaker_mouth_covered(shot))

def sound_settings(value=None):
    from director_schema import number
    value=value or {}
    if not isinstance(value,dict):raise ValueError('配乐设置格式不正确。')
    track=value.get('track','none')
    if track not in MUSIC_STYLES:
        if not isinstance(track,str) or not track.startswith('asset:'):raise ValueError('请选择有效配乐。')
        asset_path(track[6:],'music')
    if not isinstance(value.get('duck',True),bool):raise ValueError('人声避让设置无效。')
    return dict(track=track,level=number(value.get('level',-18),-36,-6,'配乐相对音量'),duck=value.get('duck',True),fade=number(value.get('fade',1),0,5,'音乐淡入淡出'))

def motion_source(shot,project):
    by_id={s['id']:s for s in project['shots']};seen=set()
    while shot.get('reuse_motion_from'):
        if shot['id'] in seen:raise ValueError('动作复用出现循环。')
        seen.add(shot['id']);shot=by_id[shot['reuse_motion_from']]
    return shot

def validate_reuse(shots):
    from director_schema import digest
    by_id={s['id']:i for i,s in enumerate(shots)}
    for i,shot in enumerate(shots):
        source=shot.get('reuse_motion_from','')
        if source and (source not in by_id or by_id[source]>=i):raise ValueError('只能复用前面已经编排的镜头，不能引用自己或后面的镜头。')
        if source:
            root=motion_source(shot,dict(shots=shots))
            fields=('role_ids','camera','scene_image','scene_description','visual_only')
            if any(shot.get(k)!=root.get(k) for k in fields):raise ValueError('复用动作时，人物、场景和取景必须与来源镜头一致；可以改变台词、情绪、音色和停顿。')
            if bool(shot.get('animate_scene'))!=bool(root.get('animate_scene')):raise ValueError('动态环境镜头与静态环境镜头不能混用动作。')
            if any(shot.get(k)!=root.get(k) for k in ('camera_motion','start_state')):raise ValueError('复用动作时，起始状态和运镜方向也应与来源一致。')
            shot['motion_source_fingerprint']=digest({k:root.get(k) for k in ('cast','action','actor_actions','camera','scene_image','scene_description','visual_only','seed','motion_seconds')})
            if root.get('animate_scene'):shot['motion_source_fingerprint']=digest(dict(source=shot['motion_source_fingerprint'],animate_scene=True))
            if root.get('camera_motion') or root.get('start_state'):
                shot['motion_source_fingerprint']=digest(dict(source=shot['motion_source_fingerprint'],camera_motion=root.get('camera_motion'),start_state=root.get('start_state')))


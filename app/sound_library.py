"""Local, licensed sound assets and conservative story-event matching."""
import hashlib
import json
import re
from functools import lru_cache
from settings import SOUND_LIBRARY_DIR
from sound_names import display_name

ROOT = SOUND_LIBRARY_DIR
INDEX = ROOT/'audio_index.json'
LABELS = dict(alarm='警报', forest='树林环境', monster='怪物吼叫', ghost='幽灵低吟', announcer_en='英文播报素材',
    metal='金属碰撞', punch='拳脚打击', wood='木材撞击', glass='玻璃碰撞', explosion='爆炸',
    laser='科幻武器', engine='机械引擎', computer='电脑运算', energy='能量变化', sword='刀剑挥动',
    draw_blade='拔刀', mechanism='机械卡扣', door='开关门', paper='纸张书本', cloth='衣物摩擦',
    footstep='脚步', footstep_grass='草地脚步', foley='其他拟音')


@lru_cache(maxsize=2)
def _read(stamp):
    return json.loads(INDEX.read_text(encoding='utf-8'))


def catalogue():
    try:return _read(INDEX.stat().st_mtime_ns)
    except (OSError, ValueError):return dict(version=1,items=[],counts={})


def media_path(ident):
    if not isinstance(ident,str) or not re.fullmatch(r'[a-f0-9]{32}',ident):raise ValueError('音效编号无效。')
    item=next((i for i in catalogue()['items'] if i['id']==ident),None)
    if not item:raise ValueError('这条本地音效尚未安装。')
    path=(ROOT/item['path']).resolve()
    if not path.is_relative_to(ROOT.resolve()) or not path.is_file():raise ValueError('本地音效文件缺失。')
    return path


def public_catalogue():
    values=catalogue()
    return dict(count=len(values['items']),categories={k:LABELS.get(k,k) for k in values['counts']},
        items=[dict(id=i['id'],name=display_name(i),category=i['category'],seconds=i['seconds'],license=i['license'],
                    source=i['source'],url='/sound-library/'+i['id']) for i in values['items']])


def choose(group, seed=0, ambient=False):
    candidates=[i for i in catalogue()['items'] if i['category']==group]
    if ambient and group=='engine':
        candidates=[i for i in candidates if 'spaceenginelow' in i['name'].lower()]
    if not candidates:return None
    position=int(hashlib.sha256(str(seed).encode()).hexdigest()[:8],16)%len(candidates)
    return candidates[position]


def plan_cues(action, scene='', seed=0):
    # Do not trigger effects from dialogue, or from explicitly negated actions.
    clauses=[c for c in re.split('[，。；！!?？\n]',action) if not re.search(r'没有|并未|不曾|无需|不要|不发出|未曾|不会|不应|禁止',c)]
    value='，'.join(clauses)
    groups=[]
    rules=[(r'警报(?:声|灯)?|警笛', 'alarm'),(r'爆炸|炸出|被炸|炸得|轰隆|砸在地上', 'explosion'),
        (r'开枪|扣动扳机|枪口.{0,4}火光|激光射', 'laser'),
        (r'上膛|机械.{0,3}卡扣', 'mechanism'),
        (r'爪.{0,8}(?:胸甲|铠甲)|金属.{0,5}碰撞|铛', 'metal'),
        (r'挥剑|反手一剑|剑.{0,8}劈|挥刀', 'sword'),
        (r'拔剑|拔刀|抽出.{0,4}(?:剑|刀)', 'draw_blade'),
        (r'一拳|踢中|拳头.{0,6}击中', 'punch'),
        (r'(?:怪物|野兽|妖兽).{0,8}(?:吼叫|咆哮)', 'monster'),
        (r'(?:幽灵|鬼魂).{0,8}(?:低吟|哀嚎)', 'ghost'),
        (r'打开.{0,3}门|关上.{0,3}门|推开.{0,3}门', 'door'),
        (r'翻开.{0,4}书|翻动.{0,4}纸', 'paper'),
        (r'一步步走|脚步声|走过来|走向', 'footstep_grass' if re.search(r'树林|山间|山路|草地',scene) else 'footstep')]
    ordered=[]
    for pattern,group in rules:
        match=re.search(pattern,value)
        if match:ordered.append((match.start(),group))
    for _,group in sorted(ordered):
        if group not in groups:groups.append(group)
    cues=[]
    for n,group in enumerate(groups[:3]):
        item=choose(group,str(seed)+group)
        if item:cues.append(dict(asset_id=item['id'],category=group,at_ratio=min(.7,.2+n*.18),level=-15 if group in ('explosion','laser') else -20,loop=False))
    ambient='engine' if re.search(r'战舰内部|机舱|发动机房',scene) else ('forest' if re.search(r'树林|山间|山路|森林',scene) else None)
    item=choose(ambient,str(seed)+'ambient',ambient=True) if ambient else None
    if item:cues.append(dict(asset_id=item['id'],category=ambient,at_ratio=0,level=-32,loop=True))
    return cues


def validate_cues(value):
    if not isinstance(value,list) or len(value)>8:raise ValueError('自动声音安排格式无效。')
    result=[]
    for cue in value:
        if not isinstance(cue,dict):raise ValueError('自动声音安排格式无效。')
        media_path(cue.get('asset_id'))
        at,level=cue.get('at_ratio',0),cue.get('level',-20)
        if type(at) not in (int,float) or not 0<=at<=.95 or type(level) not in (int,float) or not -48<=level<=0 or type(cue.get('loop',False)) is not bool:
            raise ValueError('自动音效位置或音量无效。')
        result.append(dict(asset_id=cue['asset_id'],category=str(cue.get('category',''))[:40],at_ratio=at,level=level,loop=cue.get('loop',False)))
    return result


def mix_identity(shot):
    legacy=(shot.get('effect','none'),shot.get('effect_time',0),shot.get('effect_level',-12))
    return legacy+(shot['sound_cues'],) if shot.get('sound_cues') else legacy

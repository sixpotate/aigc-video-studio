"""Labels translated from pack filenames; do not invent monster species."""
import re

ANNOUNCER = {
 'arcade_mode':'街机模式', 'battle_mode':'对战模式', 'begin':'开始',
 'championship_mode':'锦标赛模式', 'choose_your_character':'选择角色', 'combo':'连击',
 'combo_breaker':'打断连击', 'deathmatch':'死亡竞赛', 'fight':'开战',
 'final_round':'最终回合', 'flawless_victory':'完美胜利', 'game_over':'游戏结束',
 "it's_a_tie":'平局宣告', 'kill_her':'击杀她', 'kill_him':'击杀他', 'kill_it':'击杀它',
 'loser':'败者', 'multi_kill':'多重击杀', 'prepare_yourself':'做好准备', 'ready':'准备',
 'story_mode':'剧情模式', 'sudden_death':'骤死模式', 'survival_mode':'生存模式',
 'tie':'平局', 'tie_breaker':'决胜回合', 'time':'时间', 'winner':'胜者',
 'you_lose':'你输了', 'you_win':'你赢了',
}
WORDS = {
 'alarm':'警报', 'cloth':'衣物摩擦', 'clothBelt':'布质腰带摩擦',
 'computerNoise':'电脑运算声', 'doorClose':'关门', 'doorOpen':'开门',
 'drawKnife':'拔刀', 'forceField':'科幻力场', 'engineCircular':'循环机械引擎',
 'spaceEngineLarge':'大型太空引擎', 'spaceEngineLow':'低沉太空引擎',
 'spaceEngineSmall':'小型太空引擎', 'spaceEngine':'太空引擎', 'thrusterFire':'推进器点火',
 'explosionCrunch':'碎裂爆炸', 'lowFrequency_explosion':'低频爆炸',
 'impactBell':'钟体撞击', 'impactGeneric':'通用撞击', 'impactMining':'采掘敲击',
 'impactSoft':'柔软物体撞击', 'beltHandle':'皮带操作', 'chop':'劈砍', 'creak':'吱嘎声',
 'dropLeather':'皮革落下', 'handleCoins':'硬币拨动', 'handleSmallLeather':'小件皮革摩擦',
 'metalPot':'金属锅碰撞', 'slime':'黏液声', 'footstep_carpet':'地毯脚步',
 'footstep_concrete':'水泥地脚步', 'footstep_snow':'雪地脚步', 'footstep_wood':'木地板脚步',
 'footstep_grass':'草地脚步', 'footstep':'脚步', 'impactGlass':'玻璃碰撞',
 'laserLarge':'大型激光', 'laserRetro':'复古激光', 'laserSmall':'小型激光',
 'metalClick':'金属卡嗒', 'metalLatch':'金属锁扣', 'impactMetal':'金属碰撞',
 'impactPlate':'板材碰撞', 'impactTin':'锡罐碰撞', 'monster':'怪物声音_种类未标明',
 'bookClose':'合书', 'bookFlip':'翻书', 'bookOpen':'打开书', 'bookPlace':'放下书',
 'impactPunch':'拳击碰撞', 'knifeSlice':'挥刀', 'impactPlank':'木板撞击', 'impactWood':'木材撞击',
}


def display_name(item):
    if item.get('display_name'):
        return item['display_name']
    name = item.get('original_name', item['name'])
    if item['category'] == 'announcer_en':
        if name.isdigit():
            label = '数字' + name
        elif re.fullmatch(r'(player|round)_\d+', name):
            kind, number = name.split('_')
            label = ('玩家' if kind == 'player' else '回合') + number
        else:
            label = ANNOUNCER.get(name, name)
        return '英文播报_' + label
    if name == 'Birds and Wind - Ambient_1':
        return '树林环境_鸟鸣与风声_01'
    ghost = re.fullmatch(r'qubodup-GhostMoan(\d+)', name)
    if ghost:
        return '幽灵低吟_' + ghost[1]
    number = re.search(r'[_-]?(\d+)$', name)
    stem = name[:number.start()] if number else name
    intensity = ''
    for source, target in [('_heavy', '重度'), ('_medium', '中度'), ('_light', '轻度')]:
        if stem.endswith(source):
            stem, intensity = stem[:-len(source)], '_' + target
            break
    if stem not in WORDS:
        raise ValueError('尚未确认这个音效的中文含义：' + name)
    suffix = '_' + str(int(number[1]) + (1 if name.endswith('_' + number[1]) and number[1].startswith('0') else 0)).zfill(2) if number else ''
    return WORDS[stem] + intensity + suffix

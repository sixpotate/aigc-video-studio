"""Conservative input checks, with explicit draft fixes and no silent rewrites.

These rules detect known contradictions, not arbitrary semantic correctness.
"""
import re
from portrait_spec import feature_text

SPEECH = re.compile(r'语速|尾音|反问句|短句|不废话|脏字|说话|口头禅|语气|speech pace|speaks? slowly|tone of voice', re.I)
VISUAL = re.compile(r'裙|衣|衫|裤|鞋|靴|包|项链|耳环|手链|皮带|手套|眼镜|帽|头发|发色|微笑|眉|嘴|dress|skirt|shirt|jacket|coat|shoe|bag|necklace|glasses', re.I)


def outfit_parts(text):
    """Only separate clearly nonvisual whole clauses; preserve mixed clauses."""
    visual, notes = [], []
    for part in re.split(r'[。！？；;\n\r]+|(?<=[a-zA-Z])\.(?=\s|$)', text):
        part = part.strip(' ,，。;；\n\r')
        if not part:
            continue
        (notes if SPEECH.search(part) and not VISUAL.search(part) else visual).append(part)
    return visual, notes


def input_issues(role):
    issues = []
    description, outfit = role.get('description', ''), role.get('outfit', '')
    look = role.get('look', {})
    visual, notes = outfit_parts(outfit)
    if notes:
        issues.append(dict(code='speech_in_outfit', severity='error', fields=['outfit', 'personality'],
            message='服装栏混入了说话风格（如“语速”“反问句”），会干扰绘图。请移到性格与说话风格。',
            fixes=[dict(kind='move_speech', label='将说话风格移到创作备注', outfit='；'.join(visual), moved_text='\n'.join(notes))]))
    prose = description + '；' + '；'.join(visual)
    # A dress plus a jacket can be deliberate layering. Do not reject an
    # explicitly described outer layer or pick one source on the user's behalf.
    dress = re.search(r'吊带(?:连衣)?短裙|吊带(?:连衣)?裙|连衣裙|\b(?:camisole |strap |slip )?dress\b', prose, re.I)
    layering = re.search(r'外搭|内搭|搭配|叠穿|罩着|披着|加穿|外套|皮衣|夹克|jacket|coat|layer|over|under', prose, re.I)
    top = feature_text(look, 'top')
    if dress and not layering and re.search(r'皮衣|夹克|衬衫|衬衣|西装|上衣|jacket|shirt|blouse|camisole top', top, re.I):
        issues.append(dict(code='dress_top_conflict', severity='error', fields=['description', 'outfit', 'top'],
            message=f'文字描述是连衣裙，但上装仍填写“{top}”。若只穿连衣裙请清空上装；若确实叠穿，请在服装栏写明外搭关系。',
            fixes=[dict(kind='clear_look', key='top', label='清空上装，保留文字中的连衣裙')]))
    bottom = feature_text(look, 'bottom')
    if dress and bottom and re.search(r'短裙|长裤|西裤|牛仔裤|skirt|trousers|pants|jeans', bottom, re.I):
        if not re.search(r'叠穿|搭配.*(?:裤|裙)|裙外|裙下|over.*(?:pants|skirt)|layer', prose, re.I):
            issues.append(dict(code='dress_bottom_overlap', severity='warning', fields=['description', 'outfit', 'bottom'],
                message=f'文字已指定连衣裙，下装又填写“{bottom}”，可能画成两件套。若不需要叠穿，可清空下装。',
                fixes=[dict(kind='clear_look', key='bottom', label='清空单独下装，保留连衣裙')]))
    pose = feature_text(look, 'pose')
    if re.search(r'盘腿|盤腿|cross.legged', pose, re.I):
        issues.append(dict(code='pose_text_only', severity='warning', fields=['pose'],
            message='全身、全新绘制时，可勾选“姿势参考”使用正面盘腿骨架。骨架只约束关节，鞋子与衣物细节仍需检查。'))
    if re.search(r'站立|standing', pose, re.I) and re.search(r'盘腿|坐着|坐在|蹲|cross.legged|sitting|seated|crouch', prose, re.I):
        issues.append(dict(code='pose_conflict', severity='error', fields=['pose', 'description', 'outfit'],
            message='姿势栏写了站立，文字描述却要求坐姿或蹲姿，请统一后再生成。',
            fixes=[dict(kind='clear_look', key='pose', label='清空站姿，保留文字中的姿势')]))
    return issues

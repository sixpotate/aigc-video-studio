"""Compile separate visual requirements into weighted, phrase-bound prompts."""
import re
from portrait_spec import FRAMINGS, FEATURES, feature_text

PRIORITIES = {'outfit':'服装与配饰','hair':'头发','shoes':'鞋子','pose':'姿势','face':'面部'}
DEFAULT_PRIORITIES = ['outfit','hair','pose']


def compile_prompt(role, translation, style):
    look=translation['look']
    priorities=role.get('priorities',DEFAULT_PRIORITIES)
    parts=[]
    exclusions=[]
    def add(text,group,weight=1.0,region=None):
        def exclusion(match):
            exclusions.append(match.group(1));return ''
        text=re.sub(r'\b(?:no|without)(?: (?:a|any))? (hats?|glasses|beard|mustache|earrings?)\b',exclusion,text,flags=re.I)
        if re.search(r'no objects in (?:the )?hands|empty hands',text,re.I):
            exclusions.append('holding objects')
        text=re.sub(r'\s+',' ',text).strip(' .,;')
        if text:
            parts.append(dict(text=text,group=group,region=region or (group if group in ('hair','face','shoes','background') else 'global'),weight=round(weight+(.15 if group in priorities else 0),2)))
    person=FEATURES['gender'][1].get(role.get('look',{}).get('gender'),('','person'))[1]
    age=role.get('look',{}).get('age')
    person=(f'{age}-year-old ' if age else '')+person
    heritage=look.get('heritage','')
    add(f'solo, one {person}'+(f', {heritage}' if heritage else ''),'identity',1.05)
    add(FRAMINGS[role.get('framing','half')][1],'framing',1.15)
    # Put garments before decoration and style so primary requirements reach
    # the first CLIP block. Keep color attached to its garment in one segment.
    used_records=set()
    for index,record in enumerate(translation['records']):
        if record['field'] not in ('description','outfit'):continue
        source,text=record['source'],record['english']
        # Only narrowly recognized independent units are promoted. Composite
        # descriptions stay intact instead of losing unknown relations.
        if re.search(r'裙|衬衫|皮衣|夹克|风衣',source) and not re.search(r'鞋|手拿|指甲|发色|头发|眼睛|五官|肤|脸|亚洲|岁',source):
            if re.search(r'丝绒|天鹅绒',source) and re.search(r'\bvelvet\b',text,re.I):
                text+='; soft short-pile velvet fabric texture'
            add('wearing '+text,'outfit',1.08,'garment');used_records.add(index)
        elif re.match(r'脚踩|脚穿|脚上穿',source) and '鞋' in source:
            # A fully contained duplicate is recorded in the audit but need
            # not occupy another text-encoder block.
            duplicate_source=re.sub(r'^(?:脚踩|脚穿|脚上穿)','',source).strip()==feature_text(role.get('look',{}),'shoes')
            if not duplicate_source and not (look.get('shoes') and look['shoes'].lower() in text.lower()):add(text,'shoes',1.12,'shoes')
            used_records.add(index)
        elif re.match(r'手拿|手持|手提',source):
            # Accessories follow the body requirements below.
            continue
    for key in ('top','bottom'):
        if look.get(key):add('wearing '+look[key],'outfit',1.08,'garment' if re.search(r'swimsuit|dress|coat|robe',look[key],re.I) else key)
    for index,record in enumerate(translation['records']):
        if record['field']=='outfit' and index not in used_records and not re.match(r'手拿|手持|手提',record['source']):
            add('wearing '+record['english'],'outfit',1.08,'accessory' if re.search(r'wrist|bracelet',record['english'],re.I) else 'garment');used_records.add(index)
    add(look.get('shoes',''),'shoes',1.12)
    add(look.get('pose',''),'pose',1.10)
    # No mandatory default pose when user supplied a different pose.
    hair='; '.join(look[k] for k in ('hair_length','hair_style','hair_color') if look.get(k))
    add(hair,'hair',1.03)
    for key in ('eyes','expression','facial_hair'):add(look.get(key,''),'face')
    add(look.get('build',''),'body')
    for index,record in enumerate(translation['records']):
        if index in used_records:continue
        if record['field'] in ('description','outfit') and re.match(r'手拿|手持|手提',record['source']):
            add(record['english'],'outfit',1.0,'accessory')
        elif record['field']=='description':add(record['english'],'description')
    add(style,'style',.95)
    background=look.get('background','')
    if not background and not re.search(r'背景|background',role.get('description','')+role.get('outfit',''),re.I):
        background='plain light gray background'
    add(background,'background')
    negative=['blurry','deformed','low quality','duplicate person','two people','multiple heads',
              'multiple faces','collage','character sheet','split screen','text','watermark','logo']
    negative.extend(exclusions)
    if role.get('framing')=='full':
        negative.extend(['cropped feet','cropped head','out of frame','close-up','bust portrait'])
    if role.get('style') in ('anime','guoman'):
        negative.extend(['photograph','photorealistic','live action'])
    positive=' . '.join(part['text'] for part in parts)
    if re.search(r'one[ -]piece.*swimsuit',positive,re.I):
        negative.extend(['bikini','two-piece swimsuit','bare midriff'])
    if 'flat sandals' in positive.lower():negative.extend(['high heels','stiletto heels'])
    if re.search(r'bald(?: head)?',hair,re.I):negative.extend(['long hair','bangs','ponytail','wig'])
    elif re.search(r'short hair|buzz cut|crew cut',hair,re.I):negative.extend(['waist-length hair','long hair'])
    if re.search(r'arms (?:resting )?at (?:the )?sides',positive,re.I):
        negative.extend(['raised arms','arms overhead','hand on hip','hands on hips'])
    if re.search(r'clean-shaven|without (?:a )?beard',positive,re.I):negative.extend(['beard','mustache'])
    if re.search(r'cross.legged',look.get('pose',''),re.I):
        negative.extend(['standing upright','legs stretched straight'])
    if re.search(r'\bvelvet\b',positive,re.I) and not re.search(r'\b(?:leather|latex|vinyl) (?:dress|skirt)\b',positive,re.I):
        negative.extend(['latex dress','vinyl dress','patent leather dress'])
    warnings=[]
    if translation.get('excluded_records'):
        warnings.append('服装栏中的纯说话风格已排除绘图，原文仍保留在记录中，请移到创作备注。')
    source=' '.join(record['source'] for record in translation['records'])
    if re.search(r'左|右|各.*一条|left|right|each side',source,re.I):
        warnings.append('左右位置、条纹数量等小细节仍可能画错，请对照原文检查。')
    if any(record.get('repairs') for record in translation['records']):
        warnings.append('已补正部分视觉术语；请在原文对照中检查完整意思。')
    return dict(prompt='. '.join(part['text'] for part in parts),negative_prompt=', '.join(dict.fromkeys(negative)),
                segments=parts,warnings=warnings,priorities=priorities,version='weighted-clauses-v3.2')


def legacy_prompt(role,description,outfit,style):
    """Small compatibility entry point for callers using pretranslated fields."""
    look={key:feature_text(role.get('look',{}),key,'en') for key in FEATURES}
    translation=dict(look=look,records=[dict(field='description',source=role.get('description',''),english=description),
                                      dict(field='outfit',source=role.get('outfit',''),english=outfit)])
    plan=compile_prompt(role,translation,style)
    return plan['prompt'],plan['negative_prompt']

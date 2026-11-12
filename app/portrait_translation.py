"""Traceable local translation: complete clauses, explicit visual terminology.

The former word-splicing translator destroyed relations between attributes.
Never cut at a glossary hit: translate a whole clause or compile an entire
recognized phrase. Keep the source and result for every clause in the image log.
"""
import re
from portrait_spec import FEATURES, GLOSSARY, feature_text

VERSION = 'clauses-v3.2-material-pose'
CJK = re.compile(r'[\u3400-\u9fff]')
COLORS = {
    '深蓝色':'navy blue', '藏蓝色':'navy blue', '海军蓝':'navy blue',
    '浅蓝色':'light blue', '天蓝色':'sky blue', '酒红色':'burgundy red', '深红色':'dark red',
    '银白色':'silver white', '浅灰色':'light gray', '深灰色':'dark gray',
    '红棕色':'reddish brown', '深棕色':'dark brown', '浅棕色':'light brown',
    '白色':'white', '黑色':'black', '蓝色':'blue', '红色':'red',
    '棕色':'brown', '灰色':'gray', '绿色':'green', '金色':'gold',
    '银色':'silver', '粉色':'pink', '紫色':'purple', '黄色':'yellow',
}
NOUNS = {
    '连体运动泳衣':'one-piece athletic swimsuit', '连体泳衣':'one-piece swimsuit',
    '平底凉鞋':'flat sandals', '平底鞋':'flat shoes', '运动鞋':'sneakers',
    '高跟鞋':'high heels', '皮鞋':'leather shoes', '短靴':'ankle boots', '长靴':'knee-high boots',
    '一字带高跟凉鞋':'open-toe high-heeled sandals with a single straight toe strap and a single ankle strap',
    '一字带高跟鞋':'open-toe high-heeled sandals with a single straight toe strap and a single ankle strap',
    '运动手环':'sports wristband', '手环':'wristband', '手链':'bracelet',
    '竖条纹':'vertical stripes', '横条纹':'horizontal stripes',
    '圆领卫衣':'crew-neck sweatshirt', '连帽卫衣':'hooded sweatshirt',
    '西装外套':'suit jacket', '皮夹克':'leather jacket', '短皮衣':'cropped leather jacket',
    '吊带连衣短裙':'short camisole dress', '吊带短裙':'short camisole dress', '吊带连衣裙':'camisole dress',
    '衬衫':'shirt', '衬衣':'shirt', '长裤':'trousers', '西裤':'suit trousers',
    '牛仔裤':'jeans', '连衣裙':'dress', '短裙':'short skirt', '夹克':'jacket',
    '中式斜襟长衫':'Chinese diagonal-front long robe', '斜襟长衫':'diagonal-front long robe',
    '汉服':'Hanfu clothing', '旗袍':'qipao dress', '中山装':'Chinese tunic suit',
    '寸头':'buzz cut', '平头':'crew cut', '短发':'short hair', '长发':'long hair',
}
EXACT = {
    **GLOSSARY,
    **{label:english for key,(_,options) in FEATURES.items() if key not in ('hair_color','eyes') for label,english in options.values()},
    '及腰长发':'waist-length hair', '齐腰长发':'waist-length hair',
    '无胡须':'clean-shaven', '没有胡须':'clean-shaven',
    '双臂自然下垂':'both arms resting at the sides',
    '双臂放在身体两侧':'both arms resting at the sides',
    '双脚完整入镜':'both feet fully visible in frame',
    '正面自然站立':'front view, standing naturally',
    '浅灰色纯色背景':'plain light gray background',
    '一字带高跟鞋':NOUNS['一字带高跟鞋'],
    '透明一字带高跟鞋':'open-toe high-heeled sandals with clear transparent PVC straps, a single straight toe strap and a single ankle strap',
    '透明一字带高跟凉鞋':'open-toe high-heeled sandals with clear transparent PVC straps, a single straight toe strap and a single ankle strap',
    '盘腿而坐':'sitting cross-legged, both knees bent outward, ankles crossed in front',
    '盘腿坐在地上':'sitting cross-legged on the floor, both knees bent outward, ankles crossed in front',
}
MATERIALS = {'丝绒':'velvet', '天鹅绒':'velvet', '缎面':'satin', '丝缎':'satin', '真丝':'silk', '皮革':'leather'}


def clauses(text):
    # Keep comma-linked attributes together. Only sentence boundaries split text.
    return [part.strip(' ,，。.；;\n\r') for part in re.split(r'[。！？；;\n\r]+|(?<=[a-zA-Z])\.(?=\s|$)', text)
            if part.strip(' ,，。.；;\n\r')]


def visual_clauses(text):
    """Split only explicit new subjects, keeping attributes with their object.

    For example, a dress and its hem remain together, but a hand-held glossy
    bag is separate so its material need not be applied to the dress.
    """
    result=[]
    for sentence in clauses(text):
        result.extend(part.strip() for part in re.split(r'[，,]\s*(?=脚踩|脚穿|脚上穿|手拿|手持|手提|指甲|头戴|耳戴)',sentence) if part.strip())
    return result


def complete_phrase(source):
    """Compile only fully recognized phrases; never drop an unknown remainder."""
    if source in EXACT:
        return EXACT[source]
    text = re.sub(r'^(?:穿着|身穿|穿|一件|一双)', '', source).strip()
    color = next((c for c in sorted(COLORS,key=len,reverse=True) if text.startswith(c)), '')
    noun = text[len(color):]
    material = next((m for m in sorted(MATERIALS,key=len,reverse=True) if noun.startswith(m)), '')
    noun = noun[len(material):]
    if noun in NOUNS:
        english_color='blonde' if color=='金色' and noun in ('寸头','平头','短发','长发') else COLORS.get(color,'')
        return ' '.join(filter(None,(english_color,MATERIALS.get(material,''),NOUNS[noun])))
    return None


def anchors(source):
    """Semantic units that must survive MT, including their local color/side.

    These checks cover vocabulary we can verify, not arbitrary visual semantics.
    Full source clauses are retained even when no rule recognizes a word.
    """
    found=[]
    color_pattern='|'.join(map(re.escape, sorted(COLORS,key=len,reverse=True)))
    nouns_pattern='|'.join(map(re.escape, sorted(NOUNS,key=len,reverse=True)))
    pattern=re.compile(r'(?P<color>'+color_pattern+r')?(?P<noun>'+nouns_pattern+r')')
    for match in pattern.finditer(source):
        color,noun=match.group('color'),match.group('noun')
        before=source[max(0,match.start()-12):match.start()]
        # A negative instruction belongs in the negative prompt, not as a
        # positive garment requirement.
        if re.search(r'(?:不要|不穿|没有|无)[^，,。；;]{0,6}$',before):
            continue
        phrase=' '.join(filter(None,(COLORS.get(color,''),NOUNS[noun])))
        if noun in ('运动手环','手环','手链'):
            side = 'left' if re.search(r'左(?:手)?腕',before) else 'right' if re.search(r'右(?:手)?腕',before) else ''
            if side: phrase+=f' on the {side} wrist'
        if noun in ('竖条纹','横条纹') and re.search(r'两侧各.*一条|两边各.*一条',source):
            phrase='one '+phrase.removesuffix('s')+' on each side'
        found.append(dict(source=match.group(), phrase=phrase))
    return found


def repair_footwear_terms(source, translation):
    """Repair observed shoe vocabulary errors without dropping any clauses.

    A one-piece garment remains a one-piece garment: only change that wording
    immediately before a shoe noun, and only when the source specifies straps.
    """
    if not re.search(r'鞋|凉鞋',source):return translation,[]
    result=translation
    repairs=[]
    replacements=[]
    if '露趾' in source:
        replacements.append(('露趾',r'\bbare[- ]toe(?:d)?\b','open-toe'))
    if '前掌' in source:
        replacements.append(('前掌',r'\b(?:front|fore)\s+palm\b','forefoot'))
    if '一字带' in source:
        replacements.append(('一字带',r'\bone[- ]piece(?=\s+(?:high[- ]heel(?:ed)?\s+)?sandals?\b)','single-strap'))
    for term,pattern,correct in replacements:
        changed=re.sub(pattern,correct,result,flags=re.I)
        if changed!=result:
            repairs.append(dict(source=term,phrase=correct,kind='footwear_correction'))
            result=changed
    return result,repairs


def repair_terminology(source, translation):
    """Correct known mistranslations without splicing the Chinese sentence."""
    result=re.sub(r'\bwindcoats?\b','trench coat',translation,flags=re.I)
    if '斜襟' in source:result=re.sub(r'obi[ -]style','Chinese diagonal-front',result,flags=re.I)
    result,repairs=repair_footwear_terms(source,result)
    # An observed material substitution changed velvet into glossy silk/satin.
    # Repair only the dress phrase when no silk/satin fabric is requested.
    if re.search(r'丝绒|天鹅绒',source) and not re.search(r'真丝|丝缎|缎面',source):
        changed=re.sub(r'\b(?:silk\s+satin|satin|silk)(?=\s+(?:(?:strap|strappy|camisole|short|slip)\s+){0,3}(?:dress|skirt)\b)', 'velvet',result,flags=re.I)
        if changed!=result:
            repairs.append(dict(source='丝绒',phrase='velvet',kind='material_correction'));result=changed
    # Preserve a recognized shoe phrase as one unit, rather than retaining a
    # mistranslated "single-belt" phrase alongside another full shoe sentence.
    if '透明一字带高跟鞋' in source or '透明一字带高跟凉鞋' in source:
        corrected=EXACT['透明一字带高跟鞋']
        changed=re.sub(r'\b(?:transparent|clear)\s+(?:(?:single[- ]belt|single[- ]buckle|single[- ]strap|one[- ]piece)\s+)?(?:high[- ]heel(?:ed)?\s+(?:shoes?|sandals?)|high[- ]heels?)\b',corrected,result,flags=re.I)
        if changed!=result:
            repairs.append(dict(source='透明一字带高跟鞋',phrase=corrected,kind='footwear_correction'));result=changed
    for anchor in anchors(source):
        phrase=anchor['phrase']
        normalized=lambda s:re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()
        expected=normalized(phrase)
        actual=normalized(result)
        # All semantic words must be present; synonyms are normalized here.
        actual=actual.replace('dark blue','navy blue').replace('swimming suit','swimsuit')
        if 'single straight toe strap' in phrase:
            # These expressions carry the same footwear geometry. Avoid
            # appending an entire second shoe description solely for wording.
            actual=re.sub(r'horizontal (?:thin )?strap on (?:the )?forefoot','straight toe strap',actual)
        if all(word in actual.split() for word in expected.split()) or (phrase=='short camisole dress' and re.search(r'(?:short|mid thigh).*dress|(?:strap|camisole|slip) dress',actual)):
            continue
        repairs.append(anchor)
        # Replace a wrong garment term when identifiable. Otherwise add the
        # complete source-linked unit, never an unattached color token.
        if phrase=='short camisole dress' and re.search(r'\b(?:strap|camisole|slip) (?:dress|skirt)\b',result,re.I):
            result=re.sub(r'\b(?:strap|camisole|slip) (?:dress|skirt)\b',phrase,result,count=1,flags=re.I)
            continue
        if 'one-piece' in phrase:
            garment=r'(?:(?:a |an )?(?:deep |dark |navy |blue |athletic |sports? |one[- ]piece )*)?(?:swimming suits?|swimsuits?|bathing suits?)'
            if re.search(garment,result,re.I):
                result=re.sub(garment,phrase,result,count=1,flags=re.I)
                continue
        if 'flat sandals' in phrase and re.search(r'(?:white |flat |floor |on the floor )*sandals?',result,re.I):
            result=re.sub(r'(?:white |flat |floor |on the floor )*sandals?',phrase,result,count=1,flags=re.I)
            continue
        result=result.rstrip(' .')+'; '+phrase
    return result, repairs


def translate_role(role, translator):
    from portrait_validation import outfit_parts
    records=[]
    excluded=[]
    for key in ('description','outfit'):
        texts=visual_clauses(role.get(key,''))
        if key=='outfit':
            visual,notes=outfit_parts(role.get(key,''))
            texts=[unit for text in visual for unit in visual_clauses(text)]
            excluded.extend(dict(field=key,source=text,reason='说话风格不是可绘制的服装要求') for text in notes)
        for text in texts:
            records.append(dict(field=key,source=text))
    look=role.get('look',{})
    for key in FEATURES:
        if key!='gender' and look.get(key):
            value=feature_text(look,key)
            known=FEATURES[key][1].get(look[key])
            if key=='facial_hair' and value in ('无','没有','none','None'):
                records.append(dict(field=key,source=value,english='clean-shaven',method='term',repairs=[]))
            elif known:
                records.append(dict(field=key,source=value,english=known[1],method='term',repairs=[]))
            elif key in ('hair_color','eyes') and value in COLORS:
                color='blonde' if key=='hair_color' and value=='金色' else COLORS[value]
                records.append(dict(field=key,source=value,english=color+(' hair' if key=='hair_color' else ' eyes'),method='term',repairs=[]))
            else:
                for text in clauses(value):records.append(dict(field=key,source=text))
    pending=[]
    for record in records:
        if 'english' in record:continue
        source=record['source']
        direct=complete_phrase(source)
        if direct is not None:
            record.update(english=direct,method='term',repairs=[])
        elif not CJK.search(source):
            record.update(english=source,method='original',repairs=[])
        else:
            pending.append(record)
    if pending:
        results=translator([record['source'] for record in pending])
        if len(results)!=len(pending):
            raise ValueError('翻译结果不完整，已停止绘制，请重试。')
        for record, translated in zip(pending,results):
            if not isinstance(translated,str) or not translated.strip() or CJK.search(translated):
                raise ValueError('有描述未能完成翻译，已停止绘制。请简化该句后重试：'+record['source'])
            translated, repairs=repair_terminology(record['source'],translated)
            record.update(english=translated.strip(' .'),method='local_mt',repairs=repairs)
    def joined(field):
        return '. '.join(r['english'] for r in records if r['field']==field)
    translated_look={key:joined(key) for key in FEATURES if joined(key)}
    translated_look.update({key:look[key] for key in ('gender','age') if look.get(key)})
    return dict(description=joined('description'),outfit=joined('outfit'),look=translated_look,
                records=records,excluded_records=excluded,translator='Qwen3-4B + visual terms',version=VERSION)

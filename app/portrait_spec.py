"""Portrait settings, conflict checks and deterministic prompt vocabulary."""
import math
import re

FRAMINGS = {
    'head': ('头像', 'close-up head and shoulders portrait'),
    'half': ('半身', 'waist-up portrait'),
    'full': ('全身', 'full body, entire figure in frame, head and both feet visible, space around the figure'),
}
FEATURES = {
    'gender': ('人物', {'female': ('女性', 'woman'), 'male': ('男性', 'man'), 'generic': ('通用 / 自定义', 'person')}),
    'heritage': ('外貌风格', {'asian': ('亚洲面孔', 'Asian'), 'east_asian': ('东亚面孔', 'East Asian')}),
    'hair_color': ('发色', {
        'red': ('红色', 'red hair'), 'wine_red': ('酒红色', 'burgundy red hair'),
        'black': ('黑色', 'black hair'), 'brown': ('棕色', 'brown hair'),
        'blonde': ('金色', 'blonde hair'), 'silver': ('银色', 'silver hair'),
        'white': ('白色', 'white hair'), 'blue': ('蓝色', 'blue hair'),
        'pink': ('粉色', 'pink hair'), 'purple': ('紫色', 'purple hair')}),
    'hair_length': ('头发长度', {'short': ('短发', 'short hair'), 'shoulder': ('齐肩', 'shoulder-length hair'),
        'long': ('长发', 'long hair'), 'waist': ('及腰', 'waist-length hair'), 'bald': ('光头', 'bald head')}),
    'hair_style': ('发型', {'straight': ('直发', 'straight hair'), 'wavy': ('微卷', 'wavy hair'),
        'curly': ('卷发', 'curly hair'), 'ponytail': ('马尾', 'ponytail hairstyle'), 'bob': ('波波头', 'bob haircut'),
        'buzz': ('寸头', 'buzz cut'), 'crew': ('平头', 'crew cut'), 'slick': ('背头', 'slicked-back hair')}),
    'eyes': ('眼睛颜色', {'brown': ('深棕色', 'dark brown eyes'), 'amber': ('琥珀色', 'amber eyes'),
        'black': ('黑色', 'dark eyes'), 'blue': ('蓝色', 'blue eyes'), 'green': ('绿色', 'green eyes')}),
    'expression': ('面部表情', {'relaxed': ('自然放松', 'relaxed natural expression'),
        'smile': ('轻微微笑', 'gentle closed-mouth smile'), 'confident': ('自信坚定', 'confident composed expression')}),
    'build': ('体型', {'tall': ('高挑、长腿', 'tall, long legs, balanced body proportions'),
        'slim': ('纤细', 'slim build'), 'athletic': ('健美', 'athletic build'), 'average': ('匀称', 'balanced body proportions')}),
    'top': ('上装', {'leather': ('黑色短皮衣', 'cropped black leather jacket'),
        'camisole': ('红色吊带上衣', 'red camisole top'), 'shirt': ('白衬衫', 'white shirt'),
        'trench': ('深蓝风衣', 'navy blue trench coat')}),
    'bottom': ('下装', {'skirt': ('黑色短裙', 'high-waisted black short skirt'),
        'pants': ('黑色长裤', 'black fitted trousers'), 'jeans': ('蓝色牛仔裤', 'blue jeans'),
        'dress': ('长裙连衣裙', 'long dress')}),
    'shoes': ('鞋子', {'boots': ('黑色长靴', 'black knee-high boots'),
        'heels': ('黑色高跟鞋', 'black high heels'), 'sneakers': ('白色运动鞋', 'white sneakers')}),
    'facial_hair': ('面部毛发', {'clean': ('无胡须', 'clean-shaven'), 'stubble': ('短胡茬', 'short stubble'), 'beard': ('短胡须', 'short beard')}),
    'pose': ('姿势', {'front': ('正面站立，双臂自然下垂', 'front view, standing upright, both arms resting at the sides'),
                    'cross_legged': ('盘腿而坐', 'sitting cross-legged, both knees bent outward, ankles crossed in front')}),
    'background': ('背景', {'gray': ('浅灰色纯色背景', 'plain light gray background'), 'white': ('白色纯色背景', 'plain white background')}),
}

SUGGESTIONS = {
    'female': {'hair_length':['短发','齐肩','及腰'], 'hair_style':['直发','卷发','马尾'],
               'top':['白衬衫','黑色短皮衣','蓝色连衣裙'], 'bottom':['黑色短裙','黑色长裤','蓝色牛仔裤'],
               'shoes':['黑色一字带高跟鞋','白色平底凉鞋','白色运动鞋'], 'facial_hair':['无胡须']},
    'male': {'hair_length':['短发','光头','齐肩'], 'hair_style':['平头','寸头','背头'],
             'top':['白色衬衫','深蓝色西装外套','黑色夹克'], 'bottom':['黑色西裤','蓝色牛仔裤','灰色运动裤'],
             'shoes':['黑色皮鞋','白色运动鞋','棕色短靴'], 'facial_hair':['无胡须','短胡茬','短胡须']},
    'generic': {'hair_length':['短发','及腰','光头'], 'hair_style':['直发','平头','马尾'],
                'top':['白衬衫','黑色夹克','蓝色连衣裙'], 'bottom':['黑色长裤','黑色短裙'],
                'shoes':['白色运动鞋','白色平底凉鞋']},
}


def feature_text(look, key, language='zh'):
    value = look.get(key, '')
    if not value:
        return ''
    choice = FEATURES[key][1].get(value)
    return choice[0 if language=='zh' else 1] if choice else value

# Exact visual phrases retained for compatibility. Never split a source
# sentence at glossary matches: preserve complete clauses and their relations.
GLOSSARY = {
    '内搭深红色吊带上衣': 'a dark red camisole underneath the jacket',
    '内搭红色吊带上衣': 'a red camisole underneath the jacket',
    '神情自信': 'confident expression', '温柔微笑': 'gentle smile',
    '黑皮红底一字带高跟鞋': 'black ankle-strap high heels with red soles',
    '五官立体精致': 'well-defined delicate facial features',
    '五官精致': 'delicate facial features', '精致五官': 'delicate facial features', '五官立体': 'well-defined facial features',
    '五官': 'facial features', '吊带上衣': 'camisole top', '吊带衫': 'camisole top',
    '酒红色': 'burgundy red', '冷白皮': 'fair skin with cool undertones',
    '一字带高跟鞋': 'ankle-strap high heels', '修身短款皮衣': 'fitted cropped leather jacket',
    '紧身长裤': 'fitted trousers', '高腰黑色短裙': 'high-waisted black short skirt',
    '长卷发': 'long curly hair', '齐肩短发': 'shoulder-length hair',
    '垂至腰间': 'reaching the waist', '琥珀色眼睛': 'amber eyes',
    '腿部修长匀称': 'long well-proportioned legs', '身材高挑': 'tall stature',
    '银色耳环': 'silver earrings', '细项链': 'delicate necklace',
    '红棕色口红': 'reddish brown lipstick', '风衣': 'trench coat',
}


def public_options():
    from portrait_prompt import PRIORITIES, DEFAULT_PRIORITIES
    return dict(framings=[dict(value=k, label=v[0]) for k, v in FRAMINGS.items()],
        suggestions=SUGGESTIONS,
        priorities=[dict(value=k,label=v) for k,v in PRIORITIES.items()], default_priorities=DEFAULT_PRIORITIES,
        features=[dict(key=k, label=label, options=[dict(value=v, label=t[0]) for v, t in options.items()])
                  for k, (label, options) in FEATURES.items()])


def normalize_look(raw):
    if not isinstance(raw, dict):
        raise ValueError('明确特征的格式不正确。')
    result = {}
    for key, (label, options) in FEATURES.items():
        value = raw.get(key, '')
        if not isinstance(value, str) or len(value.strip())>80:
            raise ValueError(f'{label}请填写不超过80字的文字。')
        value=value.strip()
        if key=='gender' and value and value not in options:
            raise ValueError('请选择女性、男性或通用人物。')
        value=next((k for k,v in options.items() if value==v[0]),value)
        if value:
            result[key] = value
    age = raw.get('age', '')
    if age not in ('', None):
        if isinstance(age, bool) or not str(age).isdigit() or not 1 <= int(age) <= 120:
            raise ValueError('年龄请输入1至120之间的整数。')
        result['age'] = int(age)
    return result


def inspect_role(role):
    description = role.get('description', '')
    outfit = role.get('outfit', '')
    look = role.get('look', {})
    issues = []
    def add(message, severity='error'):
        issues.append(dict(severity=severity, message=message))
    if re.search(r'短发|短髮|short hair', description, re.I) and re.search(r'及腰|腰间|腰間|waist.length', description, re.I):
        add('“短发”和“及腰”互相冲突，请保留其中一种。')
    if re.search(r'短裙\s*或|或\s*紧身长裤|skirt\s+or', outfit, re.I):
        add('服装中有“短裙或长裤”，建议选定一种，避免每次变化。', 'warning')
    if look.get('hair_length') in ('long', 'waist') and re.search(r'短发|短髮|short hair', description, re.I):
        add('已选长发，但补充描述中还有短发，请统一设定。')
    if look.get('hair_length') == 'short' and re.search(r'长发|长卷发|及腰|腰间|long hair', description, re.I):
        add('已选短发，但补充描述中还有长发，请统一设定。')
    if look.get('hair_style') == 'bob' and look.get('hair_length') in ('long', 'waist'):
        add('波波头与长发／及腰长度冲突，请调整其中一项。')
    if look.get('hair_length')=='bald' and look.get('hair_style') and feature_text(look,'hair_style') not in ('光头','bald','bald head'):
        add('已选择光头，请清空发型，或也填写光头。')
    if look.get('hair_length')=='bald' and look.get('hair_color'):
        add('光头与发色同时存在，请清空发色，避免模型又画出头发。')
    build=feature_text(look,'build')
    if re.search(r'高挑|高大|tall',build,re.I) and re.search(r'娇小|矮小|petite|short stature',description,re.I):
        add('体型填写了“高挑”，外貌补充又写了“娇小”；请统一，避免两种要求互相影响。','warning')
    frame = role.get('framing', 'half')
    if frame != 'full' and re.search(r'长腿|腿部|鞋|全身|head.to.toe|full.body', description + outfit, re.I):
        add('当前不是全身构图，腿和鞋可能不会出现；需要展示时请选“全身”。', 'warning')
    if frame == 'full' and re.search(r'半身|头像|特写|upper body|close.up portrait', description, re.I):
        add('已选全身，但描述中指定了半身或特写，请删掉冲突的构图要求。')
    if frame != 'full' and re.search(r'全身|full.body|head.to.toe', description, re.I):
        add('描述要求全身，请把构图也设为“全身”。')
    from portrait_validation import input_issues
    return issues + input_issues(role)


def translate_visual_fields(role, translator):
    from portrait_translation import translate_role
    result=translate_role(role,translator)
    return result['description'],result['outfit']


def build_prompt(role, description, outfit, style_prompt):
    from portrait_prompt import legacy_prompt
    return legacy_prompt(role,description,outfit,style_prompt)


def normalize_generation(data, role, character_dir, random_seed):
    mode = data.get('mode', 'new')
    if mode not in ('new', 'reference', 'local'):
        raise ValueError('请选择有效的绘制方式。')
    seed = data.get('seed')
    if seed in ('', None):
        seed = random_seed()
    elif isinstance(seed, bool) or not str(seed).isdigit() or not 0 <= int(seed) < 2**31:
        raise ValueError('随机种子须为0至2147483647的整数，留空表示随机。')
    quality=data.get('quality','hd')
    if quality not in ('standard','hd'):
        raise ValueError('请选择标准或高清画质。')
    pose_guide=data.get('pose_guide',True)
    face_refine=data.get('face_refine',True)
    content_check=data.get('content_check',False)
    if type(pose_guide) is not bool or type(face_refine) is not bool or type(content_check) is not bool:
        raise ValueError('姿势参考、面部细化或成人敏感内容检查开关格式不正确。')
    result = dict(mode=mode, seed=int(seed),quality=quality,pose_guide=pose_guide,
                  face_refine=face_refine,content_check=content_check)
    edit=data.get('edit_instruction','')
    if not isinstance(edit,str) or len(edit)>600:raise ValueError('修改要求不超过600字。')
    if edit.strip():result['edit_instruction']=edit.strip()
    if mode == 'new':
        return result
    image = data.get('reference') or role.get('image')
    version = next((v for v in role.get('images', []) if v['image'] == image), None)
    if not version or not re.fullmatch(r'/characters/media/[a-zA-Z0-9_-]{1,48}/[a-f0-9]{32}\.png', str(image)):
        raise ValueError('请先为这个角色选择一张已保存的参考形象。')
    path = (character_dir / image.removeprefix('/characters/media/')).resolve()
    if not path.is_relative_to(character_dir.resolve()) or not path.is_file():
        raise ValueError('参考形象文件不存在。')
    if role.get('framing', 'half') != version.get('framing', 'half'):
        raise ValueError('参考修改会保留原图构图；改变全身／半身时请使用“全新绘制”。')
    try:
        strength = float(data.get('strength', .35 if mode == 'reference' else .65))
    except (TypeError, ValueError):
        raise ValueError('修改幅度格式不正确。')
    if not math.isfinite(strength) or not .1 <= strength <= .85:
        raise ValueError('修改幅度应在10%至85%之间。')
    result.update(reference=str(path), reference_image=image, strength=strength)
    if mode == 'local':
        strokes = data.get('strokes', [])
        if not isinstance(strokes, list) or not 1 <= len(strokes) <= 100:
            raise ValueError('请先在参考图上涂抹需要修改的区域。')
        points_count = 0
        checked = []
        for stroke in strokes:
            if not isinstance(stroke, dict):
                raise ValueError('修改区域格式不正确。')
            size, points = stroke.get('size'), stroke.get('points')
            if type(size) not in (float, int) or not math.isfinite(size) or not .01 <= size <= .3:
                raise ValueError('画笔大小超出范围。')
            if not isinstance(points, list) or not points:
                raise ValueError('修改区域没有有效笔迹。')
            for point in points:
                if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) or not 0 <= v <= 1 for v in point):
                    raise ValueError('修改区域坐标无效。')
            points_count += len(points)
            checked.append(dict(size=size, points=points))
        if points_count > 2000:
            raise ValueError('笔迹过多，请清空后用较大的画笔重新涂抹。')
        result['strokes'] = checked
    return result


def make_mask(size, strokes):
    from PIL import Image, ImageDraw
    width, height = size
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for stroke in strokes:
        diameter = max(1, round(stroke['size'] * width))
        radius = diameter / 2
        points = [(round(x * (width - 1)), round(y * (height - 1))) for x, y in stroke['points']]
        if len(points) > 1:
            draw.line(points, fill=255, width=diameter, joint='curve')
        for x, y in points:
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=255)
    return mask

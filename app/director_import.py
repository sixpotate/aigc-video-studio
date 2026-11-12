"""Import Markdown storyboard tables without sending scripts to a service."""
import re,secrets,uuid
from voice_catalog import role_voice
from director_script import dialogue_chunks

def table_rows(script):
    header=None;result=[]
    for line in script.splitlines():
        if not line.strip().startswith('|'):continue
        cells=[x.strip() for x in re.split(r'(?<!\\)\|',line.strip().strip('|'))]
        if '镜号' in cells and '台词' in cells:header=cells;continue
        if not header or len(cells)!=len(header) or not cells[0].isdigit():continue
        result.append(dict(zip(header,cells)))
    return result

def import_table(data,store):
    script=data['script'];rows=table_rows(script)
    if not rows:raise ValueError('没有找到包含“镜号、画面内容、台词”的分镜表。')
    default=store.get(data['default_role']);roles=store.list();by_name={};aliases={}
    for role in roles:
        by_name.setdefault(role['name'],[]).append(role)
        for label in [role['name'],*re.split(r'[·｜|]',role['name'])]:aliases.setdefault(label,[]).append(role)
    for line in data.get('aliases','').splitlines():
        if not line.strip():continue
        parts=re.split(r'[=＝]',line,maxsplit=1)
        if len(parts)!=2:raise ValueError('角色别名请按“剧本称呼=角色库完整名称”填写，一行一个。')
        label,name=map(str.strip,parts);choices=by_name.get(name,[])
        if len(choices)!=1:raise ValueError(f'别名对应的角色「{name}」不存在或重名。')
        aliases[label]=choices
    def resolve(label):
        choices={r['id']:r for r in aliases.get(label,[])}
        if len(choices)!=1:raise ValueError(f'剧本称呼「{label}」无法唯一匹配。请在角色别名中填写“{label}=角色库完整名称”。')
        role=next(iter(choices.values()))
        if not role.get('image'):raise ValueError(f'请先生成「{role["name"]}」的人物形象。')
        return role
    def mentioned(visual):
        matches=[]
        for label in sorted(aliases,key=len,reverse=True):
            for m in re.finditer(re.escape(label),visual):
                if visual[m.end():].startswith(('办公室','手机','学校')):continue
                role=resolve(label)
                if not any(r['id']==role['id'] for _,r in matches):matches.append((m.start(),role))
        return [r for _,r in sorted(matches,key=lambda x:x[0])][:4]
    shots=[];quotes=0;previous=None
    for row in rows:
        visual=row.get('画面内容','');dialogue=row['台词'];effect=row.get('音效/花字','');visible=mentioned(visual)
        matches=list(re.finditer(r'"([^"]*)"|“([^”]*)”',dialogue));records=[];end=0
        for m in matches:
            prefix=dialogue[end:m.start()].strip();end=m.end();kind='os' if re.search(r'内心|独白|OS',prefix,re.I) else ('narration' if '画外音' in prefix else 'dialogue')
            label=re.sub(r'[（(][^）)]*[）)]','',prefix).strip(' ：:')
            if kind=='os':
                named=re.sub(r'挂电话后|挂断电话后|内心独白|内心OS|内心|独白|OS','',label,flags=re.I).strip(' ：:，')
                actor=resolve(named) if named else (previous if ('挂电话' in prefix and previous) else (visible[0] if len(visible)==1 else None))
            elif label in ('旁白','画外音'):actor=default;kind='narration'
            elif label:actor=resolve(label)
            else:actor=visible[0] if len(visible)==1 else None
            if actor is None:raise ValueError(f'第{row["镜号"]}镜的独白/对白说话人不明确，请在引号前补上角色名：。')
            if '齐声' in label:kind='chorus'
            previous=actor;text=m.group(1) if m.group(1) is not None else m.group(2);quotes+=1
            records.append((actor,label,text,kind))
        if not records:
            if '无台词' not in dialogue and dialogue.strip() not in ('','无','—','（无）'):raise ValueError(f'第{row["镜号"]}镜台词没有配对引号，请用“角色：\"台词\"”格式。')
            records=[(default,'','','narration')]
        first=True;row_sources={}
        for actor,label,text,kind in records:
            cast=visible[:]
            if actor['id'] not in [r['id'] for r in cast]:cast.insert(0,actor)
            if len(cast)>4:raise ValueError('一个镜头最多4名角色。')
            for chunk in dialogue_chunks(text,32):
                token=uuid.uuid4().hex;camera='wide' if '全景' in row.get('景别','') or '远景' in row.get('景别','') else ('extreme_close' if '特写' in row.get('景别','') else 'close')
                fx=next((v for pattern,v in [('拍桌|砰','bang'),('铃','ring'),('叮','ding'),('口哨|哔','whistle'),('纸','paper'),('笑点','boing')] if re.search(pattern,effect)),'none') if first else 'none'
                flower=re.search(r'花字[：:]\s*([^；;]+)',effect)
                emotion=next((v for pattern,v in [('愤|怒|咆哮|喊','angry'),('惊|瞪','surprised'),('笑|得意','happy'),('无奈|失落','sad')] if re.search(pattern,visual)),'calm')
                shots.append(dict(id=token,source_shot=row['镜号'],role_id=actor['id'],role_ids=[r['id'] for r in cast],speaker_id='narrator' if label in ('旁白','画外音') else actor['id'],
                    actor_actions={},text=chunk,action=visual or '自然呼吸，轻微活动。',scene_description=visual,scene_image='',visual_only=not bool(matches),
                    speech_kind=kind,subtitle_name=actor['name'] if kind=='os' else (label or actor['name']),onscreen_text=flower[1].strip() if flower and first else '',
                    effect=fx,effect_time=0,effect_level=-12,camera=camera,voice=role_voice(actor),voice_mode='role',emotion=emotion,
                    emotion_note='心中独白，低声自然，不喊叫。' if kind=='os' else '',duration=None if text else 3.,speed=1.,pause_before=.12,pause_after=.3,
                    seed=secrets.randbelow(2**31),lip_sync=kind=='dialogue',face_box=None,reuse_motion_from='',motion_seconds=3))
                geometry=tuple(r['id'] for r in cast)
                if geometry in row_sources:
                    source=row_sources[geometry];shots[-1]['reuse_motion_from']=source['id'];shots[-1]['seed']=source['seed']
                else:row_sources[geometry]=shots[-1]
                first=False
    from director_schema import MAX_SHOTS
    if len(shots)>MAX_SHOTS:raise ValueError(f'拆分后超过{MAX_SHOTS}镜，请分为多个项目。')
    return dict(shots=shots,count=len(shots),source_shots=len(rows),dialogue_lines=quotes,
                note=f'已导入{len(rows)}个原稿镜头、{quotes}句对白，拆为{len(shots)}个片段。对白完整保留；请检查角色别名、场景图片、动作和音效位置。')

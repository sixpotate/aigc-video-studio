"""Deterministic offline dialogue splitting with explicit speaker validation."""
import re, secrets, uuid
from director_schema import MAX_SHOTS
from voice_catalog import role_voice


def dialogue_chunks(text,limit=20):
    text=text.strip().strip('“”「」"').strip()
    pieces=re.findall(r'[^，。！？；,.!?;]+[，。！？；,.!?;]*|[，。！？；,.!?;]+',text)
    chunks=[];current=''
    for piece in pieces:
        piece=piece.strip()
        while len(piece)>limit:
            if current:chunks.append(current);current=''
            chunks.append(piece[:limit]);piece=piece[limit:]
        if current and len(current)+len(piece)>limit:chunks.append(current);current=''
        current+=piece
    if current:chunks.append(current)
    return chunks or ['']


def split_script(data,store):
    script=data.get('script','')
    if not isinstance(script,str) or not script.strip() or len(script)>60000:raise ValueError('请输入1至60000字的对话剧本。')
    from director_import import table_rows,import_table
    if table_rows(script):return import_table(data,store)
    keep_pair=data.get('keep_pair',True)
    if not isinstance(keep_pair,bool):raise ValueError('同框选项无效。')
    default=store.get(data.get('default_role'))
    if not default.get('image'):raise ValueError('默认出镜角色还没有人物形象。')
    roles=store.list();by_name={}
    for role in roles:by_name.setdefault(role['name'],[]).append(role)
    reserved={'旁白','画面','动作'}
    names=sorted(set(by_name)|reserved,key=len,reverse=True)
    script=re.sub(r'(?m)^\s*(?:\d+[.、]\s*|[-*]\s+)','',script.replace('\r\n','\n').replace('**',''))
    marker=re.compile(r'(?<![\w\u4e00-\u9fff])(?P<name>'+ '|'.join(map(re.escape,names)) +r')\s*(?P<action>[（(][^）)\n]{0,100}[）)])?\s*[：:]')
    # Add line breaks only at recognised speaker labels; retain text for editing.
    script=marker.sub(lambda m:'\n'+m.group(0).strip(),script).strip()
    records=[];last_name=default['name'];last_action=''
    for line in script.splitlines():
        line=line.strip()
        if not line:continue
        match=re.match(r'^([^：:]{1,130})[：:](.*)$',line)
        if match:
            header,body=match.groups();direction=re.fullmatch(r'(.+?)\s*[（(]([^）)]*)[）)]\s*',header)
            name=direction[1].strip() if direction else header.strip()
            action=direction[2].strip() if direction else ''
            if name not in by_name and name not in reserved:raise ValueError(f'剧本角色「{name}」未匹配到角色库。请使用角色的完整名称，或先创建该角色。原剧本尚未导入。')
            last_name,last_action=name,action
        else:
            body=line;name=last_name;action=last_action
            standalone=re.fullmatch(r'[（(【\[](.+)[）)】\]]',line)
            if standalone:
                if len(standalone[1])>220:raise ValueError('一条画面/动作说明超过220字，请分段。')
                records.append(dict(name='画面',text='',action=standalone[1]));continue
        if name in ('画面','动作'):
            if len(body)>220:raise ValueError('一条画面/动作说明超过220字，请分段。')
            records.append(dict(name='画面',text='',action=body or action or '人物自然呼吸，轻微活动。'))
        else:
            for chunk in dialogue_chunks(body):records.append(dict(name=name,text=chunk,action=action))
    if not records or len(records)>MAX_SHOTS:raise ValueError(f'拆分得到{len(records)}个镜头，每个作品最多{MAX_SHOTS}镜。请分成多个作品。')
    def resolve(name):
        if name in reserved:return None
        choices=by_name.get(name,[])
        if len(choices)!=1:raise ValueError(f'角色库有多个「{name}」，请先区分名称，再自动拆镜。')
        if not choices[0].get('image'):raise ValueError(f'请先为「{name}」生成人物形象。')
        return choices[0]
    actors=[resolve(r['name']) for r in records]
    unique=list({r['id']:r for r in actors if r}.values())
    shots=[]
    for index,(record,actor) in enumerate(zip(records,actors)):
        visible=[actor or next((r for r in actors[index:] if r),None) or next((r for r in reversed(actors[:index]) if r),default)]
        if keep_pair:
            partner=next((r for r in actors[index+1:]+list(reversed(actors[:index])) if r and r['id']!=visible[0]['id']),None)
            if partner:visible.append(partner)
            # Stable left/right order across all shots in a two-person exchange.
            visible.sort(key=lambda r:next((i for i,v in enumerate(unique) if v['id']==r['id']),len(unique)))
        speaker='narrator' if record['name']=='旁白' else (actor or visible[0])['id']
        lead=actor or visible[0];action=record['action']
        emotion=next((value for pattern,value in [('怒|吼|质问','angry'),('哭|难过|失落','sad'),('惊|震','surprised'),('笑|开心','happy')] if re.search(pattern,action)),'calm')
        shots.append(dict(id=uuid.uuid4().hex,role_id=lead['id'],role_ids=[r['id'] for r in visible],speaker_id=speaker,
            actor_actions={r['id']:(action or '自然说话，轻微点头。') if actor and r['id']==actor['id'] else '自然聆听，轻轻呼吸，偶尔眨眼。' for r in visible},
            action=action if record['name']=='画面' else '保持角色的左右站位，自然呼吸，轻微活动。',text=record['text'],
            camera='close',duration=3.,voice=role_voice(lead),voice_mode='role',emotion=emotion,emotion_note='',
            speed=1.,pause_before=.12,pause_after=.3,seed=secrets.randbelow(2**31),lip_sync=True,face_box=None))
    return dict(shots=shots,count=len(shots),note='已按说话人标记拆分；长对白按标点拆短。请检查人物动作、站位和情绪后再生成。')

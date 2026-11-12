"""Offline character cutouts and one shared first frame for multi-person I2V."""
import hashlib
import re
from settings import WORKSPACE
from director_schema import cast_members, reference_path, NATIVE_SIZES, export_settings, digest, drawing_options, generated_recipe
from director_production import speaker_mouth_covered

MATTE_MODEL = WORKSPACE/'work/local_test/models/U2Net/u2netp.onnx'
MATTE_MD5 = '8e83ca70e441ab06c318d82300c84806'
_session = None


def identity_description_for_scene(description, scene_description):
    """Remove explicit studio-ground placement, preserving the character and pose.

    Only do this when a shot has its own scene; leave uncertain clauses and the
    saved character description untouched. This is not semantic scene parsing.
    """
    if not scene_description:
        return description or ''
    text = description or ''
    return re.sub(
        r'(站立|站|立|坐|跪|躺)(?:在|于)([^，。；\n]{0,20}(?:大理石|地板|地砖|地面|草地|沙滩|舞台|石阶|台阶)[^，。；\n]{0,10}?)(?:上|中|里)',
        lambda match: match.group(1), text)


def mask_was_discarded(actor_state):
    """Recognize only explicit past removal; an upcoming action is not a past state."""
    state = actor_state or ''
    for clause in re.split(r'[，。；;\n]', state):
        if re.search(r'(?:未|没|不|尚未|从未).{0,8}(?:丢弃|扔掉|摘下|摘掉|脱下|脱掉)', clause):
            continue
        if re.search(r'(?:防毒面具|面具)(?:此前|先前|已经|早已|已|现已){1,3}(?:丢弃|扔掉|摘下|摘掉|脱下|脱掉)', clause):
            return True
        if re.search(r'(?:此前|先前|已经|早已|已|现已)(?:丢弃|扔掉|摘下|摘掉|脱下|脱掉)(?:了|整个|那只|原有的){0,2}(?:防毒面具|面具)', clause):
            return True
    return False


def identity_description_for_shot(description, scene_description, actor_state=''):
    """Keep identity traits but omit clearly standalone portrait pose directives.

    The shot action and camera determine present pose and framing. Keep
    ambiguous clauses and the original saved character description unchanged.
    """
    text = identity_description_for_scene(description, scene_description)
    clauses = re.split(r'([，。；;\n])', text)
    pose = re.compile(r'^\s*(?:全身(?:在画面中|入镜|站立(?:在[^，。；;\n]*)?)|双脚完整可见|身形微微前倾|重心微偏)\s*$')
    discarded = mask_was_discarded(actor_state)
    output = []
    previous_removed_mask = False
    for index in range(0, len(clauses), 2):
        clause = clauses[index]
        separator = clauses[index + 1] if index + 1 < len(clauses) else ''
        mentions_mask = discarded and bool(re.search(r'防毒面具|面罩', clause))
        removal_consistent = mask_was_discarded(clause)
        orphan = previous_removed_mask and bool(re.fullmatch(r'\s*(?:没|没有|未)戴上\s*', clause))
        if not (pose.fullmatch(clause) or (mentions_mask and not removal_consistent) or orphan):
            output.append(clause + separator)
        previous_removed_mask = bool(mentions_mask and not removal_consistent)
    return ''.join(output)


def valid_reference(path):
    from PIL import Image
    try:
        with Image.open(path) as image:image.verify()
        return True
    except (OSError,ValueError):return False


def reference_key(shot, settings=None):
    from image_engine import recipe
    ratio=export_settings(settings)['ratio']
    if shot.get('reference_layout')=='generated':
        value=dict(images=[m['image_hash'] for m in cast_members(shot)],camera=shot['camera'],ratio=ratio,
            action=shot['action'],actor_actions=shot.get('actor_actions',{}),scene=shot.get('scene_description',''),
            scene_image=shot.get('scene_image',''),visual_only=shot.get('visual_only',False),seed=shot['seed'],engine=generated_recipe(shot,quantized=True))
        if shot.get('scene_description'):value['identity_scene_policy']='shot-scene-priority-v1'
        if shot.get('start_state'):value['start_state']=shot['start_state']
        if shot.get('visual_context'):
            value['visual_context']={k:v for k,v in shot['visual_context'].items() if k not in ('engine','reference_engine')}
        context=shot.get('visual_context') or {}
        actor_states={**(shot.get('actor_actions') or {}), **(shot.get('identity_actor_states') or {})}
        if shot.get('identity_actor_states'):
            value['identity_actor_states']=shot['identity_actor_states']
        identities=context.get('identities') or [m['role'] for m in cast_members(shot)]
        if any(
            identity_description_for_shot(person.get(field,''), shot.get('scene_description',''), actor_states.get(person.get('id'),''))
            != identity_description_for_shot(person.get(field,''), shot.get('scene_description',''))
            for person in identities for field in ('description','outfit')
        ):
            value['identity_gear_policy']='past-discarded-mask-v1'
        if not shot.get('scene_image') and context.get('scene_key') and shot.get('scene_description'):
            value['scene_master_recipe']=recipe(**drawing_options(shot))
        if shot.get('quality_correction'):value['quality_correction']=shot['quality_correction']
        return digest(value)
    version=2 if shot['camera']=='medium' or (ratio=='9:16' and len(cast_members(shot))>1 and shot['camera'] in ('close','reaction','extreme_close')) else 1
    value=dict(images=[m['image_hash'] for m in cast_members(shot)],camera=shot['camera'],ratio=ratio,layout_version=version)
    if shot.get('scene_image'):value.update(scene_image=shot['scene_image'],visual_only=shot.get('visual_only',False),framing=[m['role'].get('framing','full') for m in cast_members(shot)],layout_version=4)
    if shot.get('reference_layout')=='faces':value['face_layout']='head-anchor-v1'
    return digest(value)


def head_aligned_layer(actor, width, height, framing='full', tight=False):
    """Align visible head silhouettes, rather than torso/prop bounding-box centers."""
    from PIL import Image
    region_height=max(1,round(actor.height*(.38 if framing=='half' else .19)))
    alpha=actor.getchannel('A').crop((0,0,actor.width,region_height))
    bounds=alpha.point(lambda v:255 if v>100 else 0).getbbox()
    if not bounds:bounds=(0,0,actor.width,region_height)
    x0,y0,x1,y1=bounds
    scale=min(height*(.32 if tight else .23)/max(1,y1-y0),width*.82/max(1,x1-x0))
    image=actor.resize((max(1,round(actor.width*scale)),max(1,round(actor.height*scale))),Image.Resampling.LANCZOS)
    left=round(width/2-(x0+x1)/2*scale)
    top=round(height*.26-(y0+y1)/2*scale)
    layer=Image.new('RGBA',(width,height))
    layer.alpha_composite(image,(left,top))
    return layer


def cutout(member):
    """U2Net's published RGB normalization; inference and cache remain local."""
    from PIL import Image
    import numpy as np
    global _session
    cache=WORKSPACE/'work/director_cutouts';cache.mkdir(parents=True,exist_ok=True)
    target=cache/(digest(dict(image=member['image_hash'],model=MATTE_MD5,version=2))+'.png')
    if target.is_file():
        with Image.open(target) as image:return image.convert('RGBA')
    if _session is None:
        import onnxruntime as ort
        if not MATTE_MODEL.is_file():raise ValueError('缺少本地同框抠图模型 U2Net，请保留完整模型目录。')
        if hashlib.md5(MATTE_MODEL.read_bytes()).hexdigest()!=MATTE_MD5:raise ValueError('同框抠图模型文件校验失败。')
        options=ort.SessionOptions();options.intra_op_num_threads=4;options.inter_op_num_threads=1
        _session=ort.InferenceSession(str(MATTE_MODEL),sess_options=options,providers=['CPUExecutionProvider'])
    with Image.open(reference_path(member['role'])) as source:image=source.convert('RGB')
    small=np.asarray(image.resize((320,320),Image.Resampling.LANCZOS),dtype=np.float32)
    normalized=(small/max(float(small.max()),1e-6)-np.array([.485,.456,.406],np.float32))/np.array([.229,.224,.225],np.float32)
    prediction=_session.run(None,{_session.get_inputs()[0].name:normalized.transpose(2,0,1)[None]})[0][0,0]
    mask=(prediction-prediction.min())/max(float(prediction.max()-prediction.min()),1e-6)
    alpha=Image.fromarray(np.uint8(np.clip(mask*255,0,255))).resize(image.size,Image.Resampling.LANCZOS)
    # Preserve light clothing and enclosed limbs that the matte marks as holes.
    import cv2
    values=np.asarray(alpha);binary=cv2.morphologyEx(np.uint8(values>40),cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
    contours,_=cv2.findContours(binary,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
    filled=np.zeros_like(values)
    if contours:cv2.drawContours(filled,[max(contours,key=cv2.contourArea)],-1,255,-1)
    alpha=Image.fromarray(np.maximum(values,cv2.erode(filled,np.ones((3,3),np.uint8))))
    bounds=alpha.point(lambda x:255 if x>100 else 0).getbbox()
    if not bounds or (bounds[2]-bounds[0])*(bounds[3]-bounds[1])<image.width*image.height*.02:
        raise ValueError(f'无法提取「{member["role"]["name"]}」的轮廓，请选择背景简洁、人物完整的形象。')
    image=image.convert('RGBA');image.putalpha(alpha);image=image.crop(bounds)
    temp=target.with_suffix('.partial.png');image.save(temp);temp.replace(target)
    return image


def portrait_crop(image, size, close, tight=False):
    from PIL import Image, ImageOps
    import cv2,numpy as np
    if close:
        detector=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
        faces=detector.detectMultiScale(cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY),1.1,4,minSize=(40,40))
        if len(faces):
            x,y,w,h=max(faces,key=lambda b:b[2]*b[3]);cw=min(image.width,w*(1.5 if tight else 2.1));ch=min(image.height,cw*size[1]/size[0])
            left=max(0,min(image.width-cw,x+w/2-cw/2));top=max(0,min(image.height-ch,y-h*.3))
            image=image.crop((round(left),round(top),round(left+cw),round(top+ch)))
        else:image=image.crop((image.width*.12,image.height*.04,image.width*.88,image.height*.82))
    return ImageOps.fit(image,size,method=Image.Resampling.LANCZOS,centering=(.5,.35))


def prepare_reference(shot, target, settings=None, cancelled=lambda:False, require_speaker_face=False):
    if shot.get('reference_layout')=='generated':
        from image_engine import generate,STYLES,recipe
        import json
        engine_options=drawing_options(shot)
        members=cast_members(shot)
        refs=[reference_path(m['role']) for m in members]
        if require_speaker_face and len(members)==1 and not shot.get('visual_only'):
            # A full-body identity image can overpower a textual close-up request.
            # Give the bounded face-recovery pass an actual portrait composition.
            from PIL import Image
            cache=WORKSPACE/'work/director_reference_portraits';cache.mkdir(exist_ok=True)
            portrait=cache/(members[0]['image_hash']+'_portrait_v1.png')
            if not portrait.is_file():
                with Image.open(refs[0]) as source:
                    portrait_crop(source.convert('RGB'),(512,768),True).save(portrait)
            refs=[portrait]
        cast='；'.join(f"从左到右第{i+1}位是参考图{i+1}中的{m['role']['name']}" for i,m in enumerate(members))
        camera={'wide':'全景','medium':'中景','close':'近景','push':'中景','reaction':'表情近景','extreme_close':'面部特写'}[shot['camera']]
        start_state = shot.get('start_state') or shot['action']
        context=shot.get('visual_context',{})
        style=context.get('style_prompt') or STYLES.get(members[0]['role'].get('style'),'')
        state_label = '只画动作开始前的状态' if shot.get('start_state') else '动作'
        prompt=(f'一张完整的短剧镜头起始画面，只画同一时刻，不要把连续动作画成多个分身。{cast}。保持参考人物的身份、发型、服装与画风。恰好{len(members)}个人，同一空间，无分屏。'
            f"场景：{shot.get('scene_description','简洁室内')}。{state_label}：{start_state}。{camera}。"+
            '；'.join(f"人物{i+1}：{m.get('action','')}" for i,m in enumerate(members) if m.get('action'))+
            style+' 不要字幕和文字。')
        identities=context.get('identities') or [m['role'] for m in members]
        scene_description=shot.get('scene_description','')
        actor_states = {**(shot.get('actor_actions') or {}), **(shot.get('identity_actor_states') or {})}
        prompt+=' 固定角色细节：'+'；'.join(
            f"{m.get('name','人物')}：{identity_description_for_shot(m.get('description',''), scene_description, actor_states.get(m.get('id'), ''))} "
            f"{identity_description_for_shot(m.get('outfit',''), scene_description, actor_states.get(m.get('id'), ''))}"
            for m in identities)
        if shot.get('identity_actor_states'):
            prompt+=' 当前角色状态：'+'；'.join(
                f"{m.get('name','人物')}：{shot['identity_actor_states'][m.get('id')]}"
                for m in identities if m.get('id') in shot['identity_actor_states'])
        prompt+=' 保持每个人各自的年龄、身材比例、脸型、发色、服装与持有道具；统一本作品的材质和打光，不要把成人变成儿童或玩偶。'
        prompt+=' 用户选定的人物参考图是外形基准；若文字描述与参考图的既有外形有冲突，保持参考图，不擅自更换人物服装或脸型。剧情明确要求的变装、变身或动作仍按本镜执行。'
        if shot.get('visual_only'):
            framing={'wide':'环境全景','medium':'环境或道具中景','close':'环境或道具近景','push':'向景物推近','reaction':'景物近景','extreme_close':'道具细节特写'}[shot['camera']]
            prompt=(shot.get('scene_description','')+('。本镜起始画面：' if shot.get('start_state') else '。本镜画面要求：')+start_state+'。'+framing+
                    '。没有人物，不要增加角色。'+style);refs=[]
        if shot.get('scene_image'):
            from director_assets import asset_path
            refs.append(asset_path(shot['scene_image']))
            prompt+=f'参考图{len(refs)}是场景参考，保留房间结构、配色和光线，按本镜头景别重新取景。人物姿态与道具当前位置以本镜头动作要求为准；移动过的道具不要在背景原位置重复出现。'
        elif context.get('scene_key') and shot.get('scene_description'):
            scene_key=context['scene_key'] if engine_options['engine']=='flux' else digest(dict(scene=context['scene_key'],engine=recipe(**engine_options)))
            master=target.parent/(scene_key+'.scene.png')
            if not valid_reference(master):
                generate('同一部短剧反复使用的空场景参考，没有人物。'+shot['scene_description']+'。'+style,
                         master,int(context['scene_key'][:8],16)%2147483647,size=(1024,576),cancelled=cancelled,**engine_options)
            refs.append(master)
            prompt+=f'参考图{len(refs)}是固定场景，只参考空间、建筑、光源与配色；按当前机位重新构图，人物和道具按本镜剧情安排。'
        if scene_description and not shot.get('visual_only'):
            prompt+=' 人物参考图仅用于人物外貌、服装和装备，不沿用人物参考图中的背景、地面或站位。当前镜头的环境、地面和人物动作以本镜场景和动作描述为准。当前场景：'+scene_description
        if shot.get('quality_correction'):prompt+=' 修正上一版明确画面问题：'+shot['quality_correction']
        if require_speaker_face and not shot.get('visual_only'):
            speaker=shot.get('speaker_id',shot['role_id'])
            index=next(i for i,m in enumerate(members) if m['role']['id']==speaker)
            prompt+=f' 本镜说话人是从左到右第{index+1}位。保持人物身份和同框顺序，必须拍胸部以上正面近景，让这位说话人的正脸和嘴部清晰，脸部占画面宽度至少三分之一；裁掉腰部以下，不拍全身。眼睛平视镜头，不仰头，不要背面、侧脸或用烟雾和头发遮脸。发型和头部饰物只按该人物参考图，其他人物不要替代他说话。'
        size={'9:16':(576,1024),'16:9':(1024,576),'1:1':(768,768)}[export_settings(settings)['ratio']]
        metadata=generate(prompt,target,shot['seed'],refs,size=size,cancelled=cancelled,**engine_options)
        target.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
        return dict(width=size[0],height=size[1],layout='generated',regions={})
    from PIL import Image, ImageDraw, ImageFilter,ImageOps
    import numpy as np
    size=NATIVE_SIZES[export_settings(settings)['ratio']];w,h=size
    members=cast_members(shot);regions={}
    if len(members)==1 and not shot.get('scene_image'):
        with Image.open(reference_path(members[0]['role'])) as source:
            source=source.convert('RGB')
            if shot['camera']=='medium':source=source.crop((0,0,source.width,round(source.height*.75)))
            canvas=portrait_crop(source,size,shot['camera'] in ('close','reaction','extreme_close'),shot['camera']=='extreme_close')
        regions[members[0]['role']['id']]=[0,0,100,100]
    else:
        # Use a common studio floor, rather than separate portrait panels.
        yy,xx=np.mgrid[0:h,0:w];light=1-np.minimum(1,np.sqrt(((xx-w*.45)/w)**2+((yy-h*.32)/h)**2))
        pixels=np.clip(np.array([158,169,185])+light[...,None]*54,0,255).astype('uint8')
        canvas=Image.fromarray(pixels).convert('RGBA')
        if shot.get('scene_image'):
            from director_assets import asset_path
            with Image.open(asset_path(shot['scene_image'])) as source:canvas=ImageOps.fit(source.convert('RGBA'),size,Image.Resampling.LANCZOS)
        if shot.get('visual_only'):
            canvas.convert('RGB').save(target);return dict(width=w,height=h,regions={},layout='scene_only')
        slot=w/len(members);close=shot['camera'] in ('close','reaction','extreme_close');baseline=h*(1.06 if close else .94)
        matched_portraits=bool(shot.get('scene_image')) and (close or shot['camera']=='medium' or any(m['role'].get('framing')=='half' for m in members))
        for i,member in enumerate(members):
            actor=cutout(member)
            if shot.get('reference_layout')=='faces' and len(members)>1 and (close or shot['camera']=='medium' or any(m['role'].get('framing')=='half' for m in members)):
                left=round(w*i/len(members));right=round(w*(i+1)/len(members))
                layer=head_aligned_layer(actor,right-left,h,member['role'].get('framing','full'),shot['camera']=='extreme_close')
                canvas.alpha_composite(layer,(left,0))
                regions[member['role']['id']]=[100*i/len(members),0,100/len(members),100]
                continue
            if matched_portraits:
                half=member['role'].get('framing')=='half';head_y=actor.height*(.22 if half else .105);head_height=actor.height*(.24 if half else .12)
                face_y=h*.29;scale=max(h*(.20 if shot['camera']=='extreme_close' else .16)/head_height,(h-face_y)/(actor.height-head_y))
                actor=actor.resize((max(1,round(actor.width*scale)),max(1,round(actor.height*scale))),Image.Resampling.LANCZOS)
                left=round(slot*(i+.5)-actor.width/2);top=round(face_y-head_y*scale)
                if actor.width>slot:
                    x=round((actor.width-slot)/2);actor=actor.crop((x,0,x+round(slot),actor.height));left=round(slot*i)
                canvas.alpha_composite(actor,(left,top));regions[member['role']['id']]=[100*i/len(members),0,100/len(members),100]
                continue
            if close:actor=actor.crop((0,0,actor.width,round(actor.height*(.35 if shot['camera']=='extreme_close' else .53))))
            elif shot['camera']=='medium':actor=actor.crop((0,0,actor.width,round(actor.height*.75)))
            vertical_close=(close or shot['camera']=='medium') and h>w
            scale=h*(.96 if close else .86)/actor.height if vertical_close else min(slot*.94/actor.width,h*(.96 if close else .86)/actor.height)
            actor=actor.resize((max(1,round(actor.width*scale)),max(1,round(actor.height*scale))),Image.Resampling.LANCZOS)
            if vertical_close and actor.width>slot:
                left_crop=round((actor.width-slot)/2);actor=actor.crop((left_crop,0,left_crop+round(slot),actor.height))
            left=round(slot*(i+.5)-actor.width/2);top=round(baseline-actor.height)
            shadow=Image.new('RGBA',size)
            ImageDraw.Draw(shadow).ellipse((left,baseline-actor.width*.07,left+actor.width,baseline+actor.width*.07),fill=(29,37,51,72))
            canvas=Image.alpha_composite(canvas,shadow.filter(ImageFilter.GaussianBlur(max(2,w*.012))))
            canvas.alpha_composite(actor,(left,top))
            regions[member['role']['id']]=[100*i/len(members),0,100/len(members),100]
        canvas=canvas.convert('RGB')
    temp=target.with_suffix('.partial.png');canvas.save(temp);temp.replace(target)
    return dict(width=w,height=h,regions=regions,layout='shared_studio' if len(members)>1 else 'portrait')


def actor_region(shot):
    members=cast_members(shot)
    if len(members)<2:return None
    speaker=shot.get('speaker_id',shot['role_id'])
    index=next((i for i,m in enumerate(members) if m['role']['id']==speaker),None)
    return None if index is None else [100*index/len(members),0,100/len(members),100]



def speaker_gaze_action(shot, member):
    """Retain an explicitly attributed, small gaze action when unambiguous.

    This is deliberately narrow: do not infer motives or split co-actor
    choreography, and leave complex movement for human review.
    """
    speaker_name=member['role'].get('name','').strip()
    if not speaker_name:
        return ''
    others=[m['role'].get('name','').strip() for m in cast_members(shot)
            if m['role']['id'] != member['role']['id']]
    for clause in re.split(r'[，,。；;！？!?\n：:]',shot.get('action','')):
        clause=clause.strip()
        if not clause.startswith(speaker_name) or any(n and n in clause for n in others):
            continue
        if not re.search(r'侧头看向|看向|望向|注视|凝视',clause):
            continue
        if re.search(r'猛|剧烈|大幅|转身|背对|扭头|迅速|大声|喊',clause):
            continue
        if len(clause)<=120:
            return clause
    return ''


def speaker_closeup_shot(shot):
    """Reframe a failed dialogue take on its identified speaker, keeping the scene."""
    import copy
    result=copy.deepcopy(shot)
    speaker=shot.get('speaker_id',shot.get('role_id'))
    member=next((m for m in cast_members(shot) if m['role']['id']==speaker),None)
    if member is None or speaker=='narrator' or shot.get('reuse_motion_from'):
        raise ValueError('无法确认当前镜头说话人，不自动替换取景。')
    member=copy.deepcopy(member)
    gaze=speaker_gaze_action(shot,member)
    if gaze:
        direction=(f'{gaze}。保持当前对白的情绪，自然说话。'
                   '胸部以上近景，尽量保留视线方向，双眼和嘴部清晰可见，三分之二正脸，轻微头肩活动。')
    else:
        direction=(f"{member['role']['name']}在原场景中面向画外对话对象，保持当前对白的情绪，自然说话。"
                   '胸部以上近景，双眼和嘴部清晰可见，三分之二正脸，轻微头肩活动，不大幅转头。对话对象位于画外。')
    member['action']=direction
    result.update(role=member['role'],role_id=speaker,role_ids=[speaker],cast=[member],
        image_hash=member['image_hash'],actor_actions={speaker:direction},camera='close',camera_motion='static',
        action=direction,start_state=direction,seed=(shot['seed']+3571)%2147483647,
        face_box=None,reference_layout='generated',
        quality_correction='只出现指定说话人；保持身份、服装、场景与台词情绪，嘴部和双眼清晰可见。')
    original_state=((shot.get('identity_actor_states') or {}).get(speaker)
                    or (shot.get('actor_actions') or {}).get(speaker))
    if original_state:
        result['identity_actor_states']={speaker:original_state}
    result['visual_context']={**shot.get('visual_context',{}),'identities':[
        {k:member['role'].get(k,'') for k in ('id','name','description','outfit','image')}]}
    return result


def action_sources(shot):
    """Each actor is translated separately, keeping assignment out of translation."""
    if shot.get('visual_only'):
        return [shot['action'],shot.get('scene_description','')] if shot.get('animate_scene') else []
    result=[shot['action']]+[member.get('action','') for member in cast_members(shot)]
    if shot.get('scene_description'):result.append(shot['scene_description'])
    return result


def motion_prompt(shot, translations, camera, *, preserve_cover=True):
    movements={'static':'Stationary camera.', 'push':'The camera moves slowly closer to the subject.',
        'pull':'The camera steadily pulls back, revealing more of the surrounding environment. No zoom in.',
        'track':'The camera tracks the moving subject smoothly.', 'pan':'The camera pans smoothly across the scene.'}
    explicit_camera=movements.get(shot.get('camera_motion'))
    if explicit_camera:camera=explicit_camera
    if shot.get('visual_only'):
        return ' '.join(['A continuous environmental effects shot without any visible people.',
            *[t for t in translations if t],camera,
            'Animate the described physical effects and preserve the reference scenery and visual style. No human figures, no faces, no additional characters, no cuts, no text.'])
    members=cast_members(shot);n=len(members)
    if n==1:
        intro='A continuous shot of the same single character in the reference image.'
    else:
        intro=f'A continuous shot with exactly {n} distinct characters together in the same scene, in the same left-to-right order as the reference image.'
    actions=[translations[0]]
    for i,action in enumerate(translations[1:1+n]):
        if action:actions.append(f'The character number {i+1} counting from the left: {action}')
    if not explicit_camera and n>1 and shot['camera'] in ('close','reaction','extreme_close'):
        camera='A stationary ensemble medium close-up. Keep every character visible in frame.'
    elif not explicit_camera and n>1 and shot['camera']=='push':camera='A slow gentle camera push toward the group, keeping every character visible.'
    speaker=shot.get('speaker_id',shot['role_id'])
    if len(translations)>n+1:actions.append('Scene and environment: '+translations[n+1])
    covered=preserve_cover and speaker_mouth_covered(shot)
    if covered:
        index=next(i for i,m in enumerate(members) if m['role']['id']==speaker)
        actions.append(f'Character number {index+1} from the left keeps the original opaque helmet or mouth covering fully closed. Convey speech through head and body gestures. Never reveal or animate a mouth through the covering. Other characters retain their original appearance.')
    elif shot.get('speech_kind') in ('os','narration') or speaker=='narrator':actions.append('The characters do not speak aloud. Keep their mouths relaxed and closed while they react naturally.')
    elif n>1 and shot['text'] and speaker!='narrator':
        index=next(i for i,m in enumerate(members) if m['role']['id']==speaker)
        actions.append(f'Only character number {index+1} from the left speaks. The other characters listen and react with their mouths closed.')
    elif n==1 and shot['text'] and shot.get('speech_kind','dialogue')=='dialogue':
        actions.append('The character speaks naturally with clearly varying open and closed mouth shapes.')
    if shot.get('visual_context',{}).get('style_prompt'):actions.append(shot['visual_context']['style_prompt'])
    if shot.get('continuation'):actions.append('Continue forward from the exact current state of this first frame. Do not restart or reverse an action already completed. Preserve screen direction, props and lighting.')
    visibility='Preserve the original head coverings and face visibility.' if covered else 'Keep the faces visible.'
    wardrobe=("Natural expressive body movement. Preserve each character's individual face, hairstyle, clothes, footwear, and visual style. "
        "If feet are visible, keep the original footwear unchanged; never turn a character who wears shoes into a barefoot character. ")
    return ' '.join([intro,*actions,camera,wardrobe+visibility+' No additional characters, no swapping identities, no cuts, no text.'])

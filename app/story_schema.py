"""Versioned authoring document, timing checks and conversion to real director shots."""
import copy
import math
import re
import uuid
from difflib import SequenceMatcher
import image_engine
from visual_styles import SOFT_PHOTO
from director_schema import text, number, valid_id, CAMERAS, EMOTIONS, export_settings,ACTION_LIMIT

ASSET_SLOTS = {'front': '正面半身', 'side': '侧面', 'full': '全身',
               'happy': '开心', 'angry': '生气', 'serious': '严肃'}


def character_profile(actor, style, index):
    description=actor['description']
    gender='male' if re.search(r'男性|男生|男大学生|成年男',description) else ('female' if re.search(r'女性|女生|女大学生|成年女',description) else 'generic')
    choices=['Dylan','Uncle_Fu','Ryan','Eric','Aiden'] if gender=='male' else ['Vivian','Serena','Ono_Anna','Sohee']
    return dict(name=actor['name'], description=description, outfit=actor['outfit'], personality=actor['personality'],
                style=style, framing='full', look={'gender':gender}, voice=choices[index%len(choices)])


def brief_spec(data):
    if not isinstance(data, dict):
        raise ValueError('创作要求格式不正确。')
    if data.get('input_mode') == 'script' or data.get('script'):
        script = text(data.get('script', ''), 60000, '完整剧本', True)
        mode = data.get('work_mode', 'original')
        if mode not in ('original', 'existing'):
            raise ValueError('请选择原创作品或已有作品。')
        online = data.get('online_research', True)
        if type(online) is not bool:
            raise ValueError('联网参考选项无效。')
        ids = data.get('role_ids', [])
        if not isinstance(ids, list) or not 1 <= len(ids) <= 8 or any(not isinstance(i, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}', i) for i in ids) or len(set(ids)) != len(ids):
            raise ValueError('请先选好本作品的1至8位主要角色。')
        style = data.get('style', 'realistic')
        if not isinstance(style, str) or style not in image_engine.STYLES:
            raise ValueError('人物画风无效。')
        duration = int(number(data.get('duration', max(3, min(86400, len(script)/4))), 3, 86400, '剧本估计秒数'))
        episodes = number(data.get('episodes', 1), 1, 12, '分集数量')
        if int(episodes) != episodes:
            raise ValueError('分集数量应为整数。')
        return dict(input_mode='script', title=text(data.get('title', ''), 60, '作品名称', True),
            work_mode=mode, online_research=online, script=script, role_ids=list(ids),
            characters='', scene='', outline=script[:6000], duration=duration, episodes=int(episodes), style=style,
            export=export_settings(data.get('export', {'ratio':'9:16', 'resolution':'1080'})))
    idea = text(data.get('idea', ''), 6000, '故事想法')
    result = {key: text(data.get(key, ''), limit, label, not bool(idea)) for key, limit, label in
              [('characters', 2000, '人物设定'), ('scene', 1500, '场景描述'), ('outline', 6000, '剧情大纲')]}
    if idea:
        result.update(idea=idea, outline=idea)
    result['title'] = text(data.get('title', ''), 60, '作品名称')
    for key, low, high, default, label in [('duration', 30, 600, 180, '每集目标秒数'),
            ('episodes', 1, 12, 1, '集数')]:
        value = number(data.get(key, default), low, high, label)
        if int(value) != value:
            raise ValueError(label+'请填写整数。')
        result[key] = int(value)
    style = data.get('style', 'guoman')
    if not isinstance(style, str) or style not in image_engine.STYLES:
        raise ValueError('人物画风无效。')
    result['style'] = style
    result['export'] = export_settings(data.get('export', {'ratio': '9:16', 'resolution': '1080'}))
    return result


def timing(duration):
    # Reserve a genuinely short opening; all remaining targets stay within 3-8s.
    count = max(5, math.ceil(duration / 6))
    rest = duration - 3
    values = [3.] + [round(rest/(count-1), 2)] * (count-1)
    values[-1] = round(duration-sum(values[:-1]), 2)
    return values


def dialogue_seconds(value, speed=1.):
    # Explicit estimate, replaced by the real waveform duration after audition.
    chinese = len(re.findall(r'[\u3400-\u9fff]', value))
    words = len(re.findall(r'[A-Za-z0-9]+', value))
    return round((chinese/4 + words/2.5)/speed + .42, 2) if value else 0.


def issues(document):
    findings = []
    from story_integrity import issues as integrity_issues
    findings.extend(integrity_issues(document))
    if document.get('brief', {}).get('style') in ('realistic', SOFT_PHOTO):
        for actor in document.get('characters', []):
            style = actor.get('role_snapshot', {}).get('style')
            if style and style not in ('realistic', SOFT_PHOTO):
                findings.append(dict(level='warning', message=f'「{actor["name"]}」目前沿用{style}风格的已选形象；选择仿真人不会自动改变旧角色，请在人物中另存写实形象。'))
    for actor in document.get('characters', []):
        if not actor.get('reference_image'):
            findings.append(dict(level='error', message=f'角色「{actor["name"]}」尚未准备主形象。'))
    for scene in document.get('scenes', []):
        if not scene.get('asset_id'):
            findings.append(dict(level='warning', message=f'场景「{scene["name"]}」未绑定背景图，将使用素色布景；文字描述不能替代背景图片。'))
    for episode in document.get('episodes', []):
        shots = episode.get('shots', [])
        expected = len(timing(document['brief']['duration']))
        supplied = document['brief'].get('input_mode') == 'script'
        if not supplied and len(shots) != expected:
            findings.append(dict(level='error', episode=episode['number'], message=f'第{episode["number"]}集分镜尚未写完（{len(shots)}/{expected}）。'))
        elif supplied and not document.get('complete'):
            findings.append(dict(level='error', episode=episode['number'], message=f'第{episode["number"]}集原稿尚未整理完，已保存{len(shots)}个画面，可继续准备。'))
        if supplied and document.get('complete') and not shots:
            findings.append(dict(level='error', message='原稿尚未形成可制作的画面。'))
        for i, shot in enumerate(shots, 1):
            if shot.get('visual_only') and not next((s.get('asset_id') for s in document.get('scenes', []) if s['key'] == shot['scene']), None):
                findings.append(dict(level='error', episode=episode['number'], message=f'第{i}个画面的场景还未画好，请继续准备场景。'))
            if dialogue_seconds(shot['text']) > shot['duration']:
                findings.append(dict(level='warning', episode=episode['number'], shot=i,
                    message=f'第{episode["number"]}集第{i}镜对白估计{dialogue_seconds(shot["text"]):g}秒，超过目标{shot["duration"]:g}秒；配音后可能延长。'))
            if shot['text'] and shot['text'].rstrip()[-1] not in '。！？!?…」”’':
                findings.append(dict(level='warning',episode=episode['number'],shot=i,
                    message=f'第{episode["number"]}集第{i}镜台词可能未完整收句，请核对。'))
            value=re.sub(r'[^\w\u3400-\u9fff]','',shot['text'])
            if len(value)>=4:
                prior=next((j for j,s in enumerate(shots[:i-1],1) if len(re.sub(r'[^\w\u3400-\u9fff]','',s['text']))>=4
                    and SequenceMatcher(None,value,re.sub(r'[^\w\u3400-\u9fff]','',s['text'])).ratio()>.9),None)
                if prior:
                    findings.append(dict(level='warning',episode=episode['number'],shot=i,
                        message=f'第{episode["number"]}集第{i}镜与第{prior}镜台词相似，请核对是否为有意重复。'))
            if not shot['text'] and re.search(r'[“‘「][^”’」]+[”’」]',shot['action']):
                findings.append(dict(level='warning',episode=episode['number'],shot=i,
                    message=f'第{episode["number"]}集第{i}镜动作中含引号文字，台词为空；如需配音请移到台词栏。'))
        if shots and not any(s['text'] for s in shots):
            findings.append(dict(level='warning',episode=episode['number'],message=f'第{episode["number"]}集没有可配音台词，请确认是否为有意的无对白故事。'))
        total = round(sum(s['duration'] for s in shots), 2)
        if not supplied and shots and abs(total-document['brief']['duration']) > 1:
            findings.append(dict(level='warning', message=f'第{episode["number"]}集当前目标合计{total:g}秒。'))
    return findings


def validate_document(value, store):
    from director_assets import asset_path
    if not isinstance(value, dict):
        raise ValueError('创作工程格式不正确。')
    doc = copy.deepcopy(value)
    doc['id'] = valid_id(doc.get('id'), '创作工程')
    doc['brief'] = brief_spec(doc.get('brief'))
    doc['title'] = text(doc.get('title', ''), 60, '作品名称', True)
    actors, scenes, episodes = doc.get('characters'), doc.get('scenes'), doc.get('episodes')
    if not isinstance(actors, list) or not 1 <= len(actors) <= 8:
        raise ValueError('每个故事需要1至8位主要角色。')
    if not isinstance(scenes, list) or not 1 <= len(scenes) <= 8:
        raise ValueError('每个故事需要1至8个主要场景。')
    if not isinstance(episodes, list) or len(episodes) != doc['brief']['episodes']:
        raise ValueError('分集数量与创作要求不一致。')
    for actor in actors:
        for key, limit in [('key', 32), ('name', 30), ('description', 1200), ('outfit', 150), ('personality', 150)]:
            actor[key] = text(actor.get(key, ''), limit, '人物'+key, key in ('key', 'name', 'description'))
        role = store.get(actor['role_id']) if actor.get('role_id') else None
        allowed = {x['image'] for x in role.get('images', [])} if role else set()
        if role and role.get('image'):
            allowed.add(role['image'])
        if actor.get('reference_image') and actor['reference_image'] not in allowed:
            raise ValueError('人物参考图必须属于绑定的角色。')
        assets = actor.get('assets', {})
        if not isinstance(assets, dict) or set(assets)-set(ASSET_SLOTS):
            raise ValueError('人物资产包格式不正确。')
        for image in assets.values():
            if image and image not in allowed:
                raise ValueError('资产包只能使用该角色的已保存形象。')
    for scene in scenes:
        for key, limit in [('key', 32), ('name', 50), ('description', 240)]:
            scene[key] = text(scene.get(key, ''), limit, '场景'+key, True)
        if scene.get('asset_id'):
            asset_path(scene['asset_id'], 'background')
    actor_keys, scene_keys = [x['key'] for x in actors], [x['key'] for x in scenes]
    if len(set(actor_keys)) != len(actors) or len(set(scene_keys)) != len(scenes):
        raise ValueError('角色或场景编号重复。')
    for index, episode in enumerate(episodes, 1):
        episode['number'] = index
        episode['title'] = text(episode.get('title', ''), 60, '集名', True)
        episode['summary'] = text(episode.get('summary', ''), 600, '分集梗概')
        shots = episode.get('shots', [])
        if not isinstance(shots, list) or len(shots) > 300:
            raise ValueError('单集最多300镜。')
        for shot in shots:
            shot['id'] = valid_id(shot.get('id'), '镜头')
            cast = shot.get('characters')
            if not isinstance(cast, list) or not 1 <= len(cast) <= 4 or any(x not in actor_keys for x in cast) or len(set(cast)) != len(cast):
                raise ValueError('每镜需要1至4位不重复的已定义角色。')
            if shot.get('speaker') not in cast+['narrator'] or shot.get('scene') not in scene_keys:
                raise ValueError('说话人或场景未在本工程中定义。')
            overrides = shot.get('reference_images', {})
            actions = shot.get('actor_actions', {})
            if not isinstance(overrides, dict) or any(key not in cast for key in overrides):
                raise ValueError('镜头形象版本必须对应本镜出场角色。')
            if not isinstance(actions, dict) or any(key not in cast for key in actions):
                raise ValueError('镜头人物状态必须对应本镜出场角色。')
            for key, image in overrides.items():
                actor = next(a for a in actors if a['key'] == key)
                role = store.get(actor['role_id']) if actor.get('role_id') else None
                allowed = {v['image'] for v in role.get('images', [])} if role else set()
                if role and role.get('image'):
                    allowed.add(role['image'])
                if not isinstance(image, str) or image not in allowed:
                    raise ValueError('镜头形象版本必须属于对应角色。')
            for key, action in list(actions.items()):
                actions[key] = text(action, 160, '镜头人物状态')
            for key, limit in [('text', 40), ('action', ACTION_LIMIT), ('beat', 120), ('emotion_note', 100)]:
                shot[key] = text(shot.get(key, ''), limit, '镜头'+key, key == 'action')
            if shot.get('camera') not in CAMERAS or shot.get('emotion') not in EMOTIONS:
                raise ValueError('镜头景别或情绪无效。')
            kind=shot.get('speech_kind','narration' if shot['speaker']=='narrator' else 'dialogue')
            if kind not in ('dialogue','os','narration'):
                raise ValueError('说话方式无效。')
            if kind=='narration' and shot['speaker']!='narrator':
                raise ValueError('旁白请将说话人设为narrator；角色开口讲话用dialogue，内心独白用os。')
            if shot['speaker']=='narrator' and kind!='narration':
                raise ValueError('narrator说话人应使用narration旁白方式。')
            shot['speech_kind']=kind
            from story_integrity import MOTIONS
            if shot.get('camera_motion', 'auto') not in MOTIONS:
                raise ValueError('自动镜头运动无效。')
            if 'start_state' in shot:
                shot['start_state'] = text(shot['start_state'], 160, '镜头起始状态')
            if type(shot.get('visual_only', False)) is not bool:
                raise ValueError('纯场景画面标记无效。')
            if shot.get('visual_only') and shot['text'] and kind == 'dialogue':
                raise ValueError('角色开口说话时需要出镜；画外声音请用旁白或内心独白。')
            shot['duration'] = number(shot.get('duration'), 3, 8, '分镜目标秒数')
        if len(set(s['id'] for s in shots)) != len(shots):
            raise ValueError('镜头编号重复。')
    doc['schema_version'] = 1
    return doc


def director_project(document, episode_number, store):
    from voice_catalog import role_voice
    from director_schema import validate_project
    doc = validate_document(document, store)
    from story_integrity import require_pass
    require_pass(doc)
    blockers = [x['message'] for x in issues(doc) if x['level'] == 'error' and
                (not x.get('episode') or x['episode'] == episode_number)]
    if blockers:
        raise ValueError(' '.join(blockers))
    if type(episode_number) is not int or not 1 <= episode_number <= len(doc['episodes']):
        raise ValueError('请选择有效的集数。')
    episode = doc['episodes'][episode_number-1]
    actors = {a['key']: a for a in doc['characters']}
    scenes = {s['key']: s for s in doc['scenes']}
    shots, script = [], []
    for i, row in enumerate(episode['shots']):
        cast = [actors[key] for key in row['characters']]
        speaker = actors.get(row['speaker'])
        lead = speaker or cast[0]
        role = store.get(lead['role_id'])
        scene = scenes[row['scene']]
        # Resolve structured IDs only in actions; keep the author's dialogue verbatim.
        actor_pattern = r'(?<![A-Za-z0-9_])('+'|'.join(re.escape(k) for k in sorted(actors,key=len,reverse=True))+r')(?![A-Za-z0-9_])'
        action = re.sub(actor_pattern,lambda match:actors[match.group(0)]['name'],row['action'])
        script.append(f'{speaker["name"] if speaker else "旁白"}：{row["text"]}')
        shots.append(dict(id=row['id'], role_id=lead['role_id'], role_ids=[a['role_id'] for a in cast],
            speaker_id=speaker['role_id'] if speaker else 'narrator',
            reference_images={a['role_id']: row.get('reference_images', {}).get(a['key'], a['reference_image']) for a in cast},
            reference_layout=('generated' if image_engine.capabilities()['reference'] and image_engine.ready() else 'faces'),
            text=row['text'], action=action, camera=row['camera'], emotion=row['emotion'],
            emotion_note=row.get('emotion_note', ''), duration=row['duration'], voice=role_voice(role), voice_mode='role',
            pause_before=.12, pause_after=.3, speed=1., lip_sync=bool(row['text']) and speaker is not None and row['speech_kind']=='dialogue',
            speech_kind=row['speech_kind'],
            visual_only=row.get('visual_only', False),animate_scene=bool(row.get('visual_only',False)),
            scene_image=scene.get('asset_id', ''), scene_description=scene['description'],
            motion_seconds=6 if row['duration'] > 4 else 3, source_shot=str(i+1),
            actor_actions={actors[key]['role_id']: value for key, value in row.get('actor_actions', {}).items()},
            seed=42+i*71, story_beat=row.get('beat', ''), scene_name=scene['name']))
        for field in ('camera_motion', 'start_state'):
            if row.get(field):
                shots[-1][field] = row[field]
        from sound_library import plan_cues
        cues = plan_cues(action, scene['name']+' '+scene['description'], row['id'])
        if cues:shots[-1]['sound_cues'] = cues
    project = dict(id=uuid.uuid4().hex, title=f'{doc["title"][:40]} · 第{episode_number}集', shots=shots,
        script='\n'.join(script), export=doc['brief']['export'], captions={'speaker_name': False},
        sound={'track': 'comedy' if re.search(r'喜剧|轻松|搞笑',doc['brief']['outline']) else
                       'suspense' if re.search(r'悬疑|惊悚|侦探',doc['brief']['outline']) else 'none',
               'level':-22,'duck':True,'fade':1},
        authoring={'document_id': doc['id'], 'episode': episode_number, 'target_seconds': doc['brief']['duration']})
    if doc['brief'].get('input_mode') == 'script':
        project['authoring']['input_mode'] = 'script'
    project['visual_bible']={'style':doc['brief'].get('style','3d')}
    return validate_project(project, store)

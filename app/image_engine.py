"""Replaceable local image engine; public settings expose capabilities, not tuning knobs."""
import json, os, pathlib, re, shutil, time, uuid
from settings import APP_DIR, WORKSPACE
from process_control import run_child
from visual_styles import SOFT_PHOTO, SOFT_PHOTO_IMAGE_PROMPT

CONFIG = APP_DIR/'image_engine.json'
BIN = WORKSPACE/'runtime/image-engine/sd-cli.exe'
MODELS = WORKSPACE/'work/local_test/models/image_candidates'
ENGINES = {
    'flux': dict(name='FLUX.2 klein 4B · 本地', model=MODELS/'flux-2-klein-4b-Q4_0.gguf',
        vae=MODELS/'flux2_vae.safetensors', encoder=WORKSPACE/'work/local_test/models/Qwen3-4B-GGUF/Qwen3-4B-Q4_K_M.gguf',
        steps=4,reference=True,quantization='Q4_0',tag='flux-klein4b',max_vram=6.5,timeout=900),
    'flux9': dict(name='FLUX.2 klein 9B · Q4 · 本地', model=MODELS/'flux-2-klein-9b-Q4_0.gguf',
        vae=MODELS/'flux2_vae.safetensors', encoder=WORKSPACE/'work/local_test/models/Qwen3-8B-GGUF/Qwen3-8B-Q4_K_M.gguf',
        steps=4,reference=True,quantization='Q4_0',tag='flux-klein9b',max_vram=5.5,timeout=1800,
        expected_sizes={'model':5616208032,'encoder':5027784512,'vae':249519092},
        extra_args=['--backend','te=cpu,vae=cpu,diffusion=cuda0','--vae-tiling','--disable-prefetch','--threads','4']),
}
ENCODER_SHA256 = '38af6f386a520611159c6041c58a01155ff92c2be943d231898967ba05167c5f'
ENGINES['flux9_heretic'] = {
    **ENGINES['flux9'],
    'name': 'FLUX.2 klein 9B · 社区实验编码器',
    'encoder': WORKSPACE/'work/local_test/models/encoder_candidates/DreamFast-Qwen3-8B/qwen3-8b-heretic-Q4_K_M.gguf',
    'expected_sizes': {**ENGINES['flux9']['expected_sizes'], 'encoder': 5027783616},
    'tag': 'flux-klein9b-dreamfast-' + ENCODER_SHA256[:12],
    'extra_args': list(ENGINES['flux9']['extra_args']),
    'encoder_sha256': ENCODER_SHA256,
    'encoder_source': 'https://huggingface.co/DreamFast/qwen3-8b-heretic',
    'encoder_revision': '07019d2298fc4802707f8a97e1afe052024cce48',
    'encoder_validation': '文件结构和完整性已核验；本机生成效果尚未验证',
}
# Apply the measured GPU execution profile only to the standard FLUX9 engine.
# The separate experimental encoder spec above retains its existing parameters.
ENGINES['flux9'].update(
    tag='flux-klein9b-gpu-te-vae-4g-1thread-v2', max_vram=4.0,
    extra_args=['--backend','te=cuda0,vae=cuda0,diffusion=cuda0',
                '--vae-tiling','--vae-tile-size','256','--disable-prefetch','--threads','1'])
ENCODER_LABELS = {'flux9': '标准编码器', 'flux9_heretic': '社区实验编码器（效果待验证）'}
SDXL_SHA256 = '31e35c80fc4829d14f90153f4c74cd59c90b779f6afe05a74cd6120b893f7e5b'
ENGINES['sdxl'] = dict(
    name='Stable Diffusion XL 1.0 · 本地', family='sdxl',
    model=MODELS/'SDXL-1.0/sd_xl_base_1.0.safetensors', components=('model',),
    expected_sizes={'model': 6938078334}, model_sha256=SDXL_SHA256,
    model_source='https://huggingface.co/stabilityai/stable-diffusion-xl-base-1.0',
    model_revision='462165984030d82259a11f4367a4eed129e94a7b',
    steps=30, cfg=6.5, sampler='dpm++2m', reference=False, quantization='original',
    # Keep decode work on the GPU, with tiled execution and room for the desktop.
    # The engine budget is advisory; monitored jobs must still check live usage.
    tag='sdxl-base10-31e35c80-30step-en-gpuvae-v2', max_vram=4.0, timeout=2400,
    extra_args=['--scheduler','karras','--backend','te=cpu,vae=cuda0,diffusion=cuda0',
                '--vae-tiling','--vae-tile-size','256','--disable-prefetch','--threads','1'])
MODEL_LABELS = {'flux9': 'FLUX.2 klein 9B · Q4', 'sdxl': 'Stable Diffusion XL 1.0'}
STYLES = {'3d':'3D animated film character style, soft studio lighting.', 'guoman':'中国动画漫画插画风格。',
          'anime':'日系动画插画，清晰线条，赛璐璐上色。', 'realistic':'自然光，真实摄影风格。',
          SOFT_PHOTO:SOFT_PHOTO_IMAGE_PROMPT}

def selected():
    try: value=json.loads(CONFIG.read_text('utf-8-sig')).get('engine','legacy')
    except (OSError,ValueError,AttributeError):value='legacy'
    return value if isinstance(value,str) and value in ENGINES else 'legacy'

def preferred_flux_engine():
    current=selected()
    if current in ENCODER_LABELS:return current
    try: candidate=json.loads(CONFIG.read_text('utf-8-sig')).get('preferred_flux_engine')
    except (OSError,ValueError,AttributeError):candidate=None
    return candidate if isinstance(candidate,str) and candidate in ENCODER_LABELS else 'flux9'

def resolve_engine(engine=None,references=False,reference_engine=None):
    """Identity references require FLUX; never silently discard them for SDXL."""
    if reference_engine is not None and (not isinstance(reference_engine,str) or reference_engine not in ENCODER_LABELS):
        raise ValueError('参考图引擎配置无效，未开始生成。')
    requested=engine or selected()
    if requested=='sdxl' and references:
        return reference_engine or preferred_flux_engine()
    return requested

def ready(engine=None):
    engine=engine or selected()
    if engine not in ENGINES or not BIN.is_file():return False
    spec=ENGINES[engine]
    try:
        return all(spec[k].is_file() and spec[k].stat().st_size>0 and
            (k not in spec.get('expected_sizes',{}) or spec[k].stat().st_size==spec['expected_sizes'][k])
            for k in spec.get('components',('model','vae','encoder')))
    except OSError:return False

def recipe(visual_only=False,quantized=False,engine=None,references=False,reference_engine=None):
    spec=ENGINES.get(resolve_engine(engine,references,reference_engine),{})
    return spec.get('tag','legacy')+('-q4' if quantized else '')+('-scene-v4' if visual_only else '-scene-v3')

def build_command(engine,prompt_path,output,seed,size):
    spec=ENGINES[engine]
    model_args=(['-m',str(spec['model'])] if spec.get('family')=='sdxl' else
                ['--diffusion-model',str(spec['model']),'--vae',str(spec['vae']),'--llm',str(spec['encoder'])])
    return [str(BIN),*model_args,
        '--prompt-file',str(prompt_path),'--cfg-scale',str(spec.get('cfg',1)),
        '--steps',str(spec['steps']),'--sampling-method',spec.get('sampler','euler'),
        '--offload-to-cpu','--diffusion-fa','--max-vram',str(spec['max_vram']),'--mmap',
        *spec.get('extra_args',[]),'-W',str(size[0]),'-H',str(size[1]),'-s',str(seed),'-o',str(output)]

def _save_selection(updates):
    try:
        config = json.loads(CONFIG.read_text('utf-8-sig'))
        if not isinstance(config,dict):raise ValueError()
    except (OSError,ValueError):
        raise ValueError('绘图配置无法读取，原设置已保留。')
    config.update(updates)
    temporary=CONFIG.with_name(CONFIG.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('x',encoding='utf-8') as output:
            json.dump(config,output,ensure_ascii=False,indent=2)
            output.flush();os.fsync(output.fileno())
        os.replace(temporary,CONFIG)
    finally:
        temporary.unlink(missing_ok=True)
    return capabilities()

def set_encoder(engine):
    """Persist an allowlisted selection; the caller holds the shared job lock."""
    if not isinstance(engine,str) or engine not in ENCODER_LABELS:
        raise ValueError('请选择已安装的文字理解方式。')
    if selected() not in ENCODER_LABELS:
        raise ValueError('该选项只适用于当前 FLUX.2 klein 9B 绘图模型。')
    if not ready(engine):raise ValueError('所选编码器文件未准备完整，设置没有更改。')
    return _save_selection(dict(engine=engine,preferred_flux_engine=engine,
        encoder_selected_on=time.strftime('%Y-%m-%d %H:%M:%S'),encoder_rollback_engine='flux9'))

def set_engine(engine):
    """Switch models without starting computation, touching images or clearing incidents."""
    if not isinstance(engine,str) or engine not in MODEL_LABELS:
        raise ValueError('请选择列表中的绘图模型。')
    preferred=preferred_flux_engine()
    actual=preferred if engine=='flux9' else engine
    if not ready(actual):raise ValueError('所选绘图模型文件未准备完整，设置没有更改。')
    return _save_selection(dict(engine=actual,preferred_flux_engine=preferred,
        model_selected_on=time.strftime('%Y-%m-%d %H:%M:%S')))

def capabilities():
    engine=selected()
    choices=[dict(id=key,label=label,available=ready(preferred_flux_engine() if key=='flux9' else key))
             for key,label in MODEL_LABELS.items()]
    selection_id='flux9' if engine in ENCODER_LABELS else engine
    if selection_id not in MODEL_LABELS:
        choices.insert(0,dict(id=selection_id,label=ENGINES.get(engine,{}).get('name','DreamShaper 8 · 兼容引擎'),available=False))
    note=('新角色和无参考场景使用 SDXL；参考图修改及保持角色一致的分镜由现有 FLUX 处理。'
          '已有图片不变；SDXL 效果待本机验证。' if engine=='sdxl' else
          '角色、参考图修改及分镜使用当前 FLUX。切换模型不会重新绘制已有图片。' if engine!='legacy' else
          '当前使用旧版兼容引擎，可切换到已安装的绘图模型。')
    return dict(id=engine,name=ENGINES.get(engine,{}).get('name','DreamShaper 8 · 兼容引擎'),
                selection_id=selection_id,engine_choices=choices,selection_note=note,
                ready=ready(engine),reference=ENGINES.get(engine,{}).get('reference',False),
                reference_engine=resolve_engine(engine,True),
                reference_available=ready(resolve_engine(engine,True)),
                encoder_choices=[dict(id=key,label=label,available=ready(key)) for key,label in ENCODER_LABELS.items()] if engine in ENCODER_LABELS else [],
                encoder_note=('当前为社区实验版本，可切回标准版本。' if engine=='flux9_heretic' else '当前为标准版本。'),
                native_size=[768,1024] if engine!='legacy' else [512,768])

def role_prompt(role):
    from portrait_spec import FEATURES,feature_text
    # Existing fields stay readable. New ordinary-mode roles have a single description.
    pieces=[role.get('description',''),role.get('outfit','')]
    look=role.get('look',{})
    if look.get('age'):pieces.append(f"年龄：{look['age']}岁。")
    for key in FEATURES:
        value=feature_text(look,key)
        if value:pieces.append(FEATURES[key][0]+'：'+str(value)+'。')
    pieces.append({'full':'全身完整入镜，头部和双脚均在画面内。','half':'腰部以上半身构图。','head':'头像，面部和肩膀入镜。'}[role.get('framing','full')])
    if not look.get('background') and not any(s in ''.join(pieces) for s in ('背景','background')):pieces.append('简洁浅色背景。')
    pieces.append(STYLES[role.get('style','3d')])
    return '\n'.join(p for p in pieces if p)

def _translation_segments(prompt):
    """Keep every character, in small sentence chunks for the local translator's token budget."""
    segments=[]
    for sentence in re.split(r'(?<=[。！？；\n])',prompt):
        while len(sentence)>80:
            cut=max(sentence.rfind(mark,0,81) for mark in (' ','，',',','；',';'))+1
            if cut<40:cut=80
            segments.append(sentence[:cut]);sentence=sentence[cut:]
        if sentence:segments.append(sentence)
    return segments

def prepare_prompt(prompt,engine,cancelled,report):
    """Translate only SDXL Chinese input, preserving source and never falling back to partial text."""
    translated=engine=='sdxl' and bool(re.search(r'[\u3400-\u9fff]',prompt))
    details=dict(applied=translated,model='',source_language='zh_or_user_original',target_language='original')
    if not translated:return prompt,details
    from portrait_llm import translate_texts,MODEL_NAME
    def check_cancelled():
        if cancelled():raise InterruptedError('绘制已停止。')
    check_cancelled();report(3,'正在为 SDXL 完整翻译描述；原始设定会保留…')
    sources=_translation_segments(prompt)
    results=translate_texts(sources,check_cancelled=check_cancelled,allow_partial=False)
    if (not isinstance(results,list) or len(results)!=len(sources) or any(
            not isinstance(item,str) or not item.strip() or re.search(r'[\u3400-\u9fff\ufffd]',item)
            for item,source in zip(results,sources) if source.strip())):
        raise ValueError('SDXL 描述翻译不完整，已停止；没有用缺失信息的描述绘图。')
    check_cancelled()
    details.update(model=MODEL_NAME,target_language='en',segments=len(sources))
    return '\n'.join(results),details

def generate(prompt, target, seed, references=(), engine=None, size=(768,1024), cancelled=lambda:False, report=lambda *a:None,
             reference_engine=None):
    requested_engine=engine or selected()
    engine=resolve_engine(requested_engine,bool(references),reference_engine)
    # The translator is also a model workload: guard before either model starts or writes run artifacts.
    from runtime_health import assert_runtime_allowed
    assert_runtime_allowed()
    if not ready(engine):raise ValueError('所选本地绘图引擎文件不完整，请恢复模型文件后重试。')
    spec=ENGINES[engine]
    if references and not spec['reference']:raise ValueError('这个引擎不支持参考图修改。')
    if len(references)>5:raise ValueError('单次最多使用4张角色参考图和1张场景图。')
    if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>6000:raise ValueError('绘图描述需为1至6000字。')
    if cancelled():raise InterruptedError('绘制已停止。')
    generation_prompt,translation=prepare_prompt(prompt,engine,cancelled,report)
    assert_runtime_allowed()
    folder=WORKSPACE/'work/image_engine_runs'/uuid.uuid4().hex;folder.mkdir(parents=True)
    (folder/'original_prompt.txt').write_text(prompt,'utf-8')
    prompt_path=folder/'prompt.txt';prompt_path.write_text(generation_prompt,'utf-8')
    output=folder/'output.png';log_path=folder/'engine.log'
    args=build_command(engine,prompt_path,output,seed,size)
    for index,ref in enumerate(references):
        # Keep the C++ command paths ASCII on Windows, including user media paths.
        local=folder/f'reference_{index}.png'
        from PIL import Image
        with Image.open(ref) as im:
            image=im.convert('RGB');image.thumbnail((1024,1024));image.save(local)
        args+=['-r',str(local)]
    report(8,'正在加载'+spec['name']+'…');start=time.monotonic();stage=0;last_report=start
    def update_progress():
        nonlocal stage,last_report
        detail=log_path.read_text('utf-8',errors='replace')[-5000:]
        level=3 if 'decode_first_stage' in detail or 'decoding ' in detail else 2 if 'generating image' in detail else 1 if 'cached graph' in detail else 0
        if level>stage:
            stage=level;report({1:18,2:40,3:85}[level],{1:'正在理解完整描述…',2:'正在绘制画面…',3:'正在输出原生清晰图像…'}[level])
            last_report=time.monotonic()
        if time.monotonic()-last_report>=15:
            elapsed=int(time.monotonic()-start)
            report({0:8,1:18,2:40,3:85}[stage],{0:'正在加载模型',1:'正在理解人物描述',2:'正在绘制画面',3:'正在输出图片'}[stage]+f'，已用时{elapsed//60}分{elapsed%60:02d}秒')
            last_report=time.monotonic()
    def finish_image():
        if not output.is_file():raise RuntimeError('本地绘图未完成，日志：'+str(log_path))
        if cancelled():raise InterruptedError('绘制已停止。')
        from PIL import Image
        with Image.open(output) as im:im.verify()
        destination=pathlib.Path(target);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(output,destination)
        metadata=dict(engine=engine,requested_engine=requested_engine,
            reference_route='flux_reference' if engine!=requested_engine else 'none',
            model=spec['name'],runtime='stable-diffusion.cpp 3f8527a',quantization=spec['quantization'],
            model_file=spec['model'].name,text_encoder=spec['encoder'].name if 'encoder' in spec else 'CLIP-L + OpenCLIP-G (checkpoint)',max_vram_gib=spec['max_vram'],
            seed=seed,prompt=prompt,generation_prompt=generation_prompt,prompt_translation=translation,
            steps=spec['steps'],width=size[0],height=size[1],seconds=round(time.monotonic()-start,2),
            reference_count=len(references),review_status='pending',source_prompt_language='zh_or_user_original',run=str(folder))
        for key in ('encoder_sha256','encoder_source','encoder_revision','encoder_validation','model_sha256','model_source','model_revision'):
            if key in spec:metadata[key]=spec[key]
        (folder/'result.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
        # Successful copies no longer need duplicate binary inputs/output; keep small audit files.
        output.unlink()
        for ref in folder.glob('reference_*.png'):ref.unlink()
        return metadata
    # Share device-error handling and record success only after validated output is saved.
    thread_options = {'thread_limit': 1} if engine in ('sdxl', 'flux9') else {}
    return run_child(args,cancelled,log_path,on_tick=update_progress,timeout=spec['timeout'],
                     on_tick_interval=.25,on_success=finish_image,**thread_options)

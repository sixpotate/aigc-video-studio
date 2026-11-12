"""Offline Chinese text-to-image worker, isolated from the web server and TTS."""
import json
import os
import pathlib
import sys
import time
from settings import CHARACTER_MODEL, CHARACTER_CONFIG, WORKSPACE, POSE_MODEL
from portrait_spec import inspect_role, make_mask
from portrait_translation import translate_role
from portrait_prompt import compile_prompt
from portrait_encoding import encode_plan
from portrait_llm import translate_texts
from portrait_regions import apply_regions, supports_regions
from portrait_quality import pose_supported, pose_preset, standing_pose, clear_regions, face_crop, face_plan, blend_face, local_focus
from visual_styles import SOFT_PHOTO, SOFT_PHOTO_LEGACY_PROMPT

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'
os.environ['HF_HOME'] = str(WORKSPACE/'work/local_test/hf-cache')

STYLE_PROMPTS = {
    'anime': 'Japanese anime illustration, cel shading',
    'guoman': 'digital comic illustration, soft cel shading',
    '3d': '3D animated movie character, stylized, soft studio lighting',
    'realistic': 'portrait photography, natural light, realistic details',
    SOFT_PHOTO: SOFT_PHOTO_LEGACY_PROMPT,
}


def content_checked_image(output,content_info,enabled,stage):
    """Return an allowed image or stop before anything can be published."""
    flags=getattr(output,'nsfw_content_detected',None) or []
    flagged=any(bool(value) for value in flags)
    content_info['stages'].append(dict(stage=stage,checked=enabled,flagged=flagged))
    if flagged:
        content_info['flagged']=True
        raise ValueError('成人敏感内容检查已拦截本次图片，未保存或替换现有形象。可修改人物设定后重试。')
    return output.images[0]


def write_progress(path, payload):
    """Windows readers can briefly hold the progress file without delete sharing."""
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
    for attempt in range(40):
        try:
            temp.replace(path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(.025)


def translate_fields(role, check_cancelled=lambda:None):
    """Translate free-form Chinese locally; never send descriptions to a service."""
    return translate_role(role,lambda texts:translate_texts(texts,check_cancelled))


def encode_complete_prompt(pipe, prompt, negative):
    """Compatibility wrapper; the worker below uses separate weighted clauses."""
    return encode_plan(pipe,dict(segments=[dict(text=prompt,weight=1.0)],negative_prompt=negative))[0]


def main(job):
    from image_engine import selected
    if job.get('engine',selected())!='legacy' and job.get('mode','new')!='local':
        from portrait_native import main as native_main
        return native_main(job)
    progress_path = pathlib.Path(job['progress_path'])
    cancel_path = progress_path.with_suffix('.cancel')
    def check_cancelled():
        if cancel_path.exists():
            raise InterruptedError('人物绘制已停止，之前的形象仍保留。')
    def progress(percent, message, **extra):
        write_progress(progress_path, dict(progress=percent,message=message,**extra))

    try:
        progress(3, '正在本地理解人物描述…')
        import torch
        from diffusers import (StableDiffusionPipeline, StableDiffusionImg2ImgPipeline, StableDiffusionInpaintPipeline,
                               StableDiffusionControlNetPipeline, ControlNetModel, DPMSolverMultistepScheduler)
        from PIL import Image
        check_cancelled()
        if not torch.cuda.is_available():
            raise RuntimeError('没有检测到可用的NVIDIA显卡，请检查驱动。')
        torch.set_num_threads(4)
        role = job['role']
        errors = [i['message'] for i in inspect_role(role) if i['severity']=='error']
        if errors:
            raise ValueError(' '.join(errors))
        translation=translate_fields(job['role'],check_cancelled)
        description,outfit=translation['description'],translation['outfit']
        plan=compile_prompt(role,translation,STYLE_PROMPTS[role['style']])
        check_cancelled()
        progress(8, '正在加载本地绘图模型，首次加载可能较慢…')
        mode = job.get('mode', 'new')
        quality = job.get('quality','hd')
        content_check=job.get('content_check',False)
        hd = quality=='hd' and mode=='new'
        pose_enabled=job.get('pose_guide',True) and pose_supported(role,mode)
        quality_info=dict(requested=quality,base_size=[512,768],hd_refinement=False,
            pose_guidance=False,face_refinement=False,notes=[])
        content_info=dict(enabled=content_check,flagged=False,stages=[])
        if job.get('pose_guide',True) and not pose_supported(role,mode):
            quality_info['notes'].append('姿势参考支持全新绘制的全身正面站立（双臂自然下垂）或盘腿坐姿；本次姿势未匹配，使用文字或原图。')
        control_args={}
        if pose_enabled:
            if not (POSE_MODEL/'diffusion_pytorch_model.fp16.safetensors').is_file():
                raise ValueError('缺少本地站姿参考模型，请补齐模型或关闭“站姿参考”后重试。')
            control_args['controlnet']=ControlNetModel.from_pretrained(str(POSE_MODEL),variant='fp16',torch_dtype=torch.float16,local_files_only=True)
        pipeline_class = {'new':StableDiffusionPipeline, 'reference':StableDiffusionImg2ImgPipeline,
                          'local':StableDiffusionInpaintPipeline}[mode]
        if pose_enabled:pipeline_class=StableDiffusionControlNetPipeline
        safety_args=dict(safety_checker=None,feature_extractor=None,requires_safety_checker=False)
        if content_check:
            checker_path=CHARACTER_CONFIG/'safety_checker'
            extractor_path=CHARACTER_CONFIG/'feature_extractor'
            if not (checker_path/'model.safetensors').is_file() or not (extractor_path/'preprocessor_config.json').is_file():
                raise ValueError('本地成人敏感内容检查模型不完整，请关闭检查或补齐模型文件。')
            from diffusers.pipelines.stable_diffusion.safety_checker import StableDiffusionSafetyChecker
            from transformers import CLIPImageProcessor
            safety_args=dict(
                safety_checker=StableDiffusionSafetyChecker.from_pretrained(
                    str(checker_path),torch_dtype=torch.float16,local_files_only=True,use_safetensors=True),
                feature_extractor=CLIPImageProcessor.from_pretrained(str(extractor_path),local_files_only=True),
                requires_safety_checker=True,
            )
        pipe = pipeline_class.from_single_file(
            str(CHARACTER_MODEL/'dreamshaper_8.safetensors'), config=str(CHARACTER_CONFIG),
            torch_dtype=torch.float16, local_files_only=True, use_safetensors=True,
            **safety_args,
            **control_args,
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(pipe.scheduler.config, algorithm_type='dpmsolver++', use_karras_sigmas=True)
        pipe.enable_model_cpu_offload()
        pipe.enable_vae_tiling()
        check_cancelled()
        prompt,negative = plan['prompt'],plan['negative_prompt']
        steps = job.get('steps', 28)
        width, height = job.get('width',512), job.get('height',768)
        extra = {}
        reference = mask = focus = None
        effective_steps = steps
        if mode != 'new':
            with Image.open(job['reference']) as source:
                reference = source.convert('RGB')
            width, height = reference.size
            if width % 8 or height % 8 or width*height > 1024*1536 or max(width,height)>1536:
                raise ValueError('参考图片尺寸不支持，请先使用本工具生成标准角色图。')
            extra.update(image=reference, strength=job['strength'])
            effective_steps = max(1, int(steps * job['strength']))
            if mode == 'local':
                mask = make_mask(reference.size, job['strokes'])
                extra['mask_image'] = mask
                focus=local_focus(reference,mask,role,plan)
                if focus:
                    width=height=768
                    extra.update(image=reference.crop(focus['box']).resize((768,768),Image.Resampling.LANCZOS),
                                 mask_image=mask.crop(focus['box']).resize((768,768),Image.Resampling.NEAREST))
                    plan=focus['plan'];prompt,negative=plan['prompt'],plan['negative_prompt']
                    quality_info['local_refinement']=dict(area=focus['area'],box=list(focus['box']),working_size=[768,768])
        if mode != 'reference':
            extra.update(width=width, height=height)
        quality_info['base_size']=[width,height]
        if pose_enabled:
            preset=pose_preset(role,mode)
            extra.update(image=standing_pose((width,height),preset),controlnet_conditioning_scale=.85,control_guidance_end=.9)
            quality_info['pose_guidance']=True
            quality_info['pose_preset']=preset
        stage_end=48 if hd else 93
        def on_step(_pipe, step, _timestep, callback_kwargs):
            check_cancelled()
            progress(min(stage_end,15 + round((stage_end-15)*(step+1)/effective_steps)), f'正在绘制人物 · {step+1}/{effective_steps}')
            return callback_kwargs
        progress(12, '模型已加载，正在理解人物描述…')
        started = time.monotonic()
        (positive_embeds,negative_embeds),encoding=encode_plan(pipe,plan)
        token_regions=encoding.pop('token_regions')
        # A seated spatial layout requires the matching skeleton. Without it,
        # textual poses may land elsewhere and a regional mask would mislead.
        region_enabled=pose_enabled or supports_regions(role,mode)
        encoding['regional_guidance']=region_enabled and apply_regions(pipe,token_regions,role,mode,width,height)
        result = pipe(prompt_embeds=positive_embeds,negative_prompt_embeds=negative_embeds,
            **extra, num_inference_steps=steps, guidance_scale=7.5,
            generator=torch.Generator('cpu').manual_seed(job['seed']), callback_on_step_end=on_step)
        image=content_checked_image(result,content_info,content_check,'base')
        if hd:
            check_cancelled()
            progress(50,'正在生成高清细节 · 1024×1536…')
            clear_regions(pipe)
            pipe.remove_all_hooks()
            # Share the existing diffusion weights; do not load a second model.
            components={key:value for key,value in pipe.components.items() if key!='controlnet'}
            refine=StableDiffusionImg2ImgPipeline(**components,requires_safety_checker=content_check)
            if pose_enabled:
                pipe.controlnet.to('cpu')
                control_args.clear()
            del result,pipe
            torch.cuda.empty_cache()
            refine.enable_model_cpu_offload();refine.enable_vae_tiling()
            if region_enabled:apply_regions(refine,token_regions,role,mode,1024,1536)
            def on_hd(_pipe,step,_timestep,values):
                check_cancelled();progress(min(83,52+round(31*(step+1)/12)),f'正在细化高清画面 · {step+1}/12')
                return values
            hd_result=refine(image=image.resize((1024,1536),Image.Resampling.LANCZOS),strength=.30,
                prompt_embeds=positive_embeds,negative_prompt_embeds=negative_embeds,num_inference_steps=40,guidance_scale=6.5,
                generator=torch.Generator('cpu').manual_seed((job['seed']+1)%2**31),callback_on_step_end=on_hd)
            image=content_checked_image(hd_result,content_info,content_check,'hd')
            quality_info['hd_refinement']=True
            quality_info['hd_size']=[1024,1536]
            quality_info['hd_strength']=.30
            clear_regions(refine)
            check_cancelled()
            if job.get('face_refine',True):
                crop=face_crop(image,role.get('framing','half'))
                if crop:
                    progress(85,'正在单独细化面部与眼睛…')
                    (face_positive,face_negative),face_encoding=encode_plan(refine,face_plan(plan))
                    def on_face(_pipe,step,_timestep,values):
                        check_cancelled();progress(min(97,85+round(12*(step+1)/12)),f'正在细化面部 · {step+1}/12')
                        return values
                    face_result=refine(image=image.crop(crop['box']).resize((512,512),Image.Resampling.LANCZOS),
                        prompt_embeds=face_positive,negative_prompt_embeds=face_negative,strength=.30,
                        num_inference_steps=40,guidance_scale=6.0,generator=torch.Generator('cpu').manual_seed((job['seed']+2)%2**31),
                        callback_on_step_end=on_face)
                    detailed=content_checked_image(face_result,content_info,content_check,'face')
                    image=blend_face(image,detailed,crop)
                    quality_info.update(face_refinement=True,face_box=list(crop['box']),face_strength=.30)
                else:
                    quality_info['notes'].append('未可靠检测到单张正面人脸，本次跳过面部细化。')
            else:quality_info['notes'].append('面部细化已关闭。')
        elif quality=='hd' and mode!='new':
            quality_info['notes'].append('参考修改与局部修改保留原图尺寸；高清细化仅用于全新绘制。')
        if mask is not None:
            # The VAE can alter unmasked pixels; restore them exactly from the original.
            from PIL import Image, ImageFilter
            if focus:
                box=focus['box'];patch=image.resize((box[2]-box[0],box[3]-box[1]),Image.Resampling.LANCZOS)
                image=reference.copy();image.paste(patch,box[:2])
            softened = mask.filter(ImageFilter.GaussianBlur(2))
            inside_only = Image.composite(softened, Image.new('L',mask.size,0), mask)
            image = Image.composite(image, reference, inside_only)
        check_cancelled()
        target=pathlib.Path(job['target'])
        image.save(target)
        metadata=dict(seed=job['seed'],prompt=prompt,negative_prompt=negative,description=role['description'],translated_description=description,translated_outfit=outfit,width=image.width,height=image.height,
            translation=translation,plan=plan,encoding=encoding,quality=quality_info,
            content_check=content_info,review_status='pending',
            framing=role.get('framing','half'),look=role.get('look',{}),mode=mode,strength=job.get('strength'),reference=job.get('reference_image'),strokes=job.get('strokes'),
            model='DreamShaper 8',seconds=round(time.monotonic()-started,2),peak_vram_mb=round(torch.cuda.max_memory_allocated()/2**20))
        target.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
        progress(100, '图片已保存，请对照设定核对人物细节。', result=metadata)
        print(json.dumps(metadata,ensure_ascii=False),flush=True)
    except Exception as exc:
        message=str(exc)
        if 'out of memory' in message.lower():
            message='显存不足。请关闭其他使用显卡的软件后重试。'
        progress(0, message, error=True)
        raise


if __name__=='__main__':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    main(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')))

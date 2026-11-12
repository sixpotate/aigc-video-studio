"""Native instruction-following portrait path, without SD1.5 prompt/pose patches."""
import json,pathlib
from image_engine import generate,role_prompt,selected

def main(job):
    from portrait_worker import write_progress
    progress=pathlib.Path(job['progress_path']);target=pathlib.Path(job['target'])
    def report(value,message,**extra):write_progress(progress,dict(progress=value,message=message,**extra))
    try:
        prompt=role_prompt(job['role']);references=[]
        if job.get('mode')=='reference':
            references=[job['reference']]
            correction=job.get('edit_instruction','').strip()
            prompt=('保持参考人物的身份、脸部、发型、服装和背景，仅按下列要求修改：\n'+correction if correction else
                    '保持参考图中人物的身份，根据下面的完整设定调整画面：\n'+prompt)
        temporary=target.with_suffix('.pending.png')
        metadata=generate(prompt,temporary,job['seed'],references,engine=job.get('engine') or selected(),
            reference_engine=job.get('reference_engine'),report=report,cancelled=progress.with_suffix('.cancel').exists)
        # Honor the existing optional post-generation checker; do not alter its settings.
        if job.get('content_check'):
            import torch,numpy as np
            from PIL import Image
            from settings import CHARACTER_CONFIG
            from diffusers.pipelines.stable_diffusion.safety_checker import StableDiffusionSafetyChecker
            from transformers import CLIPImageProcessor
            checker=StableDiffusionSafetyChecker.from_pretrained(str(CHARACTER_CONFIG/'safety_checker'),local_files_only=True)
            processor=CLIPImageProcessor.from_pretrained(str(CHARACTER_CONFIG/'feature_extractor'),local_files_only=True)
            with Image.open(temporary) as im:
                image=im.convert('RGB');features=processor(images=image,return_tensors='pt').pixel_values
                with torch.no_grad():_,flags=checker(images=np.asarray(image)[None]/255.,clip_input=features)
            if any(flags):raise ValueError('图片检查未通过，原有形象保留。')
        metadata.update(plan=dict(version='native-v2',prompt=metadata.get('generation_prompt',prompt),
                original_prompt=prompt,priorities=[],warnings=[]),
            quality=dict(base_size=[metadata['width'],metadata['height']],native=True,hd_refinement=False,pose_guidance=False,face_refinement=False,
                         notes=['直接生成原生画面，未二次重画面部。']),
            content_check=dict(enabled=bool(job.get('content_check')),flagged=False),mode=job.get('mode','new'))
        if progress.with_suffix('.cancel').exists():raise InterruptedError('绘制已停止。')
        target.with_suffix('.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),'utf-8')
        temporary.replace(target)
        report(100,'图片已保存，请核对人物和细节。',result=metadata)
    except Exception as exc:
        target.with_suffix('.pending.png').unlink(missing_ok=True)
        report(0,str(exc),error=True);raise

"""Produce a complete line from independently checked, forward-moving takes."""
import json
import hashlib
import math
import pathlib
from PIL import Image,ImageOps
from settings import APP_DIR,WORKSPACE,PYTHON
from director_schema import digest,cast_members,CAMERAS,MOTION_ROOT,MOTION_PYTHON
from director_plan import coverage_plan,profile_for
from director_reference import prepare_reference,reference_key,motion_prompt,action_sources,actor_region,valid_reference,speaker_closeup_shot
from director_production import needs_lip_sync,motion_source
from director_motion import fit_command,video_size
from director_review import review,corrections,QualityRejected

def file_hash(path):
    with pathlib.Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def valid_encoder_cache(path):
    """Reject the empty/small files left when an encoder process is interrupted."""
    try:return path.is_file() and path.stat().st_size>=1024
    except OSError:return False

def preflight_cached_motion(profile, plan, sample=None):
    """Recheck immediately before the measured Wan 2.1 motion profile.

    Values are based on a completed 384x672, 49-frame local run; they do
    not establish safety for different profiles or replace live monitoring.
    """
    if not (profile.get('id')=='wan21_distill' and profile.get('width')==384
            and profile.get('height')==672 and plan.get('frames')==49):
        return
    if sample is None:
        from runtime_health import snapshot
        sample=snapshot(gpu=True)
    if sample.get('telemetry_errors') or any(sample.get(k) is None for k in
            ('available_ram_mib','commit_available_mib','gpu_total_mib','gpu_used_mib','gpu_temperature')):
        raise RuntimeError('动作生成前无法读取完整的内存或显卡状态，已保留素材。')
    if not all(isinstance(sample[k],(int,float)) and math.isfinite(sample[k]) for k in
            ('available_ram_mib','commit_available_mib','gpu_total_mib','gpu_used_mib','gpu_temperature')):
        raise RuntimeError('动作生成前资源状态无效，已保留素材。')
    if (sample['available_ram_mib'] < 15701*1.25 or sample['commit_available_mib'] < 18*1024
            or sample['gpu_total_mib']-sample['gpu_used_mib'] < 5815*1.1+512
            or sample['gpu_temperature'] >= 85):
        raise RuntimeError('动作生成前内存、提交余量或显卡余量不足，已保留素材。')

def calibrate_visual_review(result):
    """Treat uncalibrated vision-model opinions as review warnings, not proof.

    Retain the model's original assessment and all evidence; deterministic
    all-black video detection and unavailable inspection remain blocking.
    """
    if result.get('status') != 'rejected' or result.get('metrics', {}).get('all_black'):
        return result
    return {**result, 'status':'warning', 'model_status':'rejected',
        'review_policy':'视觉模型可能误判；此镜须人工复看，原检查意见已保留。'}

def compact_review_warnings(reviews,limit=8):
    """Deduplicate repeated take/reference warnings while keeping an audit count."""
    unique=[];seen=set()
    for result in reviews:
        for issue in result.get('issues',[]):
            key=(issue.get('code'),issue.get('severity'),
                 ' '.join(str(issue.get('evidence','')).split()).casefold(),
                 ' '.join(str(issue.get('correction','')).split()).casefold())
            if key in seen:continue
            seen.add(key);unique.append(issue)
    return unique[:limit],len(unique)

def cached_review(shot,candidate,work,cancelled,video=False,reference=None):
    from director_schema import reference_path
    identity=digest(dict(candidate=file_hash(candidate),
        reference=file_hash(reference) if reference else None,
        actors=[] if shot.get('visual_only') else [file_hash(reference_path(m['role'])) for m in cast_members(shot)],
        expected={k:shot.get(k) for k in ('action','visual_context','start_state','visual_only','role_ids','scene_description')},video=video,version=4))
    folder=work/'quality'/identity;result_path=folder/'画面检查.json'
    try:result=json.loads(result_path.read_text('utf-8'))
    except (OSError,ValueError):result=review(shot,candidate,folder,cancelled,video,reference)
    return calibrate_visual_review(result)

def require_review(result):
    if result['status']=='rejected':raise QualityRejected('自动复检仍发现问题：'+corrections(result))
    if result['status']=='unavailable':raise QualityRejected(result['note'])

def checked_reference(shot,reference,settings,folder,work,run,report,cancelled):
    candidate=reference
    for attempt in range(2):
        report('quality','正在检查人物、服装和画面…')
        result=cached_review(shot,candidate,work,cancelled)
        if result['status']!='rejected':require_review(result);return candidate,result
        if attempt:require_review(result)
        correction={**shot,'seed':(shot['seed']+7919)%2147483647,'quality_correction':corrections(result)}
        from image_engine import ready as image_ready
        if image_ready():correction['reference_layout']='generated'
        candidate=folder/(reference_key(correction,settings)+'.png')
        if not valid_reference(candidate):
            report('reference','发现明确画面问题，正在自动修正一次…')
            prepare_reference(correction,candidate,settings,cancelled=cancelled,require_speaker_face=needs_lip_sync(shot))
    raise AssertionError('unreachable')

def generate_take(shot,reference,plan,profile,folder,work,run,report,cancelled,translations=None):
    from portrait_llm import translate_texts
    sources=action_sources(shot)
    if translations is None:
        # Continuation coverage can need a fresh translation after a generated
        # close-up. Report that stage before starting the local model so a
        # startup failure is not incorrectly classified as reference creation.
        report('translation','正在本地理解当前画面的动作…')
        values=translate_texts(sources,check_cancelled=lambda:check_cancel(cancelled))
    else:
        values=translations
    prompt=motion_prompt(shot,values,CAMERAS[shot['camera']])
    width,height=profile['width'],profile['height']
    native_input=work/(digest(dict(image=file_hash(reference),width=width,height=height))+'.input.png')
    if not native_input.is_file():
        with Image.open(reference) as im:ImageOps.fit(im.convert('RGB'),(width,height),Image.Resampling.LANCZOS).save(native_input)
    for attempt in range(2):
        check_cancel(cancelled)
        seed=(shot['seed']+attempt*104729)%2147483647
        key=digest(dict(image=file_hash(native_input),prompt=prompt,frames=plan['frames'],seed=seed,profile=profile,version=2))
        name='director_'+key[:32];motion=WORKSPACE/'outputs/motion_test'/(name+'.mp4')
        benchmark=motion.with_name(motion.stem+'_benchmark.json')
        prompt_path=work/(name+'.txt');prompt_path.write_text(prompt,'utf-8')
        if not (motion.is_file() and benchmark.is_file()):
            script=APP_DIR/'motion_runtime.py' if profile['id']=='wan22_5b' else MOTION_ROOT/'run_motion.py'
            args=[MOTION_PYTHON,'-u',script,'--name',name,'--height',height,'--width',width,
                  '--frames',plan['frames'],'--seed',seed,'--image',native_input,'--prompt-file',prompt_path]
            if profile['id']=='wan22_5b':args += ['--steps',profile['steps']]
            cached=(MOTION_ROOT/'quality_runs'/name/'encoders.pt') if profile['id']=='wan22_5b' else (MOTION_ROOT/(name+'_encoders.pt'))
            if cached.exists() and not valid_encoder_cache(cached):
                raise RuntimeError('动作编码缓存不完整；已停止并保留原文件，请检查后再重试。')
            if not cached.exists():
                preflight_cached_motion(profile,plan)
                report('motion','正在理解画面与动作…');run(args+['--encode-only'])
            preflight_cached_motion(profile,plan)
            report('motion',f'正在用{profile["model"]}生成连续动作…');run(args+['--cached'])
        report('quality','正在检查动作、人物变化与画面稳定性…')
        inspection=cached_review(shot,motion,folder,cancelled,True,reference)
        if inspection['status']!='rejected':
            require_review(inspection)
            return motion,key,inspection,prompt
        if attempt:require_review(inspection)
        prompt+=' Fix these visible defects while keeping the intended action: '+translate_texts([corrections(inspection)],check_cancelled=lambda:check_cancel(cancelled))[0]
        report('motion','动作检查发现明显问题，正在自动重做一次…')
    raise AssertionError('unreachable')

def check_cancel(cancelled):
    if cancelled():raise InterruptedError('已停止，已完成的镜头片段已保留。')


def tracking_closeup_needed(shot,entry):
    prior=(shot.get('result') or {}).get('error') or {}
    message=str(prior.get('message',''))
    return entry.get('tracking_recovery')=='speaker_closeups_v1' or entry.get('preflight',{}).get('speaker_closeup') is True or (
        prior.get('stage')=='lips' and any(term in message for term in ('无法稳定识别当前说话人的脸','人脸太小')))

def force_tracking_closeup(tracking_retry,take):
    """Keep every speaking coverage segment trackable after a prior lip failure.

    Continuation frames can drift or shrink the face even when the first segment
    uses a stable close-up, so a historical tracking retry must not fall back to
    the previous segment's last frame for another speaking segment.
    """
    return bool(tracking_retry and needs_lip_sync(take))


def stable_speaker_reference(take,original_seed):
    """Use one portrait per speaker; leave each take's motion seed untouched."""
    return {**take,'seed':(int(original_seed)+3571)%2147483647}


def matching_translations(index,auto_closeup,translations):
    """Never reuse multi-character directions for a rewritten close-up."""
    return translations if index==0 and not auto_closeup else None


def render_shot(shot,project,reference,audio,folder,work,entry,run,task,report,checkpoint,cancelled,translations=None):
    profile=shot.get('production_profile') or profile_for(shot,project['export']['ratio'])
    width,height=profile['width'],profile['height']
    acting=motion_source(shot,project)
    base={**shot,**{k:acting[k] for k in ('action','actor_actions','camera','seed','cast') if k in acting}}
    plans=coverage_plan(base,audio,profile);parts=[];records=[];previous=None
    entry.update(planned_native_size=[width,height],native_sizes=[],model=profile['model'],coverage_count=len(plans))
    tracking_retry=tracking_closeup_needed(shot,entry)
    for plan in plans:
        check_cancel(cancelled);take=plan['shot'];index=plan['index']
        forced_closeup=force_tracking_closeup(tracking_retry,take)
        auto_closeup=forced_closeup or (index==0 and entry.get('preflight',{}).get('speaker_closeup'))
        if forced_closeup:
            take=speaker_closeup_shot(take)
            # Every segment begins from its verified reference frame. The same
            # forward-only wording keeps the actor and props consistent.
            take['continuation']=True
            entry['tracking_recovery']='speaker_closeups_v1'
        elif index==0 and entry.get('preflight',{}).get('speaker_closeup'):
            take=speaker_closeup_shot(take)
        def tell(stage,message):report(stage,f'画面 {index+1}/{len(plans)} · '+message)
        still=take.get('visual_only',False) and not take.get('animate_scene',False)
        if forced_closeup:
            accepted=entry.get('preflight',{})
            same_reference=str(entry.get('reference','')).rsplit('/',1)[-1]==reference.name
            if accepted.get('speaker_closeup') and accepted.get('reference_adjusted') and same_reference and valid_reference(reference):
                # The reference worker already validated this speaker's
                # independent image. Preserve it across all speaking takes.
                start=reference
            else:
                ref_take=stable_speaker_reference(take,base['seed'])
                start=folder/(reference_key(ref_take,project['export'])+'.png')
                if not valid_reference(start):
                    tell('reference','正在修复说话人追踪，准备稳定的对白近景…')
                    prepare_reference(ref_take,start,project['export'],cancelled=cancelled,require_speaker_face=True)
        elif index==0:start=reference
        elif plan['mode']=='continuation' and previous:
            start=folder/(digest(dict(previous=previous.name,version=1))+'.last.png')
            if not valid_reference(start):
                run(['ffmpeg','-y','-v','error','-sseof','-1','-i',previous,'-vf','reverse','-frames:v','1',start])
                if not valid_reference(start):raise RuntimeError('无法提取上一段视频的末帧，已保留原视频。')
        else:
            start=folder/(reference_key(take,project['export'])+'.png')
            if not valid_reference(start):
                tell('reference','正在安排反应或对话机位…')
                prepare_reference(take,start,project['export'],cancelled=cancelled,require_speaker_face=needs_lip_sync(take))
        # Continuations must remain the last actual frame; regenerating them would break physical continuity.
        if plan['mode']=='continuation' and previous:
            ref_check=cached_review(take,start,folder,cancelled);require_review(ref_check)
        else:start,ref_check=checked_reference(take,start,project['export'],folder,folder,run,tell,cancelled)
        face=None
        if needs_lip_sync(take):
            from face_motion import check_reference
            def locate_face():return check_reference(dict(image=str(start),size=(width,height),face_box=take.get('face_box'),actor_region=actor_region(take)))
            try:face=locate_face()
            except ValueError:
                if profile['kind'] in ('action','effects'):
                    take['lip_sync']=False
                    entry['lip_sync_note']='动作镜头嘴部未清晰入画，保留完整动作与配音；不强行放大脸部。'
                else:
                    tell('preflight','正在自动调整说话人的取景…')
                    adjusted=speaker_closeup_shot(take)
                    start=folder/(reference_key(adjusted,project['export'])+'.png')
                    if not valid_reference(start):prepare_reference(adjusted,start,project['export'],cancelled=cancelled,require_speaker_face=True)
                    ref_check=cached_review(adjusted,start,folder,cancelled);require_review(ref_check)
                    take=adjusted
                    auto_closeup=True
                    face=locate_face()
                    if index==0:
                        entry['preflight']={**face,'reference_adjusted':True,'speaker_closeup':True}
        if auto_closeup and face and not take.get('face_box'):
            from director_closeup import ensure_closeup
            original=start
            start,face,reframed=ensure_closeup(start,folder,face,(width,height))
            if reframed:
                tell('preflight','对白近景的人脸偏小，正在保留原图并调整取景…')
                ref_check=cached_review(take,start,folder,cancelled);require_review(ref_check)
                entry['speaker_reframe']={'source':original.name,'reference':start.name,
                    'note':'原始画面经裁切放大，人物细节可能较柔和。'}
        if index==0 and auto_closeup and face:
            entry['preflight']={**face,'reference_adjusted':True,'speaker_closeup':True}
        if index==0:entry.update(reference=f'/director-media/{project["id"]}/{start.name}',reference_quality=ref_check);checkpoint()
        if still:
            motion=start;motion_key=digest(dict(image=start.name,seconds=plan['seconds'],version=2))
            inspection=ref_check;prompt='固定场景的轻微运镜'
        else:
            motion,motion_key,inspection,prompt=generate_take(take,start,plan,profile,folder,work,run,tell,cancelled,matching_translations(index,auto_closeup,translations))
            previous=motion
        actual_size=[width,height] if still else list(video_size(motion))
        if parts and actual_size!=entry['native_sizes'][0]:
            raise ValueError('同一句的连续画面尺寸不一致，已保留片段，请重新生成这一镜。')
        entry.update(native_width=actual_size[0],native_height=actual_size[1],native_sizes=[actual_size])
        fitted=folder/(digest(dict(motion=motion_key,seconds=plan['seconds'],fit_version=2))+'.fit.mp4')
        if not fitted.is_file():
            temporary=work/(motion_key+'.fit.mp4');run(fit_command(motion,temporary,plan['seconds'],still,width,height));temporary.replace(fitted)
        current=fitted
        speech_start=max(0.,audio['speech_start']-plan['start'])
        speech_end=min(plan['seconds'],audio['speech_start']+audio['speech_seconds']-plan['start'])
        if needs_lip_sync(take) and speech_end>speech_start:
            anime=take.get('lip_mode')=='anime' or (take.get('lip_mode','auto')=='auto' and take['role'].get('style')=='anime')
            lipkey=digest(dict(motion=motion_key,audio=audio['audio'],start=plan['start'],seconds=plan['seconds'],
                face=take.get('face_box'),speaker=take.get('speaker_id'),anime=anime,version=5))
            current=folder/(lipkey+'.lips.mp4')
            if not current.is_file():
                tell('lips','正在对齐这一段对白口型…')
                wave=work/(lipkey+'.wav')
                run(['ffmpeg','-y','-v','error','-ss',plan['start'],'-i',folder/audio['audio'],'-t',plan['seconds'],'-ar','24000','-ac','1',wave])
                temp=work/(lipkey+'.mp4');box=face['face_box']
                hint=[v/d*100 for v,d in zip(box,(width,height,width,height))]
                task(lipkey,dict(video=str(fitted),audio=str(wave),output=str(temp),speech_start=speech_start,
                    speech_seconds=speech_end-speech_start,track_speech_only=not anime,face_box=take.get('face_box'),
                    face_hint=hint,actor_region=actor_region(take)),'native_lip_worker.py' if anime else 'sync_character.py')
                temp.replace(current)
            tell('quality','正在复检口型处理后的画面…')
            inspection=cached_review(take,current,folder,cancelled,True,start);require_review(inspection)
        parts.append(current)
        records.append(dict(index=index,start=plan['start'],seconds=plan['seconds'],mode=plan['mode'],
            cut_basis=plan['cut_basis'],model=profile['model'],native_size=actual_size,motion_key=motion_key,prompt=prompt,quality=inspection,reference_quality=ref_check))
        entry['takes']=records;checkpoint()
    key=digest(dict(parts=[p.name for p in parts],seconds=audio['seconds'],version=2))
    combined=folder/(key+'.coverage.mp4')
    if not combined.is_file():
        listing=work/(key+'.txt');listing.write_text(''.join("file '"+p.as_posix().replace("'","'\\''")+"'\n" for p in parts),'utf-8')
        temp=work/(key+'.mp4')
        run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',listing,'-an','-c:v','copy','-movflags','+faststart',temp]);temp.replace(combined)
    reviews=[result for record in records for result in (record['quality'],record['reference_quality'])]
    warnings,total_warnings=compact_review_warnings(reviews)
    needs_review=bool(warnings) or any(result.get('status')!='passed' for result in reviews)
    entry['quality']=dict(status='warning' if needs_review else 'passed',issues=warnings,checked_takes=len(records),retry_limit_per_stage=1,
        issue_count_total=total_warnings,issues_truncated=total_warnings>len(warnings),
        review_policy='视觉模型意见需人工复核；视频解码与音画检查仍然执行。')
    entry['timing']=dict(method='forward_coverage',audio_unchanged=True,seconds=audio['seconds'],takes=len(parts),reverse_loop=False,
        cut_offsets=[p['start'] for p in plans[1:]],pause_aligned_cuts=sum(p['cut_basis']=='speech_pause' for p in plans))
    checkpoint()
    return combined


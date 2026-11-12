"""Serial offline workflow: cast -> audition -> referenced motion -> lips -> export."""
import json, pathlib, sys, shutil, time, subprocess
from settings import APP_DIR, WORKSPACE, PYTHON, VIDEO_DIR
from director_schema import DIRECTOR_DIR, digest, render_key, export_settings, output_size, NATIVE_SIZES
from director_reference import prepare_reference, reference_key, actor_region, action_sources,valid_reference,speaker_closeup_shot
from director_export import subtitles, encode_command, validate_clip
from process_control import run_child
from production_errors import IncompleteProduction,SharedRuntimeFailure,STAGES,failure,fatal_error
from worker import safe_name
from director_production import motion_source,sound_settings,speaker_mouth_covered,needs_lip_sync
from director_render import render_shot
from director_plan import quality_summary
from director_sound import assemble
from progress_writer import write_progress, atomic_json


def write_json(path, data):
    atomic_json(path, data)


def translate(job):
    result={};missing=[];cache=WORKSPACE/'work/director_prompt_cache';cache.mkdir(exist_ok=True)
    sources=list(dict.fromkeys(source for shot in job['shots'] for source in action_sources(shot) if source))
    for source in sources:
        path=cache/(digest(source)+'.json')
        try:
            entry=json.loads(path.read_text(encoding='utf-8'))
            if entry['source']!=source:raise ValueError()
            result[source]=entry['translation']
        except (OSError,ValueError,KeyError):missing.append(source)
    if missing:
        from portrait_llm import translate_texts
        options={'allow_partial':True} if job.get('isolate_errors') else {}
        for source,translated in zip(missing,translate_texts(missing,**options)):
            if not isinstance(translated,str) or not translated.strip():continue
            result[source]=translated
            write_json(cache/(digest(source)+'.json'),dict(source=source,translation=translated))
    write_json(pathlib.Path(job['result']),{shot['id']:[result.get(s,'') for s in action_sources(shot)] for shot in job['shots']})


def main(job):
    progress=pathlib.Path(job['progress']);cancel=progress.with_suffix('.cancel')
    work=pathlib.Path(job['work']);work.mkdir(parents=True,exist_ok=True)
    project=job['project'];project.setdefault('sound',sound_settings())
    folder=DIRECTOR_DIR/project['id'];folder.mkdir(parents=True,exist_ok=True)
    settings=export_settings(project.get('export'));width,height=output_size(settings)
    native_width,native_height=NATIVE_SIZES[settings['ratio']]
    result={'shots':{},'final':None};result_path=work/'result.json';log=work/'worker.log'
    selected=[s for s in project['shots'] if job['mode'] in ('all','assemble','voices') or s['id']==job.get('shot_id')]
    numbers={s['id']:i+1 for i,s in enumerate(project['shots'])}
    last_report={};stage='reference';current_shot=None
    def report(p,message,**details):
        last_report.clear();last_report.update(progress=p,message=message,**details);write_progress(progress,last_report)
    def check_cancel():
        if cancel.exists():raise InterruptedError('已停止，已完成的素材和镜头已保留。')
    def run(command,detail_progress=None):
        started=time.monotonic();message=last_report.get('message','正在计算…')
        def tick():
            elapsed=int(time.monotonic()-started)
            detail={}
            if detail_progress:
                try:detail=json.loads(detail_progress.read_text('utf-8'))
                except (OSError,ValueError):pass
            current_message=detail.get('message') or message+f'（本步骤已用时 {elapsed//60}分{elapsed%60:02d}秒）'
            report(last_report.get('progress',0),current_message,
                   shot_id=current_shot['id'] if current_shot else None,elapsed_seconds=elapsed)
        run_child(command,cancel.exists,log,on_tick=tick if 'voice_worker.py' not in [pathlib.Path(str(x)).name for x in command] else None)
    def task(name,payload,script):
        detail=work/(name+'.progress.json') if script=='super_resolution.py' else None
        if detail:
            payload={**payload,'progress_path':str(detail)}
            write_json(detail,dict(message='正在接回已完成的清晰度片段…'))
        path=work/(name+'.json');write_json(path,payload);run([PYTHON,'-u',APP_DIR/script,path],detail)
    def checkpoint():write_json(result_path,result)
    def mark_failed(shot,failed_stage,exc):
        if isinstance(exc,InterruptedError):raise exc
        item=result['shots'][shot['id']]
        item.update(status='failed',error=failure(failed_stage,exc),video=None)
        checkpoint()
        if fatal_error(exc):raise exc
    def unfinished():
        return [s for s in selected if result['shots'][s['id']].get('status') not in ('completed','failed')]
    def finish_partial():
        failed=[s for s in selected if result['shots'][s['id']].get('status')=='failed']
        if not failed:return
        done=sum(result['shots'][s['id']].get('status')=='completed' for s in selected)
        indices='、'.join(str(numbers[s['id']]) for s in failed[:12])
        if len(failed)>12:indices+='等'
        message=f'本次已完成 {done}/{len(selected)} 个镜头；第 {indices} 镜待处理。已保留完成内容，可重试未完成镜头。'
        result['partial']=True;checkpoint()
        report(round(95*done/max(1,len(selected))),message,partial=True,failed_shots=[s['id'] for s in failed])
        raise IncompleteProduction(message)
    def finalise(clips,slots):
        report(96,'正在分批合成镜头，并加入配乐、音效和人声避让…')
        from sound_library import mix_identity
        name=digest(dict(shots=[render_key(s,settings,project.get('captions')) for s in selected],title=project['title'],export=settings,sound=project['sound'],effects=[mix_identity(s) for s in selected],assembly_version=2))+'.mp4'
        target=folder/name;temp=folder/(name+'.partial.mp4')
        assemble(project,clips,slots,temp,work,run);validate_clip(temp,sum(slots),settings);temp.replace(target)
        VIDEO_DIR.mkdir(exist_ok=True);exported=VIDEO_DIR/(time.strftime('%Y%m%d_%H%M%S')+'_自定义_'+safe_name(project['title'])+'.mp4');shutil.copy2(target,exported)
        summary=quality_summary([{**s,'result':result['shots'][s['id']]} for s in selected])
        sizes=summary['native_sizes'];native=sizes[0] if len(sizes)==1 else [None,None]
        result['final']=dict(url=f'/director-media/{project["id"]}/{name}',path=str(exported),seconds=sum(slots),width=width,height=height,
            native_width=native[0],native_height=native[1],resize_method='Real-ESRGAN + Lanczos' if summary['ai_upscaled'] else 'Lanczos',
            quality=summary,sound=project['sound']);checkpoint()
    for shot in selected:
        key=render_key(shot,settings,project.get('captions'));prior=shot.get('result',{})
        entry=dict(prior) if prior.get('signature')==key else {}
        entry.update(signature=key,error=None,status='pending')
        result['shots'][shot['id']]=entry
    try:
        # Completed, validated clips bypass image, voice and motion models entirely.
        if job['mode'] in ('all','shot','assemble'):
            for shot in selected:
                check_cancel();entry=result['shots'][shot['id']]
                clip=folder/(entry['signature']+'.mp4')
                if clip.is_file() and entry.get('seconds'):
                    try:
                        entry['validation']=validate_clip(clip,entry['seconds'],settings)
                        entry.update(video=f'/director-media/{project["id"]}/{clip.name}',status='completed')
                    except (ValueError,subprocess.TimeoutExpired):
                        entry['video']=None
                else:entry['video']=None
            checkpoint()
        if job['mode']=='assemble':
            stage='assembly'
            if unfinished():raise ValueError('仍有镜头未完成或未通过音画检查，不能省略这些镜头合成整集。')
            finalise([folder/(result['shots'][s['id']]['signature']+'.mp4') for s in selected],
                     [result['shots'][s['id']]['seconds'] for s in selected])
            report(100,'音乐与音效已重新合成，人物动作和口型未重做。');return
        references={}
        # Keep failures local to their shot; cancellation and runtime failures propagate.
        if job['mode'] not in ('audio','voices'):
            for shot in unfinished():
                current_shot=shot;stage='reference';check_cancel();entry=result['shots'][shot['id']]
                profile=shot.get('production_profile',{})
                native_width=profile.get('width',NATIVE_SIZES[settings['ratio']][0]);native_height=profile.get('height',NATIVE_SIZES[settings['ratio']][1])
                try:
                    acting=motion_source(shot,project);reference=folder/(reference_key(acting,settings)+'.png')
                    adjusted_reference=False
                    if entry.get('preflight',{}).get('reference_adjusted'):
                        name=str(entry.get('reference','')).rsplit('/',1)[-1]
                        if len(name)==68 and name.endswith('.png') and all(c in '0123456789abcdef' for c in name[:-4]):
                            corrected=folder/name
                            if valid_reference(corrected):reference=corrected;adjusted_reference=True
                    elif (shot.get('result',{}).get('error') or {}).get('stage')=='preflight' and entry.get('reference'):
                        # The last ensemble frame is still useful when only
                        # speaker tracking failed. Reuse it without overwriting
                        # it; the bounded fallback below creates a separate crop.
                        name=str(entry['reference']).rsplit('/',1)[-1]
                        if len(name)==68 and name.endswith('.png') and all(c in '0123456789abcdef' for c in name[:-4]):
                            previous=folder/name
                            if valid_reference(previous):reference=previous
                    if not reference.is_file() or not valid_reference(reference):
                        report(2,f'第 {numbers[shot["id"]]} 镜 · 正在准备参考画面…',shot_id=shot['id'])
                        prepare_reference(acting,reference,settings,cancelled=cancel.exists)
                    if not valid_reference(reference):raise ValueError('参考画面未保存完整，可以只重试这个镜头。')
                    entry['reference']=f'/director-media/{project["id"]}/{reference.name}';checkpoint()
                    if job['mode']=='reference':
                        stage='preflight'
                        if needs_lip_sync(shot):
                            from face_motion import check_reference
                            previous_preflight=entry.get('preflight',{})
                            saved_closeup=bool(adjusted_reference and previous_preflight.get('speaker_closeup'))
                            spec=dict(image=str(reference),size=(native_width,native_height),face_box=shot.get('face_box'),actor_region=None if saved_closeup else actor_region(shot))
                            try:
                                entry['preflight']=check_reference(spec)
                                if adjusted_reference:entry['preflight']['reference_adjusted']=True
                                if saved_closeup:
                                    entry['preflight']['speaker_closeup']=True
                                    if previous_preflight.get('ensemble_reference'):
                                        entry['preflight']['ensemble_reference']=previous_preflight['ensemble_reference']
                            except ValueError:
                                # One bounded attempt, kept separate from the original image.
                                # A shared/reused motion shot is never silently reframed.
                                if shot.get('reference_layout')!='generated' or shot.get('reuse_motion_from') or shot.get('face_box'):raise
                                prior=shot.get('result',{});attempt=max(1,int(prior.get('reference_retry_count',1)))
                                if (prior.get('error') or {}).get('stage')=='preflight':attempt+=1
                                correction={**shot,'seed':(shot['seed']+7919*attempt)%2147483647}
                                correction=speaker_closeup_shot(correction)
                                entry['reference_retry_count']=attempt
                                retry=folder/(digest(dict(reference=reference_key(correction,settings),speaker=shot.get('speaker_id'),face_retry=3,attempt=attempt,seed=correction['seed']))+'.png')
                                if not retry.is_file() or not valid_reference(retry):
                                    report(2,f'第 {numbers[shot["id"]]} 镜 · 自动调整说话人的取景（一次）…',shot_id=shot['id'])
                                    prepare_reference(correction,retry,settings,cancelled=cancel.exists,require_speaker_face=True)
                                reference=retry
                                checked=check_reference({**spec,'image':str(reference),'face_box':None,'actor_region':None})
                                entry['ensemble_reference']=entry.get('reference')
                                entry['reference']=f'/director-media/{project["id"]}/{reference.name}'
                                entry['preflight']={**checked,'reference_adjusted':True,'speaker_closeup':True,
                                    'ensemble_reference':entry['ensemble_reference']}
                                checkpoint()
                        else:entry['preflight']={'status':'not_required','reason':'无需可见口型'}
                    references[shot['id']]=reference
                    if job['mode']=='reference':entry['status']='completed'
                    checkpoint()
                except Exception as exc:mark_failed(shot,stage,exc)
        current_shot=None
        if job['mode']=='reference':
            finish_partial();report(100,'镜头参考已完成，可以预览。');return
        pending=unfinished();audios={}
        if pending:
            stage='audio';report(3,'正在准备逐句配音；已有配音会直接复用…')
            voice_result=work/'voices.json'
            task('voice_job',dict(shots=pending,folder=str(folder),result=str(voice_result),progress=str(progress),isolate_errors=True),'voice_worker.py')
            audios=json.loads(voice_result.read_text(encoding='utf-8'))
            for shot in pending:
                try:
                    audio=audios[shot['id']]
                    if audio.get('error'):
                        detail=audio['error'];result['shots'][shot['id']].update(status='failed',error=detail,video=None);checkpoint()
                        if detail.get('fatal'):raise SharedRuntimeFailure(detail['message'])
                        continue
                    entry=result['shots'][shot['id']]
                    entry.update(audio=f'/director-media/{project["id"]}/{audio["audio"]}',seconds=audio['seconds'],duration_extended=audio.get('extended',False))
                    if job['mode'] in ('audio','voices'):entry['status']='completed'
                    checkpoint()
                except Exception as exc:mark_failed(shot,'audio',exc)
        if job['mode'] in ('audio','voices'):
            finish_partial();report(100,'配音已完成，可以逐句试听。');return
        pending=unfinished();translated={}
        if pending:
            stage='translation';report(12,'正在本地理解每名角色的动作…')
            translations=work/'translations.json'
            acting_shots=list({motion_source(s,project)['id']:motion_source(s,project) for s in pending}.values())
            task('translation_job',dict(shots=acting_shots,result=str(translations),isolate_errors=True),'director_worker.py')
            translated=json.loads(translations.read_text(encoding='utf-8'))
            for shot in pending:
                acting=motion_source(shot,project);sources=action_sources(acting);values=translated.get(acting['id'])
                if not isinstance(values,list) or len(values)!=len(sources) or any(source and (not isinstance(value,str) or not value.strip()) for source,value in zip(sources,values)):
                    mark_failed(shot,'translation',ValueError('这个镜头的动作描述未能完整理解，已保留原稿；可以只重试这一镜，其他镜头继续。'))
            pending=unfinished()
        for shot in pending:
            current_shot=shot;entry=result['shots'][shot['id']];index=selected.index(shot);base=15+int(78*index/max(1,len(selected)))
            try:
                check_cancel();entry.update(status='running',error=None);checkpoint()
                stage='motion';audio=audios[shot['id']];seconds=audio['seconds']
                key=entry['signature'];clip=folder/(key+'.mp4');reference=references[shot['id']]
                entry.update(seed=shot['seed'],width=width,height=height)
                if speaker_mouth_covered(shot) and shot.get('text'):
                    entry['lip_sync_note']='说话人嘴部被头盔或面罩遮住，保留原有动作与角色配音，不制作可见嘴型。'
                def render_report(next_stage,message):
                    nonlocal stage
                    stage=next_stage
                    report(base,f'第 {numbers[shot["id"]]}/{len(project["shots"])} 镜 · '+message,shot_id=shot['id'])
                acting=motion_source(shot,project)
                current=render_shot(shot,project,reference,audio,folder,work,entry,run,task,render_report,checkpoint,cancel.exists,translated.get(acting['id']))
                from super_resolution import ready as enhancement_ready
                if width>entry['native_width'] or height>entry['native_height']:
                    if not enhancement_ready():raise ValueError('清晰度模型尚未完整准备，不能标记为高清修复完成。')
                    stage='enhance';report(base+4,f'第 {numbers[shot["id"]]} 镜 · 正在修复细节并放大到导出尺寸…',shot_id=shot['id'])
                    enhanced=folder/(digest(dict(source=current.name,width=width,height=height,model='realesr-general-x4v3',version=1))+'.enhanced.mp4')
                    if not enhanced.is_file() or not enhanced.with_suffix('.json').is_file():
                        task(shot['id']+'_enhance',dict(video=str(current),output=str(enhanced),width=width,height=height),'super_resolution.py')
                    current=enhanced;entry['enhancement']=json.loads(enhanced.with_suffix('.json').read_text('utf-8'))
                else:entry['enhancement']=dict(applied=False,reason='原生画面已达到导出尺寸')
                entry['resize_method']='Real-ESRGAN + Lanczos' if entry['enhancement']['applied'] else 'Lanczos'
                stage='export';report(base+5,f'第 {numbers[shot["id"]]}/{len(project["shots"])} 镜 · 正在导出并检查音画…',shot_id=shot['id'])
                ass=work/(shot['id']+'.ass');subtitles(shot,audio,ass,settings,project.get('captions'))
                temp=folder/(key+'.partial.mp4');run(encode_command(current,folder/audio['audio'],ass,seconds,temp,settings))
                entry['validation']=validate_clip(temp,seconds,settings);temp.replace(clip)
                entry.update(video=f'/director-media/{project["id"]}/{clip.name}',status='completed',error=None);checkpoint()
                report(min(95,base+2),f'第 {numbers[shot["id"]]} 镜已完成，可以预览。',shot_id=shot['id'])
            except Exception as exc:mark_failed(shot,stage,exc)
        current_shot=None
        finish_partial()
        if job['mode']=='all':
            stage='assembly'
            if any(result['shots'][s['id']].get('status')!='completed' or not result['shots'][s['id']].get('video') for s in selected):
                raise ValueError('存在未完成镜头，不能标记整集完成。')
            finalise([folder/(result['shots'][s['id']]['signature']+'.mp4') for s in selected],
                     [result['shots'][s['id']]['seconds'] for s in selected])
        report(100,'整集视频已完成，可以试看并下载。' if job['mode']=='all' else '这个镜头已完成，其余镜头可以继续生成。')
    except IncompleteProduction:
        raise
    except Exception as exc:
        shot_id=current_shot['id'] if current_shot else None
        if isinstance(exc,InterruptedError):
            for item in result['shots'].values():
                if item.get('status')=='running':item.update(status='pending',error=None)
            report(last_report.get('progress',0),str(exc),cancelled=True,shot_id=shot_id)
        else:
            result['failure']=failure(stage,exc)
            prefix=f'第 {numbers[shot_id]} 镜 · ' if shot_id else ''
            report(last_report.get('progress',0),prefix+STAGES.get(stage,stage)+'失败：'+str(exc),error=True,shot_id=shot_id)
        checkpoint();raise


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');job=json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
    if 'project' in job:main(job)
    else:translate(job)

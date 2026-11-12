import * as api from '/api.js';
import {normalizeProject,castEditor,roleFor} from '/director_cast.js';
import {productionEditor,showSound,bindSound} from '/director_production.js';
import {showStoryOverview} from '/director_story.js';
import {shotQuality,filmQuality} from '/production_quality.js';
const $=id=>document.getElementById(id);
const elapsedIndicator=api.createElapsedIndicator($('elapsed-time'));
const state={project:null,status:null,roles:[],config:null,dirty:false,busy:false,online:false,cards:new Map(),referenceViews:new Set(),expanded:new Set(),collapsed:new Set()};
const emotionNames={calm:'冷静',confident:'自信',angry:'愤怒',surprised:'惊讶',happy:'愉快',sad:'难过'};
const cameraNames={extreme_close:'特写 · 面部',close:'近景 · 上半身',medium:'中景 · 固定镜头',wide:'全景 · 全身',push:'缓慢推近',reaction:'近景 · 反应镜头'};
const maxShots=()=>state.config?.max_director_shots||300;
function followedVoice(shot){const role=roleFor(shot,shot.speaker_id,state.roles);return role?.voice||(role?.look?.gender==='male'?'Dylan':'Serena');}
const uid=()=>crypto.randomUUID().replaceAll('-','');
let toastTimer,backupDraft=null;
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,6500);}
function el(tag,cls='',text){const e=document.createElement(tag);e.className=cls;if(text!==undefined)e.textContent=text;return e;}
function dirty(){state.dirty=true;state.project.final=null;$('final-panel').hidden=true;$('save-state').textContent='有未保存的修改 · 已保留本机草稿';try{localStorage.setItem('director-draft-v1',JSON.stringify(state.project));}catch{}}
function focusShot(id){const card=state.cards.get(id)?.card;if(!card)return;$('shot-search').value='';$('shot-search').oninput?.();state.expanded.add(id);state.collapsed.delete(id);card.querySelector('.shot-body').hidden=false;card.querySelector('[aria-label^="展开或收起"]').textContent='收起';card.scrollIntoView({behavior:'smooth',block:'start'});}
function suggestedAction(text,index){
  if(/不可能|什么|怎么|竟然|居然/.test(text))return '人物眉毛抬起，身体微微后仰，睁大眼睛，露出惊讶的神情。';
  if(/开除|走人|滚|敢/.test(text))return '人物身体前倾，抬起右手强调，神情严肃，带着质问的眼神。';
  if(/证据|合同|现在|收购|我说/.test(text))return '人物慢慢抬起下巴，直视前方，轻轻抬起手掌，神情坚定自信。';
  return index%2?'人物微微前倾，轻轻点头，抬起手掌自然地解释。':'人物转头看向镜头，眼神专注，肩膀和头部自然活动。';
}
function newShot(text='',roleId=$('default-role').value,index=state.project.shots.length){return {id:uid(),role_id:roleId,role_ids:[roleId],speaker_id:roleId,actor_actions:{},text,action:suggestedAction(text,index),camera:'close',voice:followedVoice({speaker_id:roleId}),voice_mode:'role',duration:3,emotion:'calm',emotion_note:'',speed:1,pause_before:.12,pause_after:.3,seed:Math.floor(Math.random()*2147483647),lip_sync:true,face_box:null};}
function invalidate(shot,key){
  delete shot.placeholder;
  if(shot.result){
    if(['effect','effect_time','effect_level'].includes(key)){}
    else if(['action','camera','seed','lip_sync','lip_mode','face_box','role_id','role_ids','speaker_id','actor_actions','scene_image','scene_description','visual_only','reuse_motion_from','onscreen_text','subtitle_name','motion_seconds'].includes(key))shot.result={audio:shot.result.audio,seconds:shot.result.seconds,duration_extended:shot.result.duration_extended};
    else shot.result={};
  }
  dirty();updateMedia(shot);buttons();
}
function field(shot,key,label,type='text',options=null){
  const wrap=el('label','',label);let input;
  if(options){input=el('select','editor-input');for(const [value,name] of Object.entries(options)){const option=el('option','',name);option.value=value;input.append(option);}}
  else input=el(type==='textarea'?'textarea':'input','editor-input');
  if(type==='number')input.type='number';
  if(type==='textarea')input.rows=key==='action'?3:2;
  input.value=shot[key]??'';input.dataset.key=key;input.setAttribute('aria-label',label);
  const limits={text:40,action:600,emotion_note:100};if(limits[key])input.maxLength=limits[key];
  const range={duration:[1,15,.1],speed:[.8,1.25,.05],pause_before:[0,2,.1],pause_after:[0,3,.1],seed:[0,2147483647,1]}[key];
  if(range)[input.min,input.max,input.step]=range;
  input.oninput=()=>{shot[key]=type==='number'?(key==='duration'&&input.value===''?null:Number(input.value)):input.value;if(key==='voice'){shot.voice_mode='shot';const source=state.cards.get(shot.id)?.card.querySelector('[data-key="voice_mode"]');if(source)source.value='shot';}if(key==='voice_mode'&&input.value==='role'&&shot.speaker_id!=='narrator'){shot.voice=followedVoice(shot);invalidate(shot,'voice');renderShots();return;}invalidate(shot,key);};
  if(key==='duration')input.placeholder='自动适配对白';
  if(shot.reuse_motion_from&&['action','camera','seed'].includes(key))input.dataset.unavailable='true';
  wrap.append(input);return wrap;
}
function moveShot(shot,delta){const i=state.project.shots.indexOf(shot),j=i+delta;if(j<0||j>=state.project.shots.length)return;[state.project.shots[i],state.project.shots[j]]=[state.project.shots[j],state.project.shots[i]];dirty();renderShots();}
function createCard(shot,index){
  const card=el('article','shot');card.dataset.id=shot.id;
  const heading=el('div','shot-heading');heading.append(el('h3','',`镜头 ${String(index+1).padStart(2,'0')}${shot.source_shot?' · 原稿'+shot.source_shot:''}`));
  const duration=el('span','','等待试听');heading.append(duration);
  const copy=el('button','editor-input','复制');copy.type='button';copy.setAttribute('aria-label',`复制镜头${index+1}`);copy.onclick=()=>{if(state.project.shots.length>=maxShots()){toast(`最多 ${maxShots()} 个镜头。`);return;}const clone=structuredClone(shot);clone.id=uid();delete clone.result;delete clone.placeholder;state.project.shots.splice(index+1,0,clone);dirty();renderShots();};heading.append(copy);
  for(const [label,action] of [['↑',()=>moveShot(shot,-1)],['↓',()=>moveShot(shot,1)],['移除',()=>{if(state.project.shots.length===1){toast('至少保留一个镜头。');return;}state.project.shots=state.project.shots.filter(s=>s.id!==shot.id);dirty();renderShots();}]]){
    const b=el('button','editor-input',label);b.type='button';b.setAttribute('aria-label',`${label}镜头${index+1}`);b.onclick=action;heading.append(b);
  }
  const body=el('div','shot-body'),form=el('div','shot-form');
  const fold=el('button','text-button','展开');fold.type='button';fold.setAttribute('aria-label',`展开或收起镜头${index+1}`);body.hidden=state.collapsed.has(shot.id)||(state.project.shots.length>12&&index>0&&!state.expanded.has(shot.id));fold.textContent=body.hidden?'展开':'收起';fold.onclick=()=>{body.hidden=!body.hidden;state[body.hidden?'collapsed':'expanded'].add(shot.id);state[body.hidden?'expanded':'collapsed'].delete(shot.id);fold.textContent=body.hidden?'展开':'收起';};heading.append(fold);
  if(state.project.shots.length>12){const excerpt=el('p','shot-excerpt',shot.text||shot.onscreen_text||'无对白 · 场景镜头');card.append(excerpt);}
  form.append(productionEditor(shot,index,state,key=>invalidate(shot,key),renderShots,toast));
  if(!shot.visual_only){const cast=castEditor(shot,state.roles,key=>{if(shot.voice_mode==='role'&&shot.speaker_id!=='narrator'){const next=followedVoice(shot);if(next!==shot.voice){shot.voice=next;invalidate(shot,'voice');}}invalidate(shot,key);if(key!=='actor_actions')renderShots();});if(shot.reuse_motion_from)cast.querySelectorAll('.editor-input').forEach(input=>{if(input.dataset.key!=='speaker_id')input.dataset.unavailable='true';});form.append(cast);}else form.append(el('p','hint','纯场景镜头：不显示人物，可添加画面文字、音乐或画外音。'));
  form.append(field(shot,'camera','镜头取景','select',cameraNames),field(shot,'action','共同动作与镜头说明','textarea'),field(shot,'text','当前说话人的台词 · 空白表示无对白','textarea'));
  const voices=el('div','field-grid');voices.append(field(shot,'voice_mode','音色来源','select',{role:'跟随角色库',shot:'仅此镜头自选'}),field(shot,'voice','角色声音','select',state.config.voices),field(shot,'emotion','台词情绪','select',emotionNames),field(shot,'duration','目标时长 / 秒','number'));form.append(voices,el('p','hint','时长可设1–15秒，留空按完整对白适配。超过基础动作长度会往返循环动作，口型仍按整句生成；超过15秒会提示拆句，不截断台词。'));
  const timing=el('div','timing-grid');timing.append(field(shot,'speed','语速倍数','number'),field(shot,'pause_before','开口前停顿 / 秒','number'),field(shot,'pause_after','句后停顿 / 秒','number'));form.append(timing);
  const advanced=el('details','advanced');advanced.append(el('summary','','表演补充与口型校准'));
  const detail=el('div');detail.append(field(shot,'emotion_note','表演补充，例如：前半句压低声音，最后三个字加重','textarea'));
  if(!shot.lip_mode)shot.lip_mode='auto';
  detail.append(field(shot,'lip_mode','口型方式','select',{auto:'自动 · 动漫角色优先保画风',anime:'动漫 · 原有嘴形随声音张合',neural:'写实 · 模型口型'}),el('p','hint','动漫方式保留原画嘴形，匹配声音强弱与停顿，不等于逐音素对齐；写实方式可能改变二维画风。两种方式都会复用已有身体动作。'));
  const check=el('label','check');const input=el('input','editor-input');input.type='checkbox';input.checked=shot.lip_sync;input.onchange=()=>{shot.lip_sync=input.checked;invalidate(shot,'lip_sync');};check.append(input,document.createTextNode('根据台词生成口型'));detail.append(check);
  detail.append(el('p','hint','默认按站位跟踪当前说话人，旁白不生成口型。识别失败时填写该说话人人脸的左、上、宽、高百分比；四项留空即自动。多人对白建议近景，并避免交叉走位。'));
  const face=el('div','face-fields');const faceInputs=[];
  ['左 %','上 %','宽 %','高 %'].forEach((label,i)=>{const wrap=el('label','',label),input=el('input','editor-input');input.type='number';input.min=0;input.max=100;input.placeholder='自动';input.value=shot.face_box?.[i]??'';faceInputs.push(input);input.oninput=()=>{shot.face_box=faceInputs.every(x=>x.value==='')?null:faceInputs.map(x=>Number(x.value));invalidate(shot,'face_box');};wrap.append(input);face.append(wrap);});
  detail.append(face,field(shot,'seed','动作随机种子 · 相同设置会复用结果','number'));advanced.append(detail);form.append(advanced);
  const preview=el('div','shot-preview'),visual=el('div','visual'),audio=el('audio');audio.controls=true;audio.preload='metadata';audio.hidden=true;
  const mediaLabel=el('p','hint','参考人物'),voiceLabel=el('p','voice-label','先生成这句配音，再点击播放器试听。');
  const actions=el('div','shot-actions'),audition=el('button','button editor-input','生成 / 试听配音'),render=el('button','button primary editor-input','生成这个镜头');
  const reference=el('button','button editor-input','预览同框参考');reference.onclick=()=>perform('reference',shot.id);actions.append(reference);
  audition.onclick=()=>perform('audio',shot.id);render.onclick=()=>{if(shot.result?.video){shot.seed=(Number(shot.seed)+1)%2147483647;dirty();}perform('shot',shot.id);};actions.append(audition,render);
  preview.append(visual,mediaLabel,audio,voiceLabel,actions);body.append(form,preview);card.prepend(heading);card.append(body);$('shot-list').append(card);
  state.cards.set(shot.id,{card,visual,audio,mediaLabel,voiceLabel,duration,render,visualUrl:null,audioUrl:null});updateMedia(shot);
}
function updateMedia(shot){
  const c=state.cards.get(shot.id);if(!c)return;
  const result=shot.result||{},role=roleFor(shot,shot.role_id,state.roles),members=shot.role_ids.map(id=>roleFor(shot,id,state.roles)).filter(Boolean);
  const showVideo=!!result.video&&!state.referenceViews.has(shot.id);
  const url=(showVideo?result.video:null)||result.reference||(members.length>1?'cast:'+members.map(r=>r.image).join('|'):role?.image||'');
  c.visual.style.aspectRatio=state.project.export.ratio.replace(':','/');
  if(url!==c.visualUrl){c.visual.replaceChildren();c.visualUrl=url;if(url.startsWith('cast:')){const strip=el('div','cast-preview');for(const r of members){const image=el('img');image.src=r.image;image.alt=r.name;strip.append(image);}c.visual.append(strip);}else if(url){const media=el(showVideo?'video':'img');media.src=url;if(showVideo){media.controls=true;media.preload='metadata';media.playsInline=true;}else media.alt=role?.name||'参考人物';c.visual.append(media);}else c.visual.append(el('span','','请先选择已绘制的角色'));}
  c.mediaLabel.textContent=showVideo?`已生成 · ${result.width||540}×${result.height||960}`:result.reference?'已合成同框参考':members.length>1?'角色顺序示意 · 点击预览合成同框参考':'人物参考图 · 尚未生成动作';
  if(showVideo&&shotQuality(result))c.mediaLabel.textContent+=' · '+shotQuality(result);
  if(shot.scene_image&&!shot.visual_only&&members.some(r=>r.framing==='half'))c.mediaLabel.textContent+=' · 含半身素材，场景采用共同上半身构图';
  if(result.video&&!showVideo){const back=el('button','text-button','返回已生成视频');back.onclick=()=>{state.referenceViews.delete(shot.id);updateMedia(shot);};c.mediaLabel.append(back);}
  c.render.textContent=result.video?'重做这个镜头':'生成这个镜头';
  if(result.error){c.mediaLabel.textContent=(result.error.label||'制作')+'未完成：'+result.error.message;c.render.textContent='重试此镜头';}
  if(result.audio!==c.audioUrl){c.audioUrl=result.audio||null;c.audio.hidden=!result.audio;if(result.audio)c.audio.src=result.audio;else c.audio.removeAttribute('src');}
  c.voiceLabel.textContent=result.audio?'配音已就绪 · 点击播放试听':'先生成这句配音，再点击播放器试听。';
  c.duration.textContent=result.seconds?`${result.seconds.toFixed(2)} 秒${result.duration_extended?' · 已适配对白':''} · ${result.video?'镜头已完成':'配音已完成'}`:shot.duration?`目标 ${shot.duration} 秒`:'自动适配对白';
}
function renderShots(){normalizeProject(state.project);for(const shot of state.project.shots)if(shot.voice_mode==='role'&&shot.speaker_id!=='narrator'&&shot.voice!==followedVoice(shot)){shot.voice=followedVoice(shot);shot.result={};dirty();}showExportSettings();showSound(state);$('import-script').value=state.project.script;$('import-aliases').value=state.project.aliases;$('caption-speaker').checked=state.project.captions.speaker_name;state.cards.clear();$('shot-list').replaceChildren();state.project.shots.forEach(createCard);$('empty').hidden=!!state.project.shots.length;$('shot-count').textContent=state.project.shots.length;buttons();$('shot-search').oninput?.();}
function populateRoles(){const prior=$('default-role').value;const choices=state.roles.filter(r=>r.image);$('default-role').replaceChildren();for(const r of choices){const option=el('option','',r.name);option.value=r.id;$('default-role').append(option);}if(choices.some(r=>r.id===prior))$('default-role').value=prior;else if(choices.length===0){const o=el('option','','请先创建人物形象');o.value='';$('default-role').append(o);}}
function buttons(){const disabled=state.busy||state.status?.running||!state.online;document.querySelectorAll('.editor-input').forEach(x=>x.disabled=disabled||x.dataset.unavailable==='true');$('add-shot').disabled=disabled||state.project?.shots.length>=maxShots()||!$('default-role').value;$('render-all').disabled=disabled||!state.project?.shots.length||!state.status?.director?.motion_ready;$('assemble').disabled=disabled||!state.project?.shots.length||!state.project.shots.every(s=>s.result?.video);$('stop').disabled=!state.status?.running||state.status.status==='stopping'||state.busy;}
function showState(value){
  elapsedIndicator.update(value);
  const previousRoles=JSON.stringify(state.roles.map(r=>[r.id,r.name,r.image,r.voice]));
  state.status=value;state.roles=value.characters||[];
  if(previousRoles!==JSON.stringify(state.roles.map(r=>[r.id,r.name,r.image,r.voice]))){
    for(const shot of state.project?.shots||[])if(shot.voice_mode==='role'&&shot.speaker_id!=='narrator'&&shot.voice!==followedVoice(shot)){shot.voice=followedVoice(shot);invalidate(shot,'voice');}
    populateRoles();
    if(state.project)renderShots();
  }
  $('connection').textContent='本地运行';$('status').textContent=({running:'正在生成',done:'制作完成',error:'生成失败',stopped:'已停止',stopping:'正在停止'})[value.status]||'准备就绪';
  $('message').textContent=value.message;$('progress').value=value.progress;$('percent').textContent=value.progress+'%';
  $('model-state').textContent=value.director?.motion_ready?'动作模型已就绪 · 单镜头按顺序生成':'缺少动作模型，请在完整工作区使用。逐句配音仍可用。';
  const saved=value.director?.project;
  if(!state.dirty&&saved&&saved.id===state.project?.id){
    for(const shot of state.project.shots){const remote=saved.shots.find(s=>s.id===shot.id);if(remote){shot.result=remote.result;updateMedia(shot);}}
    state.project.final=saved.final;state.project.revision=saved.revision;
  }
  const result=state.project?.final;$('final-panel').hidden=!result;
  if(result){if($('final-video').getAttribute('src')!==result.url)$('final-video').src=result.url;$('download-final').href=result.url;$('download-final').download=state.project.title+'.mp4';$('final-description').textContent=filmQuality(result)+' · 已保存到视频文件夹';}
  const durations=state.project?.shots.map(s=>s.result?.seconds)||[];
  $('duration').textContent=durations.length&&durations.every(Boolean)?`合计 ${durations.reduce((a,b)=>a+b,0).toFixed(2)} 秒`:'试听后显示实际时长';showStoryOverview(state,focusShot);buttons();
}
async function perform(mode,shotId){
  if(state.busy)return;
  if(!state.project.shots.length){toast('请先添加镜头。');return;}
  if(mode==='reference')state.referenceViews.add(shotId);else if(mode==='shot')state.referenceViews.delete(shotId);else if(mode==='all')state.referenceViews.clear();
  state.busy=true;buttons();
  try{
    const payload=structuredClone(state.project);payload.title=$('title').value;
    // Snapshots and generated media are server-owned; keep longer projects small.
    for(const shot of payload.shots)for(const key of ['cast','role','image_hash','result','placeholder'])delete shot[key];
    delete payload.final;
    const result=mode==='save'?await api.action('director/save',payload):await api.action('director/generate',{project:payload,mode,shot_id:shotId});
    state.project=result.director.project;state.dirty=false;renderShots();showState(result);localStorage.setItem('director-draft-v1',JSON.stringify(state.project));$('save-state').textContent='作品已保存到本机';
    if(mode==='save')toast('作品已保存。');
  }catch(e){toast(e.message);}finally{state.busy=false;buttons();}
}
async function poll(){try{const value=await api.state();if(!state.online)state.config=await api.getConfig();state.online=true;showState(value);}catch(e){state.online=false;$('connection').textContent='连接断开';$('message').textContent='本地服务暂时断开，页面会自动重连。';buttons();}finally{setTimeout(poll,2000);}}
$('title').oninput=()=>{state.project.title=$('title').value;dirty();};
$('shot-search').oninput=()=>{const query=$('shot-search').value.trim().toLowerCase();for(const s of state.project.shots){const card=state.cards.get(s.id)?.card;if(card)card.hidden=!!query&&!`${s.text} ${s.action} ${s.scene_description} ${s.onscreen_text} ${s.subtitle_name} ${s.source_shot} ${(s.role_ids||[]).map(id=>state.roles.find(r=>r.id===id)?.name||'').join(' ')}`.toLowerCase().includes(query);}};
for(const [id,hidden] of [['collapse-shots',true],['expand-shots',false]])$(id).onclick=()=>{for(const {card} of state.cards.values()){card.querySelector('.shot-body').hidden=hidden;state[hidden?'collapsed':'expanded'].add(card.dataset.id);state[hidden?'expanded':'collapsed'].delete(card.dataset.id);card.querySelector('[aria-label^="展开或收起"]').textContent=hidden?'展开':'收起';}};
async function refreshProjects(){try{const result=await fetch('/api/director/projects').then(r=>r.json());$('project-library').replaceChildren();for(const p of result.projects){const option=el('option','',`${p.title} · ${p.shots}镜`);option.value=p.id;$('project-library').append(option);}}catch(e){toast('读取作品列表失败：'+e.message);}}
$('refresh-projects').onclick=refreshProjects;
$('open-project').onclick=async()=>{if(!$('project-library').value)return;backupDraft=structuredClone(state.project);try{localStorage.setItem(`director-backup-${backupDraft.id}`,JSON.stringify(backupDraft));state.busy=true;buttons();const value=await api.action('director/open',{id:$('project-library').value});state.project=value.director.project;state.dirty=false;$('title').value=state.project.title;$('restore-draft').hidden=false;renderShots();showState(value);toast('已打开保存的作品。');}catch(e){toast(e.message);}finally{state.busy=false;buttons();}};
function showExportSettings(){
  const {ratio,resolution}=state.project.export;const short=Number(resolution),long=Math.round(short*16/9);
  $('export-ratio').value=ratio;$('export-resolution').value=resolution;
  const size=ratio==='9:16'?`${short}×${long}`:ratio==='16:9'?`${long}×${short}`:`${short}×${short}`;
  const profiles=state.project.shots.map(s=>s.production_profile).filter(Boolean);
  const native=[...new Set(profiles.map(p=>`${p.width}×${p.height}`))].join(' / ');
  $('export-description').textContent=`导出 ${size} · ${native?'当前制作计划原生 '+native:'保存时自动选择已通过本机测试的模型'}。${state.status?.director?.production_status?.message||''}`;
}
for(const [id,key] of [['export-ratio','ratio'],['export-resolution','resolution']])$(id).onchange=()=>{state.project.export[key]=$(id).value;for(const shot of state.project.shots){const result=shot.result||{};shot.result={audio:result.audio,seconds:result.seconds};if(key==='ratio')shot.face_box=null;}dirty();renderShots();};
$('add-shot').onclick=()=>{state.project.shots.push(newShot());dirty();renderShots();};
$('save').onclick=()=>perform('save');$('render-all').onclick=()=>perform('all');
$('render-voices').onclick=()=>perform('voices');
$('assemble').onclick=()=>perform('assemble');
bindSound(state,dirty,renderShots,toast);
$('import-script').oninput=()=>{if(state.project){state.project.script=$('import-script').value;dirty();}};
$('import-aliases').oninput=()=>{if(state.project){state.project.aliases=$('import-aliases').value;dirty();}};
$('script-file').onchange=async e=>{try{const file=e.target.files[0];if(!file)return;if(file.size>200000)throw new Error('剧本文档过大，请选择文本脚本。');state.project.script=await file.text();$('import-script').value=state.project.script;dirty();toast('剧本已读入，核对角色别名后点击自动拆分镜。');}catch(error){toast(error.message);}};
$('new-project').onclick=()=>{$('shot-search').value='';backupDraft=structuredClone(state.project);try{localStorage.setItem(`director-backup-${backupDraft.id}`,JSON.stringify(backupDraft));}catch{}state.project={id:uid(),title:'',shots:[],export:{ratio:'9:16',resolution:'1440'}};if($('default-role').value)state.project.shots.push({...newShot(),placeholder:true});$('title').value='';$('restore-draft').hidden=false;dirty();renderShots();};
$('stop').onclick=async()=>{try{showState(await api.action('stop'));}catch(e){toast(e.message);}};
$('video-folder').onclick=()=>api.action('open-output').catch(e=>toast(e.message));
$('caption-speaker').onchange=()=>{state.project.captions.speaker_name=$('caption-speaker').checked;for(const shot of state.project.shots)if(shot.result)delete shot.result.video;dirty();renderShots();};
$('import-shots').onclick=async()=>{
  if(state.busy||!$('import-script').value.trim())return;
  const existing=state.project.shots.filter(s=>!s.placeholder);
  state.busy=true;buttons();
  try{
    const result=await api.action('director/split',{script:$('import-script').value,aliases:$('import-aliases').value,default_role:$('default-role').value,keep_pair:$('keep-pair').checked});
    if(result.shots.length+existing.length>maxShots())throw new Error(`合计超过 ${maxShots()} 镜，请分成两个作品。`);
    state.project.shots=[...existing,...result.shots];dirty();renderShots();toast(result.note);
  }catch(e){toast(e.message);}finally{state.busy=false;buttons();}
};
$('restore-draft').onclick=()=>{if(!backupDraft)return;state.project=backupDraft;$('title').value=state.project.title;dirty();renderShots();$('restore-draft').hidden=true;};
async function init(){
  try{state.config=await api.getConfig();const value=await api.state();state.online=true;state.roles=value.characters||[];populateRoles();
    try{backupDraft=JSON.parse(localStorage.getItem('director-draft-v1')||'null');}catch{}
    const remote=value.director?.project;state.project=remote||backupDraft||{id:uid(),title:'',shots:[]};
    $('restore-draft').hidden=!backupDraft||value.running||JSON.stringify(backupDraft)===JSON.stringify(remote);
    $('title').value=state.project.title;
    const chosen=new URLSearchParams(location.search).get('role');if(state.roles.some(r=>r.id===chosen&&r.image))$('default-role').value=chosen;
    if(!state.project.shots.length&&$('default-role').value)state.project.shots.push({...newShot(),placeholder:true});
    renderShots();showState(value);refreshProjects();poll();
  }catch(e){$('message').textContent='正在等待本地服务…';setTimeout(init,2500);}
}
init();

import {loadMaterialLibrary} from '/material-library.js';
import * as api from '/api.js';
import {shotQuality,filmQuality} from '/production_quality.js';
import {ImageModelSelect} from '/image-model-select.js';

const $=id=>document.getElementById(id);
const elapsedIndicator=api.createElapsedIndicator($('elapsed-time'));
const DRAFT_KEY='simple-creator-draft-v1',PREVIOUS_KEY='simple-creator-previous-draft-v1';
const state={status:null,config:null,doc:null,roleIds:[],busy:false,episode:0,research:null,editingRole:null,roleSignature:'',researchBusy:false,ignoreDocumentId:null,cardMedia:new Map(),roleBaseline:new Map(),roleBaselineDocument:null};
let toastTimer,pollTimer;
const imageModel=new ImageModelSelect({select:$('image-model'),note:$('image-model-note'),notify:toast,
  save:id=>task(async()=>{update(await api.action('image-engine/select',{id}));return true;})});
const el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
const roles=()=>state.status?.characters||[];
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,8500);}
function brief(){return {title:$('brief-title').value.trim(),work_mode:$('work-mode').value,online_research:$('online-research').checked,script:$('brief-script').value,role_ids:[...state.roleIds],style:$('brief-style').value,export:{ratio:'9:16',resolution:'1080'}};}
function saveDraft(){try{localStorage.setItem(DRAFT_KEY,JSON.stringify(brief()));$('draft-state').textContent='草稿已自动保存在本机';}catch{$('draft-state').textContent='浏览器未能保存草稿，请先复制重要文字。';}inputHints();}
function fillBrief(value={}){$('brief-title').value=value.title||'';$('work-mode').value=value.work_mode==='existing'?'existing':'original';$('online-research').checked=value.online_research!==false;$('brief-style').value=value.style||'realistic';$('brief-script').value=value.script||value.source_script||'';state.roleIds=[...new Set(value.role_ids||[])];renderSelected();renderLibrary();inputHints();}
function inputHints(){renderIssues();$('script-count').textContent=$('brief-script').value.length+' 字';$('research-hint').textContent=$('work-mode').value==='existing'?'查找已有作品的背景、人物和场景参考；同名作品可能需要核对。以你的人物设定与剧本为准。':'根据作品名称、人物与剧本寻找场景、服装和视觉参考。原创人物与剧情以你的设定为准。';$('research').textContent=state.researchBusy?'正在查找资料…':'先查找参考资料';buttons();}
function stableValue(value){if(Array.isArray(value))return value.map(stableValue);if(value&&typeof value==='object')return Object.fromEntries(Object.keys(value).sort().map(key=>[key,stableValue(value[key])]));return value;}
function roleIdentity(role){if(!role)return null;const fields={};for(const key of ['name','description','outfit','personality','style','look','framing','priorities','voice'])if(role[key]!==undefined)fields[key]=role[key];fields.image=role.image||'';return JSON.stringify(stableValue(fields));}
function captureRoleBaseline(){state.roleBaseline=new Map((state.doc?.characters||[]).filter(actor=>actor.role_id).map(actor=>[actor.role_id,roleIdentity(roles().find(role=>role.id===actor.role_id))]));state.roleBaselineDocument=state.doc?.id||null;}
function rolesChangedSinceOpen(){if(!state.doc||state.roleBaselineDocument!==state.doc.id)return false;return (state.doc.characters||[]).some(actor=>actor.role_id&&(!roles().some(role=>role.id===actor.role_id)||state.roleBaseline.get(actor.role_id)!==roleIdentity(roles().find(role=>role.id===actor.role_id))));}
function draftMatchesDocument(){if(!state.doc)return false;const prepared=documentBrief(state.doc),current=brief();return ['title','script','style'].every(key=>String(prepared[key]||'').trim()===String(current[key]||'').trim())&&(prepared.work_mode==='existing'?'existing':'original')===current.work_mode&&JSON.stringify([...(prepared.role_ids||[])].sort())===JSON.stringify([...current.role_ids].sort())&&!rolesChangedSinceOpen();}
function buttons(){const disabled=!!(state.busy||state.status?.running);document.querySelectorAll('main input,main textarea,main select,main button,#role-editor input,#role-editor textarea,#role-editor button').forEach(node=>node.disabled=disabled);$('close-role').disabled=false;$('stop').disabled=!state.status?.running||state.busy||state.status?.status==='stopping';$('prepare').disabled=disabled||!state.status?.story?.model_ready;$('research').disabled=disabled||!$('online-research').checked;$('produce').disabled=disabled||!state.doc?.complete||!draftMatchesDocument()||(state.status?.story?.issues||[]).some(item=>item.level==='error');$('produce-top').disabled=$('produce').disabled;$('advanced').disabled=disabled||!state.doc?.episodes?.[state.episode]?.shots?.length;$('resume').hidden=!state.doc||state.doc.complete||!state.doc.characters?.length||state.status?.running;$('draw-role').disabled=disabled||!state.status?.character_model_ready;$('open-story').disabled=disabled||!$('saved-projects').value;document.querySelectorAll('.library-role[data-selected="true"]').forEach(node=>node.disabled=true);document.querySelectorAll('.retry-shot').forEach(node=>node.disabled=$('produce').disabled);imageModel.sync(state.status,{busy:disabled});renderProgress();}
function episodeProject(){const project=state.status?.director?.project;return project&&state.doc?.director_projects?.[String(state.episode+1)]===project.id?project:null;}
function renderProgress(){
  $('engine-note').textContent=state.status?.director?.production_status?.message||'';
  if(state.researchBusy)return;
  const value=state.status||{},project=episodeProject(),film=project?.final;
  const total=project?.shots?.length||0,ready=(project?.shots||[]).filter(shot=>shot.result?.video).length;
  const failed=(project?.shots||[]).filter(shot=>shot.result?.error).length;
  const phase={story:'素材准备',director:'视频制作',video:'视频制作',character:'人物绘制',storyboard:'画面准备'}[value.task_kind]||'当前任务';
  const progress=Number.isFinite(Number(value.progress))?Math.max(0,Math.min(100,Number(value.progress))):0;
  let message=value.message||'准备就绪',label='',bar=progress,hideBar=false;
  let action=state.doc?.episodes?.length>1?`开始生成第 ${state.episode+1} 集视频`:'开始生成视频';
  if(project&&!film)action=ready===total&&total?'继续合成视频':'继续生成视频';
  if(failed&&!film)action='重试未完成镜头';
  $('produce-top').textContent=action;
  $('produce').textContent=action;
  $('production-next').hidden=!state.doc?.complete||!!film||!!value.running;
  $('production-next-note').textContent=$('produce-top').disabled?$('production-note').textContent:'人物与场景已准备好。点击后开始制作动态镜头，并自动合成为本集视频。';
  if(value.running){
    label=value.status==='stopping'?phase+' · 正在停止':progress>=100?phase+' · 正在收尾':phase+' '+progress+'%';
  }else if(failed&&value.status!=='stopped'){
    message=`已完成 ${ready}/${total} 个镜头，${failed} 个镜头待处理。具体原因显示在对应画面下方。`;
    label='部分未完成';bar=100*ready/(total+1);
  }else if(value.status==='error'||value.status==='stopped'){
    label=phase+(value.status==='error'?'失败':'已停止');
  }else if(film){
    message='视频已生成，可以试看和下载。';label='成片已完成';bar=100;
  }else if(state.doc?.complete){
    if(!draftMatchesDocument()){
      message='输入已有修改，请重新准备画面。';label='待更新素材';hideBar=true;
    }else if((value.story?.issues||[]).some(item=>item.level==='error')){
      message='素材检查尚未通过，请先处理制作检查中的问题。';label='待完善素材';hideBar=true;
    }else if(ready){
      message=ready===total?'镜头已完成，待合成成片。':`已完成 ${ready}/${total} 个镜头，可继续生成视频。`;
      label=ready===total?'待合成视频':`${ready}/${total} 镜头`;bar=100*ready/(total+1);
    }else{
      message='素材准备完成，待生成视频。';label='待生成视频';hideBar=true;
    }
  }else{
    label=value.status==='done'?phase+'已完成':state.doc?'准备未完成':'待开始';
    if(!state.doc){message='填写作品名称、人物与剧本，开始准备画面。';hideBar=true;}
  }
  $('status').textContent=message;$('percent').textContent=label;
  $('progress').hidden=hideBar;$('progress').value=bar;
  $('progress').setAttribute('aria-label',phase+'进度');
  $('progress').setAttribute('aria-valuetext',label);
}
async function task(action){if(state.busy)return;state.busy=true;buttons();try{return await action();}catch(error){toast(error.message);if($('role-editor').open)$('role-message').textContent=error.message;}finally{state.busy=false;state.researchBusy=false;inputHints();}}
function roleText(role){const options=state.config?.portrait_options?.features||[];const features=Object.entries(role.look||{}).map(([key,value])=>{const field=options.find(item=>item.key===key);return (field?.label||key)+'：'+(field?.options?.find(item=>item.value===value)?.label||value);});return [role.description,role.outfit,role.personality,...features].filter(Boolean).join('；');}
function roleImage(role){const image=el('img');image.src=role.image;image.alt=role.name+'人物形象';image.loading='lazy';return image;}
function selectRole(id){if(state.roleIds.includes(id))return;if(state.roleIds.length>=8){toast('一部作品最多安排8位主要角色。角色库仍可继续保存更多角色。');return;}state.roleIds.push(id);saveDraft();renderSelected();renderLibrary();buttons();}
function renderSelected(){const box=$('selected-roles');box.replaceChildren();$('cast-count').textContent=state.roleIds.length?state.roleIds.length+' 位':'尚未选择';if(!state.roleIds.length){box.append(el('p','选择已有角色，或创建新人物。','cast-empty'));return;}for(const id of state.roleIds){const role=roles().find(item=>item.id===id),card=el('article',undefined,'selected-role');if(!role){card.append(el('p','这位角色已不在角色库中，请重新选择。','hint'));}else{if(role.image)card.append(roleImage(role));else card.append(el('div',role.name.slice(0,1),'role-placeholder'));const info=el('div',undefined,'role-info');info.append(el('strong',role.name),el('p',role.description,'role-description'));const actions=el('div',undefined,'role-actions'),edit=el('button','编辑设定','text-button');edit.type='button';edit.onclick=()=>openRole(role);actions.append(edit);const generate=el('button',role.image?'重新生成人物':'生成人物','text-button');generate.type='button';generate.onclick=()=>task(async()=>update(await api.action('characters/generate',{id:role.id,mode:'new'})));actions.append(generate);info.append(actions);if(role.images?.length>1){const version=el('select');version.setAttribute('aria-label',role.name+'的主形象');for(const [index,item] of role.images.entries()){const option=el('option','形象 '+(index+1)+(item.image===role.image?' · 当前':''));option.value=item.image;version.append(option);}version.value=role.image;version.onchange=()=>task(async()=>update(await api.action('characters/choose',{id:role.id,image:version.value})));info.append(version);}if(!role.image)info.append(el('small','尚未生成人物，准备时将自动绘制。','hint'));card.append(info);}const remove=el('button','×','remove-role');remove.type='button';remove.setAttribute('aria-label','从本作品移除'+(role?.name||'失效角色'));remove.onclick=()=>{state.roleIds=state.roleIds.filter(value=>value!==id);saveDraft();renderSelected();renderLibrary();buttons();};card.append(remove);box.append(card);}}
function renderLibrary(){const box=$('library-roles'),query=$('role-search').value.trim().toLowerCase();box.replaceChildren();const available=roles().filter(role=>role.name.toLowerCase().includes(query));if(!available.length){box.append(el('p',roles().length?'没有找到这个名字。':'角色库还是空的，先新增一个角色。','hint'));return;}for(const role of available){const button=el('button',undefined,'library-role');button.type='button';button.dataset.selected=String(state.roleIds.includes(role.id));if(role.image)button.append(roleImage(role));button.append(el('span',role.name),el('small',state.roleIds.includes(role.id)?'已加入':role.image?'加入作品':'加入 · 尚无形象'));button.disabled=state.roleIds.includes(role.id)||state.busy||!!state.status?.running;button.onclick=()=>selectRole(role.id);box.append(button);}}
function openRole(role=null){if(state.busy||state.status?.running)return;state.editingRole=role?structuredClone(role):null;$('role-editor-title').textContent=role?'编辑角色':'新增角色';$('role-name').value=role?.name||'';$('role-description').value=role?roleText(role):'';$('simple-role-voice').replaceChildren();const automatic=el('option',role?'沿用当前音色':'自动匹配');automatic.value='';$('simple-role-voice').append(automatic);for(const [key,label] of Object.entries(state.config?.voices||{})){const option=el('option',label);option.value=key;$('simple-role-voice').append(option);}$('simple-role-voice').value=role?.voice||'';$('role-message').textContent=!state.status?.character_model_ready?'本地绘图模型尚未准备完整，可以先保存人物设定。':role?'修改会保存到角色库；已完成作品固定的参考图不会被替换。':'';$('role-editor').showModal();$('role-name').focus();}
async function saveRole(generate){if(!$('role-form').reportValidity())return;await task(async()=>{if(!state.roleIds.includes(state.editingRole?.id)&&state.roleIds.length>=8)throw new Error('这部作品已有8位主要角色，请先移除一位再添加。');const old=state.editingRole,description=$('role-description').value.trim();const value=old?{...old}:{id:crypto.randomUUID().replaceAll('-',''),outfit:'',personality:'',look:{},framing:'full',priorities:[]};value.name=$('role-name').value.trim();if(!old||description!==roleText(old)){value.description=description;value.outfit='';value.personality='';value.look={};value.priorities=[];}value.style=old?.style||$('brief-style').value;if($('simple-role-voice').value)value.voice=$('simple-role-voice').value;else delete value.voice;update(await api.action('characters/save',value));selectRole(value.id);$('role-editor').close();toast('人物设定已保存，并加入本作品。');if(generate)update(await api.action('characters/generate',{id:value.id,mode:'new'}));});}
function safeLink(value){try{const url=new URL(value);return ['https:','http:'].includes(url.protocol)?url.href:null;}catch{return null;}}
function renderResearch(research){state.research=research||null;$('research-panel').hidden=!research;$('research-sources').replaceChildren();$('research-summary').textContent='';$('research-message').textContent='';$('research-queries').textContent='';if(!research)return;
  const sources=Array.isArray(research.sources)?research.sources:[];
  $('research-summary').textContent=sources.length?sources.length+' 条来源':'暂无可用来源';
  $('research-message').textContent=research.message||research.summary||'查到的资料是补充参考，人物与剧情以你的设定为准。';
  for(const item of sources){if(!item||typeof item!=='object')continue;const card=el('article'),url=safeLink(item.url||item.link),title=item.title||item.name||'参考来源';if(url){const link=el('a',title);link.href=url;link.target='_blank';link.rel='noopener noreferrer';card.append(link);}else card.append(el('strong',title));const description=item.snippet||item.description||item.summary;if(description)card.append(el('p',description));if(item.category)card.append(el('small',item.category));$('research-sources').append(card);}
  const warnings=Array.isArray(research.warnings)?research.warnings:[];if(warnings.length){const section=el('div'),list=el('ul',undefined,'hint');section.append(el('strong','检索说明'));for(const warning of [...new Set(warnings.filter(value=>typeof value==='string'&&value.trim()))])list.append(el('li',warning));section.append(list);$('research-sources').append(section);}
  if(!sources.length){const links=Array.isArray(research.search_links)?research.search_links:[],section=el('div'),seen=new Set();for(const item of links){const url=safeLink(typeof item==='string'?item:item?.url||item?.link);if(!url||seen.has(url))continue;seen.add(url);const row=el('p'),link=el('a',typeof item==='string'?'打开搜索页面':item.query||item.title||'打开搜索页面');link.href=url;link.target='_blank';link.rel='noopener noreferrer';row.append(link);section.append(row);}if(seen.size){section.prepend(el('strong','自行查看搜索结果'));$('research-sources').append(section);}}
  const queries=Array.isArray(research.queries)?research.queries:[];$('research-queries').textContent=queries.length?'使用的搜索词：'+queries.map(query=>typeof query==='string'?query:query?.query||'').filter(Boolean).join('；'):'';
}
function renderActors(){const box=$('actors'),actors=state.doc?.characters||[];box.replaceChildren();$('asset-count').textContent=actors.filter(actor=>actor.reference_image).length+'/'+actors.length+' 位形象就绪';$('prepare-portraits').hidden=!(actors.some(actor=>!actor.reference_image)||(state.doc?.brief?.input_mode==='script'&&(state.doc.scenes||[]).some(scene=>!scene.asset_id)));for(const actor of actors){const card=el('article',undefined,'actor-card');if(actor.reference_image){const image=el('img');image.src=actor.reference_image;image.alt=actor.name+'固定主形象';card.append(image);}card.append(el('strong',actor.name),el('p',[actor.description,actor.outfit].filter(Boolean).join(' '),'hint'));box.append(card);}}
function displayAction(text){let value=text||'';for(const actor of [...(state.doc?.characters||[])].sort((a,b)=>(b.key?.length||0)-(a.key?.length||0)))if(actor.key)value=value.replace(new RegExp('(?<![A-Za-z0-9_])'+actor.key.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?![A-Za-z0-9_])','g'),()=>actor.name);return value;}
function renderEpisode(){const episode=state.doc?.episodes?.[state.episode];$('story-preview').replaceChildren();state.cardMedia.clear();$('episode-summary').textContent=episode?.summary||'';if(!episode){$('story-preview').append(el('p','正在理解剧本，画面安排会逐步出现在这里。','hint'));return;}for(const [index,shot] of (episode.shots||[]).entries()){const card=el('article',undefined,'story-preview-shot');card.append(el('span',String(index+1).padStart(2,'0'),'shot-number'));const body=el('div');body.append(el('p',displayAction(shot.action),'shot-action'));if(shot.text){const actor=state.doc.characters.find(item=>item.key===shot.speaker);body.append(el('p',(actor?.name||'旁白')+'：'+shot.text,'shot-dialogue'));}const media=el('div',undefined,'shot-media'),label=el('small',undefined,'hint');media.hidden=true;label.hidden=true;const retry=el('button','重试此镜头','retry-shot subtle');retry.type='button';retry.hidden=true;retry.onclick=()=>retryShot(shot.id);body.append(media,label,retry);state.cardMedia.set(shot.id,{media,label,retry,url:''});card.append(body);$('story-preview').append(card);}if(!episode.shots?.length)$('story-preview').append(el('p','这一集的画面还在准备中。','hint'));$('produce').textContent=state.doc.episodes.length>1?'生成这一集视频':'生成视频';updateShotMedia();renderFilm();}
function renderDocument(){const doc=state.doc;$('empty').hidden=!!doc;$('document').hidden=!doc;$('story-title').textContent=doc?.title||'从你的作品开始';if(!doc){$('film-preview').hidden=true;renderResearch(null);buttons();return;}renderActors();state.episode=Math.max(0,Math.min(state.episode,(doc.episodes?.length||1)-1));$('episode').replaceChildren();for(const [index,episode] of (doc.episodes||[]).entries()){const option=el('option',`第${index+1}集 · ${episode.title||doc.title}`);option.value=index;$('episode').append(option);}$('episode').value=state.episode;$('episode-field').hidden=(doc.episodes?.length||0)<2;renderEpisode();renderResearch(doc.research||null);renderIssues();buttons();}
function renderIssues(){const box=$('issues');box.replaceChildren();const items=state.status?.story?.issues||[];for(const item of items)box.append(el('li',item.message,'issue-'+item.level));if(!items.length)box.append(el('li',state.doc?.complete?'分镜和素材检查通过。成片仍需试看，确认人物、动作和声音。':'准备完成后会检查人物、画面与对白。'));const blocking=items.find(item=>item.level==='error');$('production-note').textContent=state.doc&&!draftMatchesDocument()?(rolesChangedSinceOpen()?'人物设定或主形象已修改。':'输入已修改。')+'请先点击左侧“理解剧本并准备画面”，为新内容另存作品；这里仍展示上一次的结果。':blocking?blocking.message:'视频生成较慢，可随时停止并保留已完成镜头。';}
function updateShotMedia(){
  const project=episodeProject();if(!project)return;
  for(const shot of project.shots||[]){
    const view=state.cardMedia.get(shot.id),result=shot.result||{};if(!view)continue;
    view.retry.hidden=!result.error;
    view.label.hidden=false;view.label.classList.toggle('issue-error',!!result.error);
    view.label.textContent=result.error?(result.error.label||'制作')+'未完成：'+result.error.message:
      result.video?'镜头已生成，可单独试看':result.status==='running'?'这一镜正在制作…':
      result.reference?'参考画面已就绪，等待制作动作与声音':'等待准备画面';
    if(result.video&&shotQuality(result))view.label.textContent+=' · '+shotQuality(result);
    const raw=result.video||result.reference||result.image||'',url=typeof raw==='string'&&/^\/director-media\/[a-f0-9]{32}\/[a-f0-9]{64}\.(mp4|png)$/.test(raw)?raw:'';
    if(!url){if(view.url){view.media.replaceChildren();view.media.hidden=true;view.url='';}continue;}
    if(view.url!==url){
      view.url=url;view.media.replaceChildren();const video=!!result.video,media=el(video?'video':'img');media.src=url;
      if(video){media.controls=true;media.preload='metadata';media.playsInline=true;}else{media.alt='这一镜的实际生成画面';media.loading='lazy';}
      view.media.append(media);view.media.hidden=false;
    }
  }
}
function retryShot(id){
  return task(async()=>{
    if(!draftMatchesDocument())throw new Error('输入已经修改，请先准备新内容，避免重试旧剧本。');
    const project=episodeProject();
    if(!project||!project.shots.some(shot=>shot.id===id))throw new Error('作品已经切换，请刷新后重试。');
    update(await api.action('director/generate',{mode:'shot',shot_id:id,project:structuredClone(project)}));
  });
}
function renderFilm(){const project=state.status?.director?.project,linked=state.doc?.director_projects?.[String(state.episode+1)]===project?.id,film=linked?project?.final:null;$('film-preview').hidden=!film;if(film){if($('film').getAttribute('src')!==film.url)$('film').src=film.url;$('film-download').href=film.url;$('film-info').textContent=filmQuality(film)+'。放大后的导出尺寸不等于原生细节。';}}
function update(value){elapsedIndicator.update(value);const wasRunning=state.status?.running,previousTask=state.status?.task_kind;state.status=value;$('connection').textContent='已连接本机';$('model-note').textContent=value.story?.model_ready?'联网仅用于查找参考；绘图与视频在本机生成。':'本地编剧模型未准备完整，暂不能自动安排画面。仍可保存输入、选择人物和查资料。';const signature=JSON.stringify(value.characters||[]);if(signature!==state.roleSignature){state.roleSignature=signature;renderSelected();renderLibrary();}const remote=value.story?.document;if(remote&&remote.id!==state.ignoreDocumentId&&(remote.id!==state.doc?.id||remote.revision!==state.doc?.revision||JSON.stringify(remote.director_projects||{})!==JSON.stringify(state.doc?.director_projects||{}))){const changedDocument=remote.id!==state.doc?.id;state.doc=structuredClone(remote);if(changedDocument)captureRoleBaseline();renderDocument();}if(wasRunning&&!value.running&&previousTask==='story'&&value.status==='done'&&state.doc?.complete)captureRoleBaseline();renderIssues();updateShotMedia();renderFilm();buttons();if(wasRunning&&!value.running)catalogue().catch(error=>toast(error.message));}
async function catalogue(){const response=await api.request('/api/story/projects'),data=await response.json(),selected=state.doc?.id||$('saved-projects').value;$('saved-projects').replaceChildren();if(!data.projects?.length){const option=el('option','暂无已保存作品');option.value='';$('saved-projects').append(option);}for(const project of data.projects||[]){const option=el('option',project.title);option.value=project.id;$('saved-projects').append(option);}if([...$('saved-projects').options].some(option=>option.value===selected))$('saved-projects').value=selected;buttons();}
function documentBrief(doc){const value={...doc.brief};value.title=doc.title||value.title;value.role_ids=doc.characters?.map(actor=>actor.role_id).filter(Boolean)||[];value.script=value.script||doc.source_script||doc.script||'';if(!value.script)value.script=(doc.episodes||[]).map(episode=>(episode.shots||[]).map(shot=>{const name=doc.characters.find(actor=>actor.key===shot.speaker)?.name||'旁白';return [shot.action?'画面：'+displayAction(shot.action):'',shot.text?name+'：'+shot.text:''].filter(Boolean).join('\n');}).join('\n\n')).join('\n\n');return value;}
function archiveDraft(){try{const value=brief();if(value.title||value.script||value.role_ids.length){localStorage.setItem(PREVIOUS_KEY,JSON.stringify(value));$('restore-draft').hidden=false;}}catch{}}

$('brief-form').oninput=saveDraft;$('brief-form').onchange=saveDraft;
$('brief-form').onsubmit=event=>{event.preventDefault();task(async()=>{const value=brief();if(!value.title)throw new Error('请先填写作品名称。');if(!value.role_ids.length)throw new Error('请先选择或新增出场人物。');if(!value.script.trim())throw new Error('请放入你的完整剧本。');saveDraft();state.episode=0;state.ignoreDocumentId=null;update(await api.action('story/start',{mode:'script',brief:value,auto_prepare:true}));await catalogue();});};
$('research').onclick=()=>task(async()=>{const value=brief();if(!value.title)throw new Error('先填写作品名称，再查找参考资料。');state.researchBusy=true;inputHints();$('status').textContent='正在按作品、人物与剧本查找参考资料…';$('percent').textContent='资料检索';$('progress').hidden=false;$('progress').removeAttribute('value');try{const result=await api.action('story/research',{brief:value});renderResearch(result.research||result);$('research-panel').open=true;$('status').textContent=(result.research||result).message||'参考资料已更新。';}finally{$('progress').value=state.status?.progress||0;$('percent').textContent=(state.status?.progress||0)+'%';}});
$('choose-role').onclick=()=>{$('role-picker').hidden=!$('role-picker').hidden;renderLibrary();buttons();};$('close-picker').onclick=()=>$('role-picker').hidden=true;$('role-search').oninput=renderLibrary;$('add-role').onclick=()=>openRole();$('close-role').onclick=()=>$('role-editor').close();$('role-form').onsubmit=event=>{event.preventDefault();saveRole(false);};$('draw-role').onclick=()=>saveRole(true);
$('script-file').onchange=()=>task(async()=>{const file=$('script-file').files[0];if(!file)return;if(file.size>500000)throw new Error('文字文件过大，请控制在6万字以内。');const text=await file.text();if(text.length>60000)throw new Error('剧本超过6万字，请分成几部作品导入。');if($('brief-script').value.trim())archiveDraft();$('brief-script').value=text;saveDraft();$('script-file').value='';toast('原稿已导入，可以开始理解剧本。');});
$('open-story').onclick=()=>task(async()=>{if(!$('saved-projects').value)return;archiveDraft();state.episode=0;state.ignoreDocumentId=null;update(await api.action('story/open',{id:$('saved-projects').value}));captureRoleBaseline();fillBrief(documentBrief(state.doc));saveDraft();});
$('new-story').onclick=()=>{archiveDraft();state.ignoreDocumentId=state.status?.story?.document?.id||null;fillBrief({online_research:true});saveDraft();state.doc=null;state.research=null;renderDocument();renderResearch(null);$('brief-title').focus();toast('已新建输入草稿，之前的作品保留在已保存作品中。');};
$('restore-draft').onclick=()=>{try{const prior=JSON.parse(localStorage.getItem(PREVIOUS_KEY)||'null');if(prior){archiveDraft();fillBrief(prior);saveDraft();toast('已恢复上一份输入草稿。');}}catch{toast('上一次草稿无法读取。');}};
$('stop').onclick=()=>task(async()=>update(await api.action('stop')));$('resume').onclick=()=>task(async()=>update(await api.action('story/start',{mode:'resume',id:state.doc.id,revision:state.doc.revision})));
const produceEpisode=()=>task(async()=>update(await api.action('story/produce',{id:state.doc.id,revision:state.doc.revision,episode:state.episode+1})));
$('produce').onclick=produceEpisode;$('produce-top').onclick=produceEpisode;
$('prepare-portraits').onclick=()=>task(async()=>update(await api.action('story/start',{mode:'portraits',id:state.doc.id,revision:state.doc.revision})));
$('episode').onchange=()=>{state.episode=Number($('episode').value);renderEpisode();buttons();};$('advanced').onclick=()=>task(async()=>{await api.action('story/commit',{id:state.doc.id,revision:state.doc.revision,episode:state.episode+1});location.href='/director';});
$('export-story').onclick=()=>{if(!state.doc)return;const url=URL.createObjectURL(new Blob([JSON.stringify(state.doc,null,2)],{type:'application/json'})),link=el('a');link.href=url;link.download=state.doc.title+'_创作工程.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),5000);};
async function poll(){try{update(await api.state());}catch{$('connection').textContent='连接断开';$('status').textContent='正在等待本地服务恢复，输入草稿仍保留。';}finally{pollTimer=setTimeout(poll,2000);}}
async function init(){try{state.config=await api.getConfig();update(await api.state());let draft;try{draft=JSON.parse(localStorage.getItem(DRAFT_KEY)||'null');$('restore-draft').hidden=!localStorage.getItem(PREVIOUS_KEY);}catch{}if(draft)fillBrief(draft);else if(state.doc)fillBrief(documentBrief(state.doc));else fillBrief();const roleId=new URLSearchParams(location.search).get('role');if(roleId){if(roles().some(role=>role.id===roleId)){selectRole(roleId);history.replaceState(null,'','/create');}else toast('这个角色已不在角色库中，请重新选择。');}await catalogue();inputHints();clearTimeout(pollTimer);poll();}catch(error){$('status').textContent=error.message;setTimeout(init,2500);}}
init();
loadMaterialLibrary().catch(()=>{});

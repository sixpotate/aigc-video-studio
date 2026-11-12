import * as api from '/api.js';
import {CharacterManager} from '/characters.js';

const $ = id => document.getElementById(id);
const ui = {config:null, state:null, selected:new Set(), seen:new Set(), projectId:null, busy:false, online:false, cards:new Map()};
const statuses = {idle:'准备就绪', running:'正在生成', stopping:'正在停止', stopped:'已停止', done:'生成完成', error:'生成失败'};
const shotStatuses = {pending:'等待生成',running:'生成中',ready:'已完成',cancelled:'已停止',error:'生成失败'};
let toastTimer;
function toast(message) {
  $('toast').textContent = message; $('toast').hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(()=>$('toast').hidden=true, 5000);
}
function element(tag, cls, text) {
  const node = document.createElement(tag); node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}
function updateRoleChoices() {
  const selected=$('lead_character').value;
  $('lead_character').replaceChildren();
  for(const role of characters.roles.filter(r=>r.image)){
    const option=element('option','',role.name);option.value=role.id;$('lead_character').append(option);
  }
  if([...$('lead_character').options].some(o=>o.value===selected))$('lead_character').value=selected;
  if(!$('lead_character').options.length){const option=element('option','','请先生成角色形象');option.value='';$('lead_character').append(option);}
}
function updateSource() {
  const custom=$('source').value==='character';
  $('lead-field').hidden=!custom;$('template-field').hidden=custom;$('style-field').hidden=custom;
  $('video-settings').hidden=custom;
  $('source-tag').textContent=custom?'角色立绘':'模板模式';
  $('source-note').textContent=custom?'这里生成单人静态立绘分镜。点击“制作角色视频”，可安排1–4人同框、分别填写动作和对白，并导出2K视频。':'原有模板中的人物固定；顶部“自定义角色视频”支持1–4人同框、新动作、配音和2K导出。';
  buttons();
}
function readForm() {
  return {title:$('title').value.trim(), script:$('script').value.trim(), ...($('source').value==='character'?{character_ids:[$('lead_character').value].filter(Boolean)}:{}), settings:{style:$('style').value, template:Number($('template').value), ratio:$('ratio').value, count:Number($('count').value), resolution:$('resolution').value,source:$('source').value,lead_character:$('lead_character').value,video_duration:Number($('video_duration').value),video_mood:$('video_mood').value}};
}
function writeForm(project) {
  $('title').value=project.title; $('script').value=project.script;
  for (const key of ['style','template','ratio','count','resolution']) $(key).value=project.settings[key];
  $('source').value=project.settings.source||'template';
  $('video_duration').value=project.settings.video_duration||12.25;
  $('video_mood').value=project.settings.video_mood||'daily';
  if(project.settings.lead_character)$('lead_character').value=project.settings.lead_character;
  updateSource();
  countScript();
}
function countScript() {$('script-count').textContent=`${$('script').value.length} / 6000`;}
function example() {
  const ep = ui.config.episodes[Number($('template').value||1)-1];
  if (!ep) { toast('未提供示例剧本，请输入自己的故事。'); return; }
  $('title').value=ep.title; $('script').value=ep.lines.map(l=>l.text).join('\n');
  countScript(); saveDraft(); toast('示例剧本已载入，可直接编辑。');
}
function saveDraft() {
  if (!ui.config) return;
  try {localStorage.setItem('drama-draft-v2',JSON.stringify(readForm()));} catch {}
}
function selection() {
  const ready=(ui.state?.project?.shots||[]).filter(s=>s.image);
  const count=ready.filter(s=>ui.selected.has(s.id)).length;
  $('select-all').disabled=!ready.length || ui.busy || ui.state?.running;
  $('select-all').checked=ready.length>0&&count===ready.length;
  $('select-all').indeterminate=count>0&&count<ready.length;
  $('export-count').textContent=count?`已选择 ${count} 张图片`:'尚未选择图片';
  $('export-button').disabled=!count||ui.busy||ui.state?.running||!ui.online;
}
function openImage(shot) {
  if (!shot.image) return;
  $('lightbox-title').textContent=`镜头 ${String(shot.id).padStart(2,'0')}`;
  $('lightbox-image').src=shot.image;
  $('lightbox-image').alt=shot.text;
  $('lightbox-caption').textContent=shot.text;
  $('lightbox').showModal();
}
function createCard(shot) {
  const card=element('article','shot-card'); card.dataset.id=shot.id;
  const top=element('div','shot-card-top'), label=element('label','shot-label');
  const checkbox=document.createElement('input'); checkbox.type='checkbox'; checkbox.setAttribute('aria-label',`选择镜头${shot.id}`);
  checkbox.onchange=()=>{checkbox.checked?ui.selected.add(shot.id):ui.selected.delete(shot.id);card.classList.toggle('selected',checkbox.checked);selection();};
  label.append(checkbox,document.createTextNode(`镜头 ${String(shot.id).padStart(2,'0')}`));
  const status=element('span','shot-status'); top.append(label,status);
  const frame=element('button','shot-image-button'); frame.type='button'; frame.setAttribute('aria-label',`预览镜头${shot.id}`);
  frame.onclick=()=>openImage(ui.state.project.shots.find(s=>s.id===shot.id));
  const description=element('p','shot-description');
  const bottom=element('div','shot-bottom'), meta=element('span','shot-meta');
  const regenerate=element('button','regenerate','↻ 重新生成'); regenerate.type='button'; regenerate.title='使用模板中的其他时刻与取景，重新生成此镜头';
  regenerate.setAttribute('aria-label',`重新生成镜头${shot.id}`);
  regenerate.onclick=()=>perform('regenerate',{project_id:ui.state.project.id,shot_id:shot.id});
  bottom.append(meta,regenerate);card.append(top,frame,description,bottom);$('shots').append(card);
  return {card,checkbox,status,frame,description,meta,regenerate,imageUrl:null,phase:null};
}
function render(state) {
  ui.state=state;
  characters.sync(state);
  const project=state.project;
  if ((project?.id||null)!==ui.projectId) {
    ui.projectId=project?.id||null; ui.selected.clear();ui.seen.clear();ui.cards.clear();$('shots').replaceChildren();
  }
  const shots=project?.shots||[];
  $('empty-state').hidden=shots.length>0;
  $('shot-total').textContent=shots.length;
  $('project-summary').textContent=project?`${project.title} · ${project.settings.ratio} · ${project.settings.resolution}p`:'把故事变成看得见的画面。';
  $('ready-count').textContent=`${shots.filter(s=>s.image).length} 张已完成`;
  $('status-title').textContent=statuses[state.status]||'准备就绪';
  $('status-text').textContent=state.message;
  $('progress-percent').textContent=`${state.progress}%`;
  $('progress-fill').style.width=`${state.progress}%`;
  $('progress').setAttribute('aria-valuenow',state.progress);
  $('status-dot').className=`status-dot ${state.status}`;
  for (const shot of shots) {
    if (!ui.cards.has(shot.id)) ui.cards.set(shot.id,createCard(shot));
    const c=ui.cards.get(shot.id);
    if (shot.image&&!ui.seen.has(shot.id)) {ui.selected.add(shot.id);ui.seen.add(shot.id);}
    c.checkbox.checked=ui.selected.has(shot.id);c.checkbox.disabled=!shot.image||state.running||ui.busy;
    c.card.classList.toggle('selected',c.checkbox.checked);c.card.classList.toggle('is-running',shot.status==='running');
    c.status.textContent=shotStatuses[shot.status]; c.status.className=`shot-status ${shot.status}`;
    if (shot.image!==c.imageUrl || shot.status!==c.phase) {
      c.frame.replaceChildren();c.imageUrl=shot.image;c.phase=shot.status;
      if (shot.image) {
        const img=element('img','shot-image');img.src=shot.image;img.alt=`镜头${shot.id}：${shot.text}`;
        c.frame.append(img);
      } else {
        const placeholder=element('div','shot-placeholder');placeholder.append(element('b','',String(shot.id).padStart(2,'0')),element('span','',shotStatuses[shot.status]));c.frame.append(placeholder);
      }
    }
    c.frame.disabled=!shot.image;
    c.description.textContent=shot.text;c.description.title=shot.text;
    c.meta.textContent=`${project.settings.ratio} · ${project.settings.resolution}p · V${shot.revision+1}`;
    c.regenerate.disabled=state.running||ui.busy||!ui.online;
    c.regenerate.title=project.settings.source==='character'?'调整立绘排版，保留同一人物形象':'使用模板中的其他时刻与取景，重新生成此镜头';
  }
  buttons();
}
function buttons() {
  const running=ui.state?.running||false;
  $('editor-fields').disabled=running||ui.busy;
  $('generate').disabled=running||ui.busy||!ui.online;
  $('stop').disabled=!running||ui.state?.status==='stopping'||ui.busy||!ui.online;
  $('reset').disabled=running||ui.busy||!ui.online;
  $('empty-example').disabled=running||ui.busy||!ui.config;
  const custom=$('source').value==='character';
  $('video-button').textContent=custom?'制作角色视频 ↗':'生成配音视频';
  $('video-button').disabled=running||ui.busy||!ui.online||(custom?!$('lead_character').value:!ui.state?.project);
  selection();
}
async function perform(name,payload={}) {
  if(ui.busy) return;
  ui.busy=true;buttons();
  try {render(await api.action(name,payload));}
  catch(e){toast(e.message);}
  finally {ui.busy=false;if(ui.state)render(ui.state);}
}
async function poll() {
  try {
    const state=await api.state();
    if(!ui.online) ui.config=await api.getConfig();
    ui.online=true;$('connection').className='connection online';$('connection').replaceChildren(element('i',''),document.createTextNode('本地运行'));
    render(state);
  } catch {
    ui.online=false;$('connection').className='connection';$('connection').textContent='连接已断开';
    $('status-text').textContent='暂时无法连接。请重新双击启动文件，页面会自动重试。';buttons();
  } finally {setTimeout(poll,ui.state?.running?450:2000);}
}
$('project-form').onsubmit=e=>{e.preventDefault();saveDraft();perform('generate',readForm());};
$('project-form').oninput=()=>{countScript();saveDraft();};
$('project-form').onchange=saveDraft;
$('source').onchange=()=>{updateSource();saveDraft();};
$('example-button').onclick=example;$('empty-example').onclick=example;
$('stop').onclick=()=>perform('stop');
$('reset').onclick=async()=>{
  await perform('reset');
  if(ui.state?.project||ui.state?.running)return;
  writeForm({title:'',script:'',characters:ui.config.characters,settings:{style:'template',ratio:'9:16',count:6,resolution:'540',template:1}});
  saveDraft();
};
$('select-all').onchange=e=>{for(const s of ui.state.project.shots){if(s.image)e.target.checked?ui.selected.add(s.id):ui.selected.delete(s.id);}render(ui.state);};
$('view-mode').onclick=()=>{const compact=$('shots').classList.toggle('compact');$('view-mode').textContent=compact?'标准视图':'紧凑视图';};
$('help-button').onclick=()=>$('help').showModal();$('close-help').onclick=()=>$('help').close();
$('close-lightbox').onclick=()=>$('lightbox').close();
for(const id of ['help','lightbox'])$(id).addEventListener('click',e=>{if(e.target===$(id)){const r=$(id).getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)$(id).close();}});
$('video-button').onclick=()=>{
  if($('source').value==='character'){location.href=`/director?role=${encodeURIComponent($('lead_character').value)}`;return;}
  const saved=ui.state?.project,current=readForm();
  if(!saved)return;
  if(current.script!==saved.script||current.title!==saved.title||['template','video_duration','video_mood'].some(k=>String(current.settings[k])!==String(saved.settings[k]??({video_duration:12.25,video_mood:'daily'}[k])))){
    toast('剧本或视频设置已修改，请先点击“开始生成”更新分镜，再制作视频。');return;
  }
  perform('video');
};
$('video-folder').onclick=()=>api.action('open-output').catch(e=>toast(e.message));
$('image-folder').onclick=()=>api.action('open-images').catch(e=>toast(e.message));
$('export-button').onclick=async()=>{ui.busy=true;buttons();try{await api.exportImages(ui.state.project,[...ui.selected]);toast('已保存到“导出的图片”文件夹，同时已发起浏览器下载。');}catch(e){toast(e.message);}finally{ui.busy=false;buttons();}};

async function init() {
  try {
    ui.config=await api.getConfig();ui.online=true;
    characters.portrait.configure(ui.config.portrait_options);
    $('template').replaceChildren();
    for(const e of ui.config.episodes){const option=document.createElement('option');option.value=e.id;option.textContent=`${String(e.id).padStart(2,'0')} · ${e.title}`;$('template').append(option);}
    const state=await api.state();
    characters.sync(state);
    let draft=null;
    try {
      const saved=JSON.parse(localStorage.getItem('drama-draft-v2')||'null');
      if(saved && typeof saved.script==='string' && saved.settings) draft=saved;
    } catch {}
    if(state.running&&state.project)writeForm(state.project);else if(draft)writeForm(draft);else if(state.project)writeForm(state.project);else example();
    render(state);poll();
  } catch(e){ui.online=false;toast('正在等待本地制作器连接…');buttons();setTimeout(init,3000);}
}
const characters=new CharacterManager({notify:toast,applyState:render,onChange:updateRoleChoices,useRole:role=>{
  $('source').value='character';$('lead_character').value=role.id;updateSource();saveDraft();toast(`已选择${role.name}，点击“开始生成”制作立绘分镜。`);
}});
init();

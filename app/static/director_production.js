import * as api from '/api.js';
const el=(tag,text='')=>{const node=document.createElement(tag);node.textContent=text;return node;};
const options=(select,values,current)=>{select.replaceChildren();for(const [value,name] of Object.entries(values)){const option=el('option',name);option.value=value;select.append(option);}select.value=current;};
export async function uploadAsset(file,kind){
  if(!file)return null;if(file.size>20*1024*1024)throw new Error('素材最大20MB。');
  const data=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('无法读取本机文件。'));reader.readAsDataURL(file);});
  return api.action('director/upload',{kind,name:file.name,data});
}
export function productionEditor(shot,index,state,changed,rerender,toast){
  const box=el('details');box.className='production-editor';box.append(el('summary','场景、说话方式、动作复用与音效'));
  const body=el('div');body.className='production-fields';
  function field(key,label,type='text',values=null){
    const wrap=el('label',label),input=el(values?'select':type==='textarea'?'textarea':'input');input.className='editor-input';input.dataset.key=key;input.setAttribute('aria-label',label);
    if(values)options(input,values,shot[key]??'');else{if(type!=='textarea')input.type=type;input.value=shot[key]??'';}
    if(type==='textarea'){input.rows=2;input.maxLength=key==='onscreen_text'?100:240;}
    if(['scene_image','scene_description','motion_seconds'].includes(key)&&shot.reuse_motion_from)input.dataset.unavailable='true';
    input.onchange=()=>{shot[key]=type==='number'?Number(input.value):input.value;changed(key);};wrap.append(input);body.append(wrap);return input;
  }
  const speech=field('speech_kind','说话方式','select',state.config.speech_kinds||{dialogue:'角色对白',os:'内心独白',narration:'画外音',chorus:'齐声'});
  speech.onchange=()=>{shot.speech_kind=speech.value;shot.lip_sync=speech.value==='dialogue';changed('speech_kind');rerender();};
  const subtitle=field('subtitle_name','字幕中的人物称呼');subtitle.maxLength=24;
  field('scene_image','背景图片','select',{'':'使用人物原有背景',...Object.fromEntries((state.config.assets||[]).filter(a=>a.kind==='background').map(a=>[a.id,a.name]))});
  const upload=el('input');upload.type='file';upload.accept='image/png,image/jpeg,image/webp';upload.className='editor-input';upload.setAttribute('aria-label','导入场景图片');if(shot.reuse_motion_from)upload.dataset.unavailable='true';
  upload.onchange=async()=>{try{const result=await uploadAsset(upload.files[0],'background');if(!result)return;state.config.assets=result.assets;shot.scene_image=result.asset.id;changed('scene_image');rerender();toast('背景已保存到本机，可以预览同框参考。');}catch(e){toast(e.message);}};body.append(upload);
  field('scene_description','环境与场景说明（提供给动作模型）','textarea');
  const check=el('label',''),input=el('input');input.type='checkbox';input.className='editor-input';input.dataset.key='visual_only';input.checked=!!shot.visual_only;if(shot.reuse_motion_from)input.dataset.unavailable='true';input.setAttribute('aria-label','纯场景镜头，不显示人物');
  input.onchange=()=>{shot.visual_only=input.checked;if(input.checked){shot.lip_sync=false;shot.speech_kind='narration';}changed('visual_only');rerender();};check.className='check';check.append(input,document.createTextNode('纯场景镜头，不显示人物'));body.append(check);
  const lengths=field('motion_seconds','新生成的基础动作长度','select',{'3':'约3秒 · 节省时间，长对白循环动作','6':'约6秒 · 更连贯，生成较慢'});lengths.onchange=()=>{shot.motion_seconds=Number(lengths.value);changed('motion_seconds');};
  const reuse=field('reuse_motion_from','复用前面镜头的动作','select',{'':'单独生成动作',...Object.fromEntries(state.project.shots.slice(0,index).map((s,i)=>[s.id,`镜头 ${i+1} · ${s.subtitle_name||s.role?.name||'角色'} ${s.text.slice(0,12)}`]))});
  reuse.onchange=()=>{shot.reuse_motion_from=reuse.value;if(reuse.value){let source=state.project.shots.find(s=>s.id===reuse.value);const seen=new Set();while(source?.reuse_motion_from&&!seen.has(source.id)){seen.add(source.id);source=state.project.shots.find(s=>s.id===source.reuse_motion_from);}if(source){for(const key of ['role_ids','actor_actions','action','camera','scene_image','scene_description','visual_only','motion_seconds','seed'])shot[key]=structuredClone(source[key]);if(!shot.role_ids.includes(shot.speaker_id)&&shot.speaker_id!=='narrator')shot.speaker_id=shot.role_ids[0];shot.role_id=shot.speaker_id==='narrator'?shot.role_ids[0]:shot.speaker_id;shot.face_box=null;}}changed('reuse_motion_from');rerender();};
  const hint=el('p','复用动作会保持来源镜头的人物、场景和取景；台词、声音、情绪与停顿仍独立。长对白通过往返循环延长身体动作，口型逐句重新生成。');hint.className='hint';body.append(hint);
  field('onscreen_text','画面花字 / 空镜说明','textarea');
  field('effect','成片音效（合成时加入）','select',state.config.effects||{none:'无'});
  const time=field('effect_time','音效在本镜头第几秒出现','number');time.min=0;time.max=15;time.step=.05;
  const level=field('effect_level','音效音量 / dB','number');level.min=-36;level.max=0;level.step=1;
  box.append(body);return box;
}
export function showSound(state){
  const sound=state.project.sound;const select=document.getElementById('music-track');
  options(select,{...(state.config.music_styles||{none:'不加音乐'}),...Object.fromEntries((state.config.assets||[]).filter(a=>a.kind==='music').map(a=>['asset:'+a.id,a.name]))},sound.track);
  document.getElementById('music-level').value=sound.level;document.getElementById('music-duck').checked=sound.duck;document.getElementById('music-fade').value=sound.fade;
}
export function bindSound(state,dirty,rerender,toast){
  for(const [id,key] of [['music-track','track'],['music-level','level'],['music-duck','duck'],['music-fade','fade']])document.getElementById(id).onchange=e=>{state.project.sound[key]=key==='duck'?e.target.checked:key==='track'?e.target.value:Number(e.target.value);dirty();};
  document.getElementById('music-upload').onchange=async e=>{try{const result=await uploadAsset(e.target.files[0],'music');if(!result)return;state.config.assets=result.assets;state.project.sound.track='asset:'+result.asset.id;dirty();rerender();toast('音乐已保存到本机。');}catch(error){toast(error.message);}};
  document.getElementById('music-preview').onclick=async()=>{try{const track=state.project.sound.track;if(track==='none'){toast('请先选择配乐。');return;}const result=await api.action('director/music-preview',{track});const player=document.getElementById('music-player');player.src=result.url;player.hidden=false;await player.play();}catch(error){toast(error.message);}};
}

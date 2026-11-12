import * as api from '/api.js';
import {PortraitControls} from '/portrait-controls.js';
import {RoleVoice} from '/role-voice.js';
import {ImageModelSelect} from '/image-model-select.js';

const $ = id => document.getElementById(id);
const styleNames = {anime:'日系插画',guoman:'国漫插画','3d':'3D动画',realistic:'写实',soft_photo:'柔光真人写真'};
const newId = () => crypto.randomUUID().replaceAll('-', '');
function node(tag, className, text) {
  const el=document.createElement(tag); el.className=className;
  if(text!==undefined)el.textContent=text;
  return el;
}
function isCurrent(role, fields=role) {
  const version=(role.images||[]).find(v=>v.image===role.image);
  return !!version && ['description','outfit','style'].every(k=>(version[k]||'')===(fields[k]||''))
    && (version.framing||'half')===(fields.framing||'half')
    && Object.keys({...version.look,...fields.look}).every(k=>version.look?.[k]===fields.look?.[k])
    && JSON.stringify([...(version.priorities??['outfit','hair','pose'])].sort())===JSON.stringify([...(fields.priorities??['outfit','hair','pose'])].sort());
}

export class CharacterManager {
  constructor({notify,applyState,useRole,onChange}) {
    this.notify=notify; this.applyState=applyState; this.useRole=useRole; this.onChange=onChange;
    this.roles=[]; this.editingId=null; this.busy=false; this.pending=false; this.signature=''; this.lastDeleted=null;
    this.portrait=new PortraitControls(notify);
    this.voice=new RoleVoice({notify,applyState});
    this.imageModel=new ImageModelSelect({select:$('image-model'),note:$('image-model-note'),notify,
      save:id=>this.action('image-engine/select',{id})});
    $('add-character').onclick=()=>this.open();
    $('close-character').onclick=()=>$('character-editor').close();
    $('character-form').onsubmit=e=>{e.preventDefault();this.save(false);};
    $('draw-character').onclick=()=>this.save(true);
    this.simple=true;
    $('toggle-role-fields').onclick=()=>{if(this.simple){const fields=this.fields();for(const key of ['description','outfit','personality'])$('role-'+key).value=fields[key]||'';this.portrait.open({...this.roles.find(r=>r.id===this.editingId),...fields});}else{$('role-visual').value=this.combined(this.legacyFields());this.initialSimple=null;}this.simple=!this.simple;this.fieldMode();this.preview();};
    $('apply-correction').onclick=async()=>{const edit=$('portrait-instruction').value.trim();if(!edit){this.notify('请先写下要修改的地方。');return;}await this.action('characters/generate',{id:this.editingId,mode:'reference',reference:this.roles.find(r=>r.id===this.editingId)?.image,edit_instruction:edit,seed:'',content_check:$('portrait-content-check').checked});};
    $('stop-character').onclick=()=>this.action('stop');
    $('character-form').oninput=()=>this.preview();
    $('character-form').onchange=()=>this.preview();
    $('character-folder').onclick=()=>api.action('characters/open-folder').catch(e=>this.notify(e.message));
    $('undo-character').onclick=async()=>{
      if(!this.lastDeleted)return;
      await this.action('characters/restore',{id:this.lastDeleted});
      this.lastDeleted=null; $('character-undo').hidden=true;
    };
    $('portrait-version').onchange=async e=>{
      await this.action('characters/choose',{id:this.editingId,image:e.target.value});
      this.preview();
    };
    $('image-encoder').onchange=async e=>{
      const id=e.target.value, engine=this.state?.image_engine;
      const choice=engine?.encoder_choices?.find(c=>c.id===id);
      if(this.busy||this.pending||!['flux9','flux9_heretic'].includes(engine?.id)||
        !['flux9','flux9_heretic'].includes(id)||!choice?.available||id===engine.id){
        this.encoderControls();return;
      }
      this.encoderPendingId=id;
      try {
        if(await this.action('image-engine/encoder',{id}))this.notify('绘图文字理解设置已保存；下次绘图时使用，不会立即生成。');
      } finally {this.encoderPendingId=null;this.encoderControls();}
    };
    $('use-character').onclick=()=>{
      const role=this.roles.find(r=>r.id===this.editingId);
      if(role?.image){this.useRole(role);$('character-editor').close();}
    };
  }

  values() {
    return this.roles.map(({id,name,description,outfit,personality,style,image,look,framing,voice})=>({id,name,description,outfit,personality,style,image,look,framing,voice}));
  }

  sync(state) {
    this.state=state;this.portrait.engine=state.image_engine; this.busy=!!state.running; this.modelReady=!!state.character_model_ready;
    const roles=state.characters||[];
    const signature=JSON.stringify([roles,this.busy,state.character_id]);
    this.roles=roles;
    this.voice.sync(state);
    if(signature!==this.signature){this.signature=signature;this.render();this.onChange();}
    this.controls();
    if($('character-editor').open)this.preview();
  }

  controls() {
    const disabled=this.busy||this.pending;
    $('add-character').disabled=disabled;
    $('character-fields').disabled=disabled;
    $('save-character').disabled=disabled;
    $('draw-character').disabled=disabled||!this.modelReady;
    $('portrait-version').disabled=disabled;
    $('undo-character').disabled=disabled;
    $('stop-character').hidden=!(this.busy&&(this.state?.task_kind==='voice_preview'||(this.state?.task_kind==='character'&&this.state.character_id===this.editingId)));
    $('stop-character').textContent=this.state?.task_kind==='voice_preview'?'停止试听生成':'停止生成人物';
    $('preview-role-voice').disabled=disabled;
    $('stop-character').disabled=this.state?.status==='stopping'||this.pending;
    $('character-model-status').textContent=this.modelReady?((this.state?.image_engine?.name||'本地绘图')+' · 无需额度'):'本地模型文件未准备完整';
    $('apply-correction').disabled=disabled;
    const referenceAvailable=this.state?.image_engine?.reference_available??this.state?.image_engine?.reference;
    $('portrait-correction').hidden=!referenceAvailable||!this.roles.find(r=>r.id===this.editingId)?.image;
    this.encoderControls();
    this.imageModel.sync(this.state,{busy:disabled});
    this.portrait.update(this.roles.find(r=>r.id===this.editingId),disabled);
  }

  encoderControls() {
    const engine=this.state?.image_engine;
    const choices=(Array.isArray(engine?.encoder_choices)?engine.encoder_choices:[])
      .filter(c=>['flux9','flux9_heretic'].includes(c.id));
    const supported=['flux9','flux9_heretic'].includes(engine?.id)&&choices.length>0;
    $('image-encoder-settings').hidden=!supported;
    const select=$('image-encoder');
    select.disabled=!supported||this.busy||this.pending;
    if(!supported)return;
    const signature=JSON.stringify(choices);
    if(select.dataset.key!==signature){
      select.dataset.key=signature;select.replaceChildren();
      for(const choice of choices){
        const label=choice.label||(choice.id==='flux9'?'标准':'社区实验');
        const option=node('option','',label+(choice.available?'':' · 文件未准备完整'));
        option.value=choice.id;option.disabled=!choice.available;select.append(option);
      }
    }
    select.value=this.encoderPendingId||engine.id;
    const caution='社区实验版效果尚未经过本机生成验证，不保证比标准版更准确。';
    $('image-encoder-note').textContent=this.encoderPendingId?'正在保存设置，不会启动生成…':
      [engine.encoder_note,caution].filter(Boolean).join(' ');
  }

  render() {
    $('character-count').textContent=`${this.roles.length} 个角色 · 不限数量`;
    $('characters').replaceChildren();
    if(!this.roles.length){$('characters').append(node('p','character-empty','还没有角色。点击“新增角色”，创建你的第一个人物。'));return;}
    for(const role of this.roles) {
      const card=node('article','role-card'); card.dataset.roleId=role.id;
      const cover=node('button','role-cover');cover.type='button';cover.setAttribute('aria-label',`编辑${role.name}`);
      if(role.image){const img=node('img','');img.src=role.image;img.alt=role.name;img.loading='lazy';cover.append(img);}
      else cover.append(node('span','',role.name.slice(0,1)));
      cover.onclick=()=>this.open(role);
      const info=node('div','role-info');
      info.append(node('strong','role-name',role.name),node('p','role-description',role.description));
      const active=this.busy&&this.state?.task_kind==='character'&&this.state.character_id===role.id;
      info.append(node('span','role-badge',active?'正在绘制…':role.image?(isCurrent(role)?`${styleNames[role.style]} · 已生成`:'设定已改，形象待更新'):'尚未生成人物'));
      const actions=node('div','role-actions');
      const edit=node('button','text-button','编辑 / 生成');edit.type='button';edit.disabled=this.busy;edit.onclick=()=>this.open(role);
      const duplicate=node('button','text-button','复制');duplicate.type='button';duplicate.disabled=this.busy;
      duplicate.setAttribute('aria-label',`复制${role.name}`);
      duplicate.onclick=()=>this.open({...role,id:newId(),name:role.name.slice(0,25)+'副本',image:null,images:[]});
      const remove=node('button','text-button role-remove','移除');remove.type='button';remove.disabled=this.busy;
      remove.setAttribute('aria-label',`移除${role.name}`);
      remove.onclick=async()=>{
        const ok=await this.action('characters/archive',{id:role.id});
        if(ok){this.lastDeleted=role.id;$('character-undo').hidden=false;$('character-undo-label').textContent=`已移除「${role.name}」`;}
      };
      actions.append(edit,duplicate,remove);info.append(actions);card.append(cover,info);$('characters').append(card);
    }
  }

  open(role=null) {
    if(this.busy||this.pending)return;
    const value=role||{id:newId(),name:'',description:'',outfit:'',personality:'',style:'3d',image:null};
    this.editingId=value.id;
    $('character-editor-title').textContent=this.roles.some(r=>r.id===value.id)?'编辑角色':'新增角色';
    for(const key of ['name','description','outfit','personality','style'])$('role-'+key).value=value[key]||'';
    $('role-style').value=value.style||'3d';
    this.voice.open(value);
    this.portrait.open({...value,framing:value.framing||(role?'half':'full')});
    this.simple=true;this.initialSimple=this.combined(value);$('role-visual').value=this.initialSimple;$('portrait-instruction').value='';this.fieldMode();this.controls();this.preview();$('character-editor').showModal();
    $('role-name').focus();
  }

  legacyFields() {
    const value={id:this.editingId};
    for(const key of ['name','description','outfit','personality','style'])value[key]=$('role-'+key).value.trim();
    return {...value,...this.portrait.fields(),voice:this.voice.value()};
  }

  combined(role) {
    const options=this.portrait.options?.features||[];
    const features=Object.entries(role.look||{}).map(([key,value])=>{if(key==='age')return `年龄：${value}岁`;const field=options.find(f=>f.key===key);return (field?.label||key)+'：'+(field?.options.find(o=>o.value===value)?.label||value);});
    return [role.description,role.outfit,...features].filter(Boolean).join('。');
  }
  fieldMode(){ $('role-simple-field').hidden=!this.simple;$('role-legacy-fields').hidden=this.simple;$('toggle-role-fields').textContent=this.simple?'分项编辑旧设定':'合并为一段描述'; }
  fields(){
    const fields=this.legacyFields();if(!this.simple)return fields;
    const description=$('role-visual').value.trim();
    if(description===this.initialSimple)return fields;
    return {...fields,description,outfit:'',look:{},priorities:[]};
  }

  preview() {
    const role=this.roles.find(r=>r.id===this.editingId);
    $('character-editor-title').textContent=role?'编辑角色':'新增角色';
    const busy=this.busy&&this.state?.task_kind==='character'&&this.state.character_id===this.editingId;
    const preview=$('portrait-image');
    preview.hidden=!role?.image; $('portrait-placeholder').hidden=!!role?.image;
    if(role?.image&&preview.getAttribute('src')!==role.image)preview.src=role.image;
    preview.alt=role?.name||'人物形象';
    const taskFailed=this.state?.task_kind==='character'&&this.state.character_id===this.editingId&&['error','stopped'].includes(this.state.status);
    const message=busy||taskFailed?this.state.message:role?.image?(isCurrent(role,this.fields())?'已保存到本地，请对照设定核对外貌、服装和姿势。': '当前图片对应旧设定；重新绘制后才会更新外貌。'):'填写外貌与服装，点击“保存并生成人物”。';
    $('portrait-status').textContent=message;
    const correction=role?.images?.find(v=>v.image===role.image)?.generation?.edit_instruction;
    if(correction&&!busy&&!taskFailed&&isCurrent(role,this.fields()))$('portrait-status').textContent='本版图片已按“'+correction+'”修改。文本设定未改变；再次全新绘制会按文本设定生成。';
    $('portrait-progress').hidden=!busy;
    $('portrait-progress').value=this.state?.progress||0;
    $('use-character').disabled=!role?.image||this.busy||this.pending;
    $('role-video').hidden=!role?.image;
    $('role-video').href=role?.image?`/create?role=${encodeURIComponent(role.id)}`:'/create';
    const versions=role?.images||[];
    const listKey=JSON.stringify(versions.map(v=>v.image));
    if($('portrait-version').dataset.key!==listKey){
      $('portrait-version').dataset.key=listKey;$('portrait-version').replaceChildren();
      versions.forEach((v,i)=>{const option=node('option','',`形象 ${i+1} · ${styleNames[v.style]}`);option.value=v.image;$('portrait-version').append(option);});
    }
    if(role?.image)$('portrait-version').value=role.image;
    $('portrait-version-field').hidden=!versions.length;
    this.portrait.update(role,this.busy||this.pending);
    this.portrait.inspect(this.fields());
  }

  async action(name,payload={}) {
    if(this.pending)return false;
    this.pending=true;this.controls();
    try {this.applyState(await api.action(name,payload));return true;}
    catch(e){
      this.notify(e.message);
      if($('character-editor').open){$('portrait-issues').hidden=false;$('portrait-issues').textContent=e.message;}
      return false;
    }
    finally{this.pending=false;this.controls();}
  }

  async save(generate) {
    if(!$('character-form').reportValidity()||this.pending||this.busy)return;
    let generation;
    if(generate){
      try{
        generation=this.portrait.generation();
        if(!await this.portrait.validate(this.fields())){
          $('portrait-issues').scrollIntoView({block:'center',behavior:'smooth'});
          this.notify('请先处理标红的设定冲突，再生成图片。');return;
        }
      }
      catch(e){this.notify(e.message);return;}
    }
    const ok=await this.action('characters/save',this.fields());
    if(!ok)return;
    this.notify('角色设定已保存到本地。');
    if(generate)await this.action('characters/generate',{id:this.editingId,...generation});
    else $('character-editor').close();
  }
}

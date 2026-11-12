import * as api from '/api.js';
const $ = id => document.getElementById(id);

export class PortraitControls {
  constructor(notify) {
    this.notify=notify; this.keys=[]; this.strokes=[]; this.role=null; this.disabled=false;
    this.lastInspect=''; this.inspectSerial=0; this.reference=null;this.detailKey='';this.detailSerial=0;
    $('portrait-mode').addEventListener('change',()=>{
      $('portrait-strength').value=$('portrait-mode').value==='local'?65:35;
      this.update(this.role,this.disabled);
    });
    $('portrait-strength').oninput=()=>$('portrait-strength-value').textContent=$('portrait-strength').value+'%';
    $('portrait-quality').onchange=()=>this.update(this.role,this.disabled);
    $('portrait-content-check').onchange=()=>this.update(this.role,this.disabled);
    $('portrait-reuse-seed').onclick=()=>{
      const version=this.version();
      if(version)$('portrait-seed').value=version.seed;
    };
    $('portrait-random-seed').onclick=()=>$('portrait-seed').value='';
    $('portrait-mask-clear').onclick=()=>{this.strokes=[];this.draw();};
    $('portrait-mask-undo').onclick=()=>{this.strokes.pop();this.draw();};
    $('portrait-image').addEventListener('load',()=>{
      const img=$('portrait-image'), canvas=$('portrait-mask');
      canvas.width=img.naturalWidth; canvas.height=img.naturalHeight;
      img.parentElement.style.aspectRatio=`${img.naturalWidth}/${img.naturalHeight}`;
      this.draw();
    });
    const canvas=$('portrait-mask');
    canvas.onpointerdown=e=>{
      if(this.disabled||this.strokes.length>=100)return;
      if(this.strokes.reduce((n,s)=>n+s.points.length,0)>=1900){this.notify('笔迹较多，请清空后使用较大的画笔。');return;}
      e.preventDefault();canvas.setPointerCapture(e.pointerId);
      this.active={size:Number($('portrait-brush').value)/100,points:[this.point(e)]};
      this.strokes.push(this.active);this.draw();
    };
    canvas.onpointermove=e=>{
      if(!this.active||this.disabled)return;
      const point=this.point(e),last=this.active.points.at(-1);
      if(Math.hypot(point[0]-last[0],point[1]-last[1])>.004&&this.strokes.reduce((n,s)=>n+s.points.length,0)<2000){this.active.points.push(point);this.draw();}
    };
    canvas.onpointerup=canvas.onpointercancel=canvas.onlostpointercapture=()=>{this.active=null;};
  }
  configure(options) {
    if(this.keys.length)return;
    if(!options)throw new Error('请重新启动制作器以加载新版角色功能。');
    this.options=options;
    const root=$('portrait-feature-fields');
    const age=document.createElement('label');age.className='field';
    const ageLabel=document.createElement('span');ageLabel.textContent='年龄';
    const input=document.createElement('input');input.id='look-age';input.type='number';input.min='1';input.max='120';input.step='1';input.placeholder='例如：25';
    age.append(ageLabel,input);root.append(age);
    this.keys=['age'];
    for(const field of options.features){
      this.keys.push(field.key);
      const label=document.createElement('label');label.className='field';
      const title=document.createElement('span');title.textContent=field.label;
      const input=document.createElement(field.key==='gender'?'select':'input');input.id='look-'+field.key;
      if(field.key==='gender'){
        for(const item of [{value:'',label:'未指定'},...field.options]){
          const option=document.createElement('option');option.value=item.value;option.textContent=item.label;input.append(option);
        }
        input.addEventListener('change',()=>this.suggestions());
      }else{
        input.type='text';input.maxLength=80;input.placeholder='自由输入，也可点选下方建议';
      }
      label.append(title,input);
      if(field.key!=='gender'){
        const tips=document.createElement('span');tips.className='feature-suggestions';tips.id='suggest-'+field.key;label.append(tips);
      }
      root.append(label);
    }
    this.suggestions();
    for(const item of options.priorities||[]){
      const label=document.createElement('label');label.className='priority-choice';
      const input=document.createElement('input');input.type='checkbox';input.value=item.value;input.name='portrait-priority';
      input.onchange=()=>{
        if(document.querySelectorAll('[name="portrait-priority"]:checked').length>3){input.checked=false;this.notify('最多选择三项，优先突出最重要的细节。');}
      };
      label.append(input,document.createTextNode(item.label));$('portrait-priorities').append(label);
    }
  }
  suggestions() {
    const gender=$('look-gender').value||'generic';
    $('portrait-gender-hint').textContent=({female:'女性常用建议',male:'男性常用建议',generic:'通用建议'}[gender]||'通用建议')+' · 所有文字均可自由修改，切换人物类型不会清空已填内容。';
    for(const field of this.options.features){
      if(field.key==='gender')continue;
      const tips=$('suggest-'+field.key);tips.replaceChildren();
      const words=this.options.suggestions?.[gender]?.[field.key]||field.options.slice(0,3).map(o=>o.label);
      for(const word of words){
        const button=document.createElement('button');button.type='button';button.textContent=word;
        button.onclick=()=>{const input=$('look-'+field.key);input.value=word;input.dispatchEvent(new Event('input',{bubbles:true}));};
        tips.append(button);
      }
    }
  }
  open(role) {
    $('role-framing').value=role.framing||(role.image?'half':'full');
    for(const key of this.keys){
      const value=role.look?.[key]??'';
      const field=this.options.features.find(f=>f.key===key);
      $('look-'+key).value=key==='gender'||key==='age'?value:(field?.options.find(o=>o.value===value)?.label||value);
    }
    this.suggestions();
    const priorities=role.priorities??this.options.default_priorities??[];
    document.querySelectorAll('[name="portrait-priority"]').forEach(input=>input.checked=priorities.includes(input.value));
    this.detailKey='';++this.detailSerial;$('portrait-audit').hidden=true;
    $('portrait-mode').value='new';$('portrait-seed').value='';$('portrait-strength').value=35;
    const selected=role.images?.find(v=>v.image===role.image)?.generation||{};
    $('portrait-quality').value=selected.quality||'hd';
    $('portrait-pose-guide').checked=selected.pose_guide??true;
    $('portrait-face-refine').checked=selected.face_refine??true;
    $('portrait-content-check').checked=selected.content_check??false;
    $('portrait-quality-info').textContent='';
    this.strokes=[];this.active=null;this.lastInspect='';this.reference=null;
    ++this.inspectSerial;clearTimeout(this.timer);$('portrait-issues').hidden=true;
    this.update(role,false);this.draw();
  }
  fields() {
    const look={};
    for(const key of this.keys){
      const value=$('look-'+key).value.trim();
      const field=this.options.features.find(f=>f.key===key);
      if(value)look[key]=key==='age'?Number(value):(field?.options.find(o=>o.label===value)?.value||value);
    }
    const priorities=[...document.querySelectorAll('[name="portrait-priority"]:checked')].map(input=>input.value);
    return {framing:$('role-framing').value,look,priorities};
  }
  version() {return this.role?.images?.find(v=>v.image===this.role.image);}
  update(role,disabled) {
    this.role=role;this.disabled=disabled;
    const available=!!role?.image,mode=$('portrait-mode').value;
    const native=!!this.engine&&this.engine.id!=='legacy'&&mode!=='local';
    for(const option of $('portrait-mode').options)option.disabled=option.value!=='new'&&(!available||
      (option.value==='reference'&&this.engine?.reference_available===false&&this.engine?.id!=='legacy'));
    $('portrait-reuse-seed').disabled=disabled||!this.version();
    $('portrait-strength-field').hidden=mode==='new'||native;
    $('portrait-quality-fields').hidden=mode!=='new'||native;
    $('portrait-face-refine').disabled=disabled||$('portrait-quality').value!=='hd';
    $('portrait-content-check').disabled=disabled;
    $('portrait-content-check-hint').textContent=$('portrait-content-check').checked
      ?'当前开启。图片只在本机检查；若命中，将停止并且不保存、不替换现有形象。它不会改变绘图模型是否补画衣物。'
      :'当前关闭。绘图过程完全不加载成人敏感内容检查器。模型仍可能自行增加、减少或改变服装。';
    $('portrait-strength-value').textContent=$('portrait-strength').value+'%';
    $('portrait-mask').hidden=mode!=='local'||!available;
    $('portrait-mask-tools').hidden=mode!=='local'||!available;
    for(const id of ['portrait-brush','portrait-mask-undo','portrait-mask-clear'])$(id).disabled=disabled;
    $('portrait-mask').style.pointerEvents=disabled?'none':'auto';
    $('portrait-mode-hint').textContent={new:'根据设定绘制新图。改变构图或生成高清版本时使用此方式。',reference:'以右侧当前图片为基础，保留原图尺寸。幅度越低越接近原图，越高变化越明显；不能保证脸部完全不变。',local:'在右侧涂抹要改的头发或服装，并在描述中写明目标效果。保留原图尺寸，未涂抹的区域保留原图。'}[mode];
    if(native){
      const size=this.engine.native_size?.join('×')||'原生';
      $('portrait-mode-hint').textContent=mode==='new'
        ?`${this.engine.name||'当前模型'} · 生成 ${size} 画面。${this.engine.id==='sdxl'?'中文描述会在本机翻译后绘制，可在生成记录核对实际提示词。':'使用完整描述绘制，请核对实际人物细节。'}`
        :`${this.engine.id==='sdxl'?'参考修改由现有 FLUX 模型处理。':''}使用参考图理解修改要求，不需要设置修改幅度；请核对人物身份和细节。`;
    }
    if(mode==='local'&&this.engine?.id!=='legacy')$('portrait-mode-hint').textContent+=' 此模式使用兼容局部编辑模型。';
    const version=this.version();
    $('portrait-seed-info').textContent=version?`当前图片种子：${version.seed} · ${{head:'头像',half:'半身',full:'全身'}[version.framing||'half']}`:'';
    if(this.reference!==role?.image){this.reference=role?.image;this.strokes=[];this.active=null;this.draw();}
    this.audit(role);
  }
  async audit(role) {
    const key=role?.image||'';
    if(key===this.detailKey)return;
    this.detailKey=key;const serial=++this.detailSerial;
    const panel=$('portrait-audit');panel.hidden=!key;
    $('portrait-audit-rows').replaceChildren();$('portrait-audit-note').textContent='正在读取本次绘制依据…';
    if(!key)return;
    try{
      const detail=await api.action('characters/detail',{id:role.id,image:key});
      if(serial!==this.detailSerial)return;
      const records=detail.translation?.records||[];
      const quality=detail.quality;
      const content=detail.content_check;
      $('portrait-quality-info').textContent=detail.width?`${detail.width}×${detail.height} · ${quality?.hd_refinement?'已做高清细化':'保留原始画幅'}${quality?.pose_guidance?(quality.pose_preset==='front-cross-legged-v1'?' · 已用盘腿姿势参考':' · 已用站姿参考'):''}${quality?.face_refinement?' · 已做面部细化':''}${quality?.local_refinement?' · 已细化'+(quality.local_refinement.area==='shoes'?'鞋子':'面部'):''} · 内容检查${content?.enabled?'已开启':'已关闭'}${quality?.notes?.length?'。'+quality.notes.join(' '):''}`:'';
      const priorityNames=(detail.plan?.priorities||[]).map(k=>this.options.priorities.find(p=>p.value===k)?.label||k);
      $('portrait-audit-note').textContent=records.length?`待人工核对：以下为原文与理解结果，不代表每一项都已画对。${priorityNames.length?'优先落实：'+priorityNames.join('、')+'。':''}${(detail.plan?.warnings||[]).join(' ')}`:'旧版本没有逐项翻译记录，重新绘制后会显示。';
      if(detail.engine){
        const translated=detail.prompt_translation?.applied===true;
        const translationNote=translated?'中文描述已在本机翻译，下面保留原文与实际绘图提示词。'
          :detail.prompt_translation?.applied===false?'使用原文绘制。':'旧记录未保存是否翻译，请以已记录的提示词为准。';
        const route=detail.reference_route==='flux_reference'?'本次参考图任务已交给 FLUX 处理。':'';
        $('portrait-audit-note').textContent=`${detail.model||detail.engine} · ${route}${translationNote} 请人工核对画面是否符合设定。`;
        const original=document.createElement('p');original.textContent=detail.prompt||'';$('portrait-audit-rows').append(original);
        if(detail.generation_prompt&&detail.generation_prompt!==detail.prompt){
          const actual=document.createElement('div');actual.className='audit-row';
          const label=document.createElement('strong');label.textContent='实际绘图提示词';
          const prompt=document.createElement('p');prompt.textContent=detail.generation_prompt;
          actual.append(label,prompt);$('portrait-audit-rows').append(actual);
        }
      }
      const labels={description:'外貌补充',outfit:'服装与配饰',...Object.fromEntries(this.options.features.map(f=>[f.key,f.label]))};
      for(const row of records){
        const item=document.createElement('div');item.className='audit-row';
        const label=document.createElement('strong');label.textContent=labels[row.field]||row.field;
        const source=document.createElement('p');source.textContent=row.source;
        const translation=document.createElement('small');translation.textContent=row.english;
        item.append(label,source,translation);$('portrait-audit-rows').append(item);
      }
      for(const row of detail.translation?.excluded_records||[]){
        const item=document.createElement('div');item.className='audit-row';
        const label=document.createElement('strong');label.textContent='未用于绘图 · '+(labels[row.field]||row.field);
        const source=document.createElement('p');source.textContent=row.source;
        const reason=document.createElement('small');reason.textContent=row.reason;
        item.append(label,source,reason);$('portrait-audit-rows').append(item);
      }
    }catch(e){if(serial===this.detailSerial)$('portrait-audit-note').textContent=e.message;}
  }
  generation() {
    const mode=$('portrait-mode').value;
    if(mode==='reference'&&this.engine?.reference_available===false&&this.engine?.id!=='legacy')throw new Error('参考图绘图模型尚未准备好，请检查 FLUX 文件。');
    if(mode==='local'&&!this.strokes.length)throw new Error('请先在右侧人物图上涂抹需要修改的区域。');
    return {mode,seed:$('portrait-seed').value,reference:this.role?.image,strength:Number($('portrait-strength').value)/100,strokes:this.strokes,
      quality:$('portrait-quality').value,pose_guide:$('portrait-pose-guide').checked,face_refine:$('portrait-face-refine').checked,
      content_check:$('portrait-content-check').checked};
  }
  inspect(fields) {
    const signature=JSON.stringify(fields);
    if(this.lastInspect===signature)return;
    this.lastInspect=signature;clearTimeout(this.timer);const serial=++this.inspectSerial;
    this.timer=setTimeout(async()=>{
      if(!fields.description&&!Object.keys(fields.look||{}).length){$('portrait-issues').hidden=true;return;}
      try{
        const result=await api.action('characters/inspect',{...fields,name:fields.name||'未命名角色'});
        if(serial!==this.inspectSerial)return;
        this.showIssues(result.issues);
      }catch(e){if(serial===this.inspectSerial){$('portrait-issues').hidden=false;$('portrait-issues').textContent=e.message;}}
    },220);
  }
  showIssues(issues) {
    const box=$('portrait-issues');box.replaceChildren();box.hidden=!issues.length;
    for(const issue of issues){
      const row=document.createElement('div');row.className='portrait-issue';
      const p=document.createElement('p');p.className=issue.severity;p.textContent=issue.message;row.append(p);
      for(const fix of issue.fixes||[]){
        const button=document.createElement('button');button.type='button';button.className='text-button';button.textContent=fix.label;
        button.onclick=()=>{
          if(this.disabled)return;
          if(fix.kind==='move_speech'){
            const notes=$('role-personality');
            const merged=[notes.value.trim(),fix.moved_text].filter(Boolean).join('\n');
            if(merged.length>notes.maxLength){this.notify('创作备注超过字数上限，请先精简备注；原文未改动。');return;}
            notes.value=merged;$('role-outfit').value=fix.outfit;
          }else if(fix.kind==='clear_look'&&this.keys.includes(fix.key)){
            $('look-'+fix.key).value='';
          }else return;
          $('role-outfit').dispatchEvent(new Event('input',{bubbles:true}));
          this.notify('已修改表单草稿，点击保存后生效。');
        };
        row.append(button);
      }
      box.append(row);
    }
  }
  async validate(fields) {
    clearTimeout(this.timer);++this.inspectSerial;
    const result=await api.action('characters/inspect',{...fields,name:fields.name||'未命名角色'});
    this.showIssues(result.issues);
    return !result.issues.some(issue=>issue.severity==='error');
  }
  point(event) {
    const rect=$('portrait-mask').getBoundingClientRect();
    return [Math.max(0,Math.min(1,(event.clientX-rect.left)/rect.width)),Math.max(0,Math.min(1,(event.clientY-rect.top)/rect.height))].map(v=>Number(v.toFixed(4)));
  }
  draw() {
    const canvas=$('portrait-mask'),ctx=canvas.getContext('2d');ctx.clearRect(0,0,canvas.width,canvas.height);
    ctx.strokeStyle='#7162ed';ctx.fillStyle='#7162ed';ctx.lineCap='round';ctx.lineJoin='round';
    for(const stroke of this.strokes){
      ctx.lineWidth=stroke.size*canvas.width;ctx.beginPath();
      stroke.points.forEach(([x,y],i)=>i?ctx.lineTo(x*canvas.width,y*canvas.height):ctx.moveTo(x*canvas.width,y*canvas.height));ctx.stroke();
      const [x,y]=stroke.points[0];ctx.beginPath();ctx.arc(x*canvas.width,y*canvas.height,ctx.lineWidth/2,0,2*Math.PI);ctx.fill();
    }
  }
}

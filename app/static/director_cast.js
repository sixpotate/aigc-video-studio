const element=(tag,className='',text)=>{const node=document.createElement(tag);node.className=className;if(text!==undefined)node.textContent=text;return node;};
export const roleFor=(shot,id,roles)=>{const role=roles.find(r=>r.id===id)||shot.cast?.find(m=>m.role.id===id)?.role||(shot.role?.id===id?shot.role:null);if(!role)return null;const pinned=shot.reference_images?.[id];return pinned?{...role,image:pinned}:role;};
export function normalizeProject(project){
  project.export??={ratio:'9:16',resolution:'540'};
  project.captions??={speaker_name:false};
  project.sound??={track:'none',level:-18,duck:true,fade:1};project.script??='';project.aliases??='';
  for(const shot of project.shots){shot.role_ids??=[shot.role_id];shot.speaker_id??=shot.role_id;shot.actor_actions??={};shot.duration??=null;shot.voice_mode??='shot';shot.speech_kind??=shot.speaker_id==='narrator'?'narration':'dialogue';shot.scene_image??='';shot.scene_description??='';shot.visual_only??=false;shot.onscreen_text??='';shot.subtitle_name??='';shot.reuse_motion_from??='';shot.effect??='none';shot.effect_time??=0;shot.effect_level??=-12;shot.motion_seconds??=3;}
  return project;
}
export function castEditor(shot,roles,onChange){
  const wrap=element('section','cast-editor');
  wrap.append(element('strong','',`同框角色 · ${shot.role_ids.length}/4`),element('p','hint','按画面从左到右排列，每人的动作单独填写。多人对白建议使用近景，并先预览同框参考。'));
  const list=element('div','cast-list');
  shot.role_ids.forEach((id,index)=>{
    const role=roleFor(shot,id,roles),row=element('div','cast-member');
    const head=element('div','cast-member-head');
    if(role?.image){const image=element('img');image.src=role.image;image.alt=role.name;image.loading='lazy';head.append(image);}
    head.append(element('span','',`${index+1}. ${role?.name||'角色不可用'}`));
    for(const [label,delta] of [['←',-1],['→',1]]){
      const button=element('button','editor-input',label);button.type='button';button.setAttribute('aria-label',`${role?.name||'角色'}向${delta<0?'左':'右'}移动`);
      button.dataset.unavailable=String(index+delta<0||index+delta>=shot.role_ids.length);
      button.onclick=()=>{const next=index+delta;if(next<0||next>=shot.role_ids.length)return;[shot.role_ids[index],shot.role_ids[next]]=[shot.role_ids[next],shot.role_ids[index]];shot.face_box=null;onChange('role_ids');};head.append(button);
    }
    const remove=element('button','editor-input','移除');remove.type='button';remove.dataset.unavailable=String(shot.role_ids.length===1);remove.setAttribute('aria-label',`移除同框角色${role?.name||''}`);
    remove.onclick=()=>{if(shot.role_ids.length<2)return;shot.role_ids=shot.role_ids.filter(r=>r!==id);delete shot.actor_actions[id];if(shot.reference_images)delete shot.reference_images[id];if(shot.speaker_id===id)shot.speaker_id=shot.role_ids[0];shot.role_id=shot.speaker_id==='narrator'?shot.role_ids[0]:shot.speaker_id;shot.face_box=null;onChange('role_ids');};head.append(remove);
    const label=element('label','',`${role?.name||'该角色'}的动作`),input=element('textarea','editor-input');input.rows=2;input.maxLength=160;input.value=shot.actor_actions[id]||'';input.placeholder=index===0?'例如：抬起右手，点头说明。':'例如：看向左边的人，微笑回应。';input.setAttribute('aria-label',`${role?.name||'该角色'}的动作`);
    input.oninput=()=>{shot.actor_actions[id]=input.value;onChange('actor_actions');};label.append(input);row.append(head,label);list.append(row);
  });
  wrap.append(list);
  const addRow=element('div','cast-add'),select=element('select','editor-input');select.setAttribute('aria-label','添加同框角色');
  const available=roles.filter(r=>r.image&&!shot.role_ids.includes(r.id));
  for(const role of available){const option=element('option','',role.name);option.value=role.id;select.append(option);}
  const unavailable=shot.role_ids.length>=4||!available.length;select.dataset.unavailable=String(unavailable);
  const add=element('button','button editor-input','＋ 加入同框');add.type='button';add.dataset.unavailable=String(unavailable);
  add.onclick=()=>{if(shot.role_ids.length>=4||!select.value)return;shot.role_ids.push(select.value);shot.face_box=null;onChange('role_ids');};addRow.append(select,add);wrap.append(addRow);
  const speakerLabel=element('label','','当前说话人'),speaker=element('select','editor-input');speaker.setAttribute('aria-label','当前说话人');speaker.dataset.key='speaker_id';
  for(const id of [...shot.role_ids,'narrator']){const name=id==='narrator'?'旁白 · 不给人物配口型':roleFor(shot,id,roles)?.name||'角色不可用';const option=element('option','',name);option.value=id;speaker.append(option);}
  speaker.value=shot.speaker_id;speaker.onchange=()=>{shot.speaker_id=speaker.value;shot.role_id=speaker.value==='narrator'?shot.role_ids[0]:speaker.value;shot.face_box=null;onChange('speaker_id');};speakerLabel.append(speaker);wrap.append(speakerLabel,element('p','hint','切换说话人后，请核对下方的声音；旁白不会给人物配口型。'));
  return wrap;
}

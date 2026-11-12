const el=(tag,text)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;return node;};
const cameraNames={close:'近景',medium:'中景',wide:'全景',push:'推近',reaction:'反应近景',extreme_close:'特写'};
export function showStoryOverview(state,focus){
  if(!state.project)return;
  const shots=state.project.shots,rows=document.getElementById('story-overview-rows');rows.replaceChildren();
  const ready=shots.filter(s=>s.result?.video).length,target=shots.reduce((sum,s)=>sum+(s.duration||0),0),actual=shots.reduce((sum,s)=>sum+(s.result?.seconds||0),0);
  document.getElementById('story-overview-summary').textContent=`${ready}/${shots.length} 镜完成 · 目标 ${target.toFixed(1)} 秒`;
  const warnings=[];if(shots.some(s=>!s.scene_image))warnings.push('部分镜头未绑定背景图，将使用角色原图或素色布景');
  if(shots.some(s=>s.reuse_motion_from))warnings.push('部分镜头复用已有动作');
  const failed=shots.filter(s=>s.result?.error).length;if(failed)warnings.push(failed+' 个镜头待处理，请查看对应镜头的失败原因');
  if(shots.some(s=>s.duration>(s.motion_seconds||3)))warnings.push('部分镜头会循环基础动作以匹配对白');
  const targetSeconds=state.project.authoring?.target_seconds;
  document.getElementById('story-preflight').textContent=[targetSeconds?`本集创作目标 ${targetSeconds} 秒`:'',`已完成配音 ${actual.toFixed(1)} 秒`,...warnings].filter(Boolean).join('；')+'。';
  shots.forEach((shot,index)=>{const tr=el('tr'),number=el('td'),button=el('button',String(index+1).padStart(2,'0'));button.className='text-button';button.onclick=()=>focus(shot.id);number.append(button);
    const names=shot.role_ids.map(id=>state.roles.find(r=>r.id===id)?.name||'角色').join('、');
    const cells=[`${shot.scene_name||shot.scene_description||'未命名场景'}${shot.story_beat?' / '+shot.story_beat:''}`,`${names}：${shot.text||'无对白'}`,cameraNames[shot.camera]||shot.camera,shot.result?.seconds?`${shot.result.seconds.toFixed(1)} 秒 · 实际`:`${shot.duration||'自动'} 秒 · 目标`,shot.result?.video?'镜头就绪':shot.result?.audio?'配音就绪':'待制作'];
    tr.append(number,...cells.map(text=>el('td',text)));rows.append(tr);});
}

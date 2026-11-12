import * as api from '/api.js';
export async function loadMaterialLibrary(){
  const $=id=>document.getElementById(id),response=await api.request('/api/sound-library'),data=await response.json();
  if(!response.ok||!data.count)return;
  $('material-library').hidden=false;$('material-count').textContent=`· ${data.count} 条本地音频`;
  for(const [value,label] of Object.entries(data.categories)){const node=document.createElement('option');node.value=value;node.textContent=label;$('material-category').append(node);}
  function preview(){
    const item=data.items.find(value=>value.id===$('material-item').value),audio=$('material-audio');
    audio.pause();audio.removeAttribute('src');if(!item)return;audio.src=item.url;
    $('material-license').replaceChildren(document.createTextNode(`${item.seconds.toFixed(1)} 秒 · ${item.license} · `));
    const source=document.createElement('a');source.textContent='查看素材来源';source.href=item.source;source.target='_blank';source.rel='noopener noreferrer';$('material-license').append(source);
  }
  function category(){
    $('material-item').replaceChildren();
    for(const item of data.items.filter(item=>item.category===$('material-category').value)){const node=document.createElement('option');node.value=item.id;node.textContent=item.name;$('material-item').append(node);}
    preview();
  }
  $('material-category').value=data.categories.metal?'metal':Object.keys(data.categories)[0];
  $('material-category').onchange=category;$('material-item').onchange=preview;category();
}

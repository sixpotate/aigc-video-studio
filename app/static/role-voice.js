import * as api from '/api.js';
const $=id=>document.getElementById(id);

// Fixed-text previews never save the character or regenerate its portrait.
export class RoleVoice {
  constructor({notify,applyState}) {
    this.notify=notify;this.applyState=applyState;this.cache={};this.pending=null;this.selected='Serena';
    this.ready=api.getConfig().then(config=>{
      this.details=config.voice_details||{};
      const processed=Object.values(this.details).filter(value=>value.processing).length;
      $('voice-count').textContent=`${Object.keys(this.details).length-processed} 种基础音色 + ${processed} 种处理预设`;
      for(const [value,label] of Object.entries(config.voices)){
        const option=document.createElement('option');option.value=value;option.textContent=label;$('role-voice').append(option);
      }
      $('role-voice').value=this.selected;this.show();
    }).catch(e=>notify(e.message));
    $('role-voice').onchange=()=>{this.selected=$('role-voice').value;this.pending=null;this.show();};
    $('preview-role-voice').onclick=()=>this.preview();
    $('character-editor').addEventListener('close',()=>{$('role-voice-audio').pause();this.pending=null;});
  }
  open(role){this.selected=role.voice||(role.look?.gender==='male'?'Dylan':'Serena');this.pending=null;$('role-voice').value=this.selected;this.show();}
  value(){return this.selected;}
  show(){
    const audio=$('role-voice-audio'),url=this.cache[this.selected];
    if(audio.getAttribute('src')!==url){audio.pause();if(url)audio.src=url;else audio.removeAttribute('src');}
    audio.hidden=!url;
    $('role-voice-hint').textContent=`${this.details?.[this.selected]?.native||'本地音色'} · 可说中文；跨语种音色可能带口音。`;
    $('preview-role-voice').textContent=url?'▶ 试听音色':'生成试听';
    $('role-voice-status').textContent=this.pending?'正在本地制作试听，首次加载需要等待…':url?'试听已缓存在本机。':'首次试听由本地模型生成，无需联网。';
  }
  sync(state){
    this.cache=state.voice_previews||{};
    const ready=this.pending&&this.cache[this.pending];
    if(this.pending&&!state.running&&!ready){this.pending=null;this.notify(state.message||'试听生成未完成。');}
    this.show();
    if(ready){this.pending=null;this.show();if($('character-editor').open)$('role-voice-audio').play().catch(()=>this.notify('试听已就绪，点击播放器播放。'));}
  }
  async preview(){
    await this.ready;
    if(this.cache[this.selected]){$('role-voice-audio').currentTime=0;await $('role-voice-audio').play().catch(e=>this.notify(e.message));return;}
    this.pending=this.selected;this.show();$('preview-role-voice').disabled=true;
    try{this.applyState(await api.action('voices/preview',{voice:this.selected}));}
    catch(e){this.pending=null;this.show();$('preview-role-voice').disabled=false;this.notify(e.message);}
  }
}

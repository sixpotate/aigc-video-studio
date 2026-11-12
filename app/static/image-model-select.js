// Both creation screens share the same server-owned, global model setting.
export class ImageModelSelect {
  constructor({select,note,save,notify=()=>{}}) {
    this.select=select;this.note=note;this.save=save;this.notify=notify;
    this.status=null;this.busy=false;this.pendingId=null;
    select.addEventListener('change',event=>this.change(event));
    this.render();
  }

  sync(status,{busy=false}={}) {
    this.status=status;this.busy=busy||!!status?.running;this.render();
  }

  choices() {
    const choices=this.status?.image_engine?.engine_choices;
    const seen=new Set();
    return (Array.isArray(choices)?choices:[]).filter(choice=>{
      if(!choice||typeof choice.id!=='string'||!choice.id||seen.has(choice.id))return false;
      seen.add(choice.id);return true;
    });
  }

  currentId() {
    return this.status?.image_engine?.selection_id||this.status?.image_engine?.id||'';
  }

  render() {
    const engine=this.status?.image_engine,choices=this.choices();
    const selected=this.pendingId||this.currentId();
    const key=JSON.stringify([choices,selected,engine?.name]);
    if(key!==this.key) {
      this.key=key;this.select.replaceChildren();
      for(const choice of choices) {
        const option=document.createElement('option');
        option.value=choice.id;option.disabled=choice.available!==true;
        option.textContent=(choice.label||choice.id)+(option.disabled?' · 文件未准备完整':'');
        this.select.append(option);
      }
      if(!choices.some(choice=>choice.id===selected)) {
        const option=document.createElement('option');
        option.value=selected;option.textContent=engine?.name||'正在读取可选模型…';option.disabled=true;
        this.select.append(option);
      }
    }
    this.select.value=selected;
    this.select.disabled=this.busy||this.pendingId!==null||!choices.some(choice=>choice.available===true);
    this.select.setAttribute('aria-busy',String(this.pendingId!==null));
    this.note.textContent=this.pendingId!==null?'正在保存绘图模型设置，不会启动生成…':
      [engine?.selection_note,'这是全局设置。切换只保存设置，不会开始生成；已有图片不变。'].filter(Boolean).join(' ');
  }

  async change(event) {
    // This setting is not part of the story draft or character fields.
    event?.stopPropagation();
    const id=this.select.value,choice=this.choices().find(item=>item.id===id);
    if(this.busy||this.pendingId!==null||choice?.available!==true||id===this.currentId()) {
      this.render();return;
    }
    this.pendingId=id;this.render();
    try {
      // Hosts apply the returned snapshot and lock their other controls while saving.
      if(await this.save(id))this.notify('绘图模型已保存；下次绘图时使用，不会立即生成。');
    } catch(error) {
      this.notify(error.message||'绘图模型设置保存失败，请重试。');
    } finally {
      this.pendingId=null;this.render();
    }
  }
}

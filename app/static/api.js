// All HTTP and download behavior stays outside the view layer.
let token = '';
function showRuntimeSafety(value) {
  if (!value || typeof document === 'undefined') return;
  let banner = document.getElementById('runtime-safety');
  if (!banner) {
    banner = document.createElement('section');
    banner.id = 'runtime-safety';
    banner.setAttribute('role', 'status');
    banner.setAttribute('aria-live', 'polite');
    banner.style.cssText = 'box-sizing:border-box;margin:16px auto;padding:16px 20px;max-width:1440px;border:1px solid #e2c58b;border-radius:10px;background:#fff9ec;color:#503d18;line-height:1.6';
    const heading = document.createElement('strong');
    const reason = document.createElement('p');
    reason.style.margin = '6px 0';
    const note = document.createElement('small');
    banner.append(heading, reason, note);
    const main = document.querySelector('main');
    if (main) main.before(banner); else document.body.prepend(banner);
  }
  banner.hidden = !value.blocked;
  banner.children[0].textContent = '生成已暂停，需要检查电脑稳定性';
  banner.children[1].textContent = value.reason || '上次重负载任务异常中断，已保留现场。';
  banner.children[2].textContent = '可继续编辑、查看和下载已有作品。排查并确认稳定后再恢复生成；重启软件不会自动解除暂停。';
}
export async function request(path, data) {
  const response = await fetch(path, data === undefined ? {cache:'no-store'} : {
    method:'POST', headers:{'Content-Type':'application/json','X-Local-Token':token}, body:JSON.stringify(data)
  });
  if (!response.ok) {
    const detail = await response.json().catch(()=>({}));
    showRuntimeSafety(detail.runtime_safety);
    throw new Error(detail.error || `请求失败（${response.status}）`);
  }
  return response;
}
export async function getConfig() {
  const config = await (await request('/api/config')).json();
  token = config.token;
  return config;
}
async function readState(response) {
  const value = await response.json();
  showRuntimeSafety(value.runtime_safety);
  return value;
}
export async function state() {return readState(await request('/api/status'));}
export async function action(name, payload={}) {
  const requestedAt=Date.now();
  const result=await readState(await request(`/api/${name}`, payload));
  if ((name==='director/generate'||name==='story/produce') && result.running && result.task_kind==='director')
    rememberTaskStart(result, requestedAt, 'request');
  return result;
}

// The currently running job predates this feature; its time comes from its job file.
const EXISTING_TASK_START={'38afc4e0a68c4c0585444b98bb0a6545':1793439403831};
const TIME_KEY='aigc-director-task-time-v1';
let memoryStart=null;
function taskId(value) {
  const id=String(value?.director_work||'').split(/[\\/]/).pop();
  return /^[a-f0-9]{32}$/.test(id)?id:null;
}
function readTaskStart(id) {
  try {const value=JSON.parse(localStorage.getItem(TIME_KEY)||'null');if(value?.id===id)return value;} catch {}
  return memoryStart?.id===id?memoryStart:null;
}
function rememberTaskStart(value,ms,source) {
  const id=taskId(value);
  if(!id||!Number.isFinite(ms))return null;
  const record={id,ms,source};memoryStart=record;
  try {localStorage.setItem(TIME_KEY,JSON.stringify(record));} catch {}
  return record;
}
function elapsedText(ms) {
  const total=Math.max(0,Math.floor(ms/1000)),h=Math.floor(total/3600),m=Math.floor(total%3600/60),s=total%60;
  return (h?`${h}小时 `:'')+(h||m?`${m}分 `:'')+`${s}秒`;
}
export function createElapsedIndicator(node) {
  let active=null,finished=null;
  function render() {
    if(!node)return;
    const item=active||finished;
    node.hidden=!item;
    if(!item)return;
    const label=item.source==='observed'?'本页面已观察':'本次生成已用';
    node.textContent=label+' '+elapsedText((item.end??Date.now())-item.ms);
  }
  const timer=setInterval(render,1000);
  return {
    update(value) {
      const id=taskId(value);
      if(value?.running && value.task_kind==='director' && id) {
        const server=Number(value.task_started_at)*1000;
        const now=Date.now();let record;
        if(Number.isFinite(server)&&server>946684800000&&server<=now+5000)record=rememberTaskStart(value,server,'server');
        else if(EXISTING_TASK_START[id])record=rememberTaskStart(value,EXISTING_TASK_START[id],'record');
        else record=readTaskStart(id)||rememberTaskStart(value,now,'observed');
        active=record;finished=null;
      } else if (!value?.running && active) {
        finished={...active,end:Date.now()};active=null;
      } else if (value?.running) {active=null;finished=null;}
      render();
    },
    dispose(){clearInterval(timer);}
  };
}
export async function exportImages(project, ids) {
  const response = await request('/api/export', {project_id:project.id, ids});
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement('a');
  link.href = url;
  link.download = `${project.title.replace(/[<>:"/\\|?*]/g,'_')}_分镜图片.zip`;
  document.body.append(link); link.click(); link.remove();
  setTimeout(()=>URL.revokeObjectURL(url), 30000);
}

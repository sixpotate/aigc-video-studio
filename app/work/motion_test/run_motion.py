import os,sys,pathlib,time,json,argparse,threading,subprocess,hashlib,tempfile

def select_t5_weights(models):
 """Use the verified lazy checkpoint when installed; never silently fall back on damage."""
 original=models/'models_t5_umt5-xxl-enc-fp8.pth'
 lazy=models/'umt5-xxl-fp8-lazy.safetensors'
 marker=models/'umt5-xxl-fp8-lazy.validation.json'
 if not lazy.exists() and not marker.exists():return original,False
 if not lazy.is_file() or not marker.is_file():raise RuntimeError('低内存文本编码器文件或校验记录缺失，已暂停；请重新验证模型。')
 try:
  value=json.loads(marker.read_text(encoding='utf-8'));stat=lazy.stat()
  valid=(value.get('version')==1 and value.get('filename')==lazy.name and
    value.get('size')==stat.st_size and value.get('mtime_ns')==stat.st_mtime_ns and
    isinstance(value.get('sha256'),str) and len(value['sha256'])==64 and
    all(c in '0123456789abcdef' for c in value['sha256']))
 except (OSError,ValueError,TypeError):valid=False
 if not valid:raise RuntimeError('低内存文本编码器校验状态发生变化，已暂停；请重新验证模型。')
 return lazy,True

root=pathlib.Path(__file__).resolve().parent
workspace=root.parent.parent
sys.path.insert(0,str(root/'LightX2V-main'))
for k,v in {'TRITON_CACHE_DIR':'triton-cache','TORCHINDUCTOR_CACHE_DIR':'torch-cache','HF_HOME':'hf-cache','TORCH_HOME':'torch-home'}.items():os.environ[k]=str(root/v)
os.environ.update(DTYPE='BF16',LOGURU_LEVEL='INFO',TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTORCH_CUDA_ALLOC_CONF='')
p=argparse.ArgumentParser();p.add_argument('--name',default='motion_v1');p.add_argument('--frames',type=int,default=49);p.add_argument('--height',type=int,default=832);p.add_argument('--width',type=int,default=480);p.add_argument('--seed',type=int,default=42);p.add_argument('--tiny',action='store_true');p.add_argument('--encode-only',action='store_true');p.add_argument('--cached',action='store_true');p.add_argument('--prompt-file',required=True);p.add_argument('--image',required=True);a=p.parse_args()
models=root/'models/distill_fp8'
t5_path,t5_lazy=select_t5_weights(models)
out=workspace/'outputs/motion_test';out.mkdir(exist_ok=True,parents=True)
config={
 'infer_steps':4,'num_frames':a.frames,'text_len':512,'size':[a.height,a.width],'fps':16,
 'distill_method':'dmd2','sample_guide_scale':1,'sample_shift':5,'enable_cfg':False,
 'denoising_step_list':[1000,750,500,250],
 'self_attn_1_type':'torch_sdpa','cross_attn_1_type':'torch_sdpa','cross_attn_2_type':'torch_sdpa',
 'rope_type':'torch_complex_rope','cpu_offload':True,'offload_granularity':'phase',
 'dit_quantized':True,'dit_quantized_ckpt':str(models),'dit_quant_scheme':'fp8-triton',
 't5_cpu_offload':True,'t5_quantized':True,'t5_quantized_ckpt':str(t5_path),'t5_quant_scheme':'fp8-triton','t5_lazy_load':t5_lazy,
 'clip_cpu_offload':True,'clip_quantized':True,'clip_quantized_ckpt':str(models/'clip-fp8.pth'),'clip_quant_scheme':'fp8-triton',
 'use_tiling_vae':True,'use_tae':a.tiny,'tae_path':str(models/'taew2_1.pth'),
 'lazy_load':True,'clean_cuda_cache':True,'rotary_chunk':True,'rotary_chunk_size':100,
}
configpath=root/(a.name+'_config.json');configpath.write_text(json.dumps(config,indent=2))
prompt=pathlib.Path(a.prompt_file).read_text(encoding='utf-8').strip()
(root/(a.name+'_prompt.txt')).write_text(prompt)
import torch
torch.set_num_threads(4)
from lightx2v import LightX2VPipeline
st=time.perf_counter();peak=0;stop=threading.Event()
def monitor():
 global peak
 while not stop.wait(1):
  try:peak=max(peak,int(subprocess.check_output(['nvidia-smi','--query-gpu=memory.used','--format=csv,noheader,nounits'],creationflags=0x08000000).decode().strip().splitlines()[0]))
  except Exception:pass
threading.Thread(target=monitor,daemon=True).start()
try:
 pipe=LightX2VPipeline(task='i2v',model_path=str(models),model_cls='wan2.1',distill_method='dmd2')
 pipe.create_generator(config_json=str(configpath),fps=16)
 pipe.runner.model=None
 cachepath=root/(a.name+'_encoders.pt')
 def cpu_tree(v):
  if isinstance(v,torch.Tensor):return v.detach().cpu()
  if isinstance(v,dict):return {k:cpu_tree(t) for k,t in v.items()}
  if isinstance(v,list):return [cpu_tree(t) for t in v]
  if isinstance(v,tuple):return tuple(cpu_tree(t) for t in v)
  return v
 def save_cache(inputs):
  temporary=None
  try:
   with tempfile.NamedTemporaryFile(dir=cachepath.parent,prefix=cachepath.name+'.',suffix='.tmp',delete=False) as stream:temporary=pathlib.Path(stream.name)
   payload={'inputs':cpu_tree(inputs),'latent_shape':pipe.runner.input_info.latent_shape,'cache_key':cache_key}
   torch.save(payload,temporary)
   verified=torch.load(temporary,map_location='cpu',weights_only=True)
   if verified.get('cache_key')!=cache_key or 'inputs' not in verified or 'latent_shape' not in verified:raise ValueError('动作编码缓存写入校验失败。')
   os.replace(temporary,cachepath);temporary=None
  finally:
   if temporary is not None:temporary.unlink(missing_ok=True)
 image_path=pathlib.Path(a.image)
 cache_key=hashlib.sha256((prompt+str(config['size'])+str(a.frames)).encode()+image_path.read_bytes()).hexdigest()
 if a.encode_only:
  def save_encoders():
   save_cache(pipe.runner.inputs)
   print('ENCODERS_SAVED',time.perf_counter()-st,flush=True)
   raise SystemExit(0)
  pipe.runner.init_run=save_encoders
 elif a.cached:
  original_encoder=pipe.runner.run_input_encoder
  def cached_encoders():
   try:
    if cachepath.stat().st_size<1024:raise EOFError('动作编码缓存为空或不完整。')
    cached=torch.load(cachepath,map_location='cuda',weights_only=True)
    if cached.get('cache_key')!=cache_key:raise ValueError('动作编码缓存不匹配。')
    if 'inputs' not in cached or 'latent_shape' not in cached:raise ValueError('动作编码缓存缺少必要字段。')
    pipe.runner.input_info.latent_shape=cached['latent_shape']
    print('ENCODERS_REUSED',flush=True)
    return cached['inputs']
   except (EOFError,OSError,RuntimeError,ValueError,KeyError) as exc:
    print('ENCODERS_CACHE_INVALID',type(exc).__name__,flush=True)
    raise RuntimeError('动作编码缓存无效；已停止并保留原文件，请先检查内存余量后重试。') from exc
  pipe.runner.run_input_encoder=cached_encoders
 loaded=time.perf_counter();print('PIPELINE_READY',loaded-st,flush=True)
 image_path=pathlib.Path(a.image)
 pipe.generate(seed=a.seed,prompt=prompt,image_path=str(image_path),save_result_path=str(out/(a.name+'.mp4')))
 torch.cuda.synchronize()
 stats={'model':'LightX2V Wan2.1 I2V 14B distilled fp8','seed':a.seed,'frames':a.frames,'height':a.height,'width':a.width,'fps':16,'load_seconds':loaded-st,'generation_seconds':time.perf_counter()-loaded,'total_seconds':time.perf_counter()-st,'peak_gpu_total_mib':peak,'peak_torch_allocated_mib':torch.cuda.max_memory_allocated()/1024**2,'tiny_vae':a.tiny}
 (out/(a.name+'_benchmark.json')).write_text(json.dumps(stats,indent=2))
 print('SUCCESS',json.dumps(stats),flush=True)
finally:stop.set()

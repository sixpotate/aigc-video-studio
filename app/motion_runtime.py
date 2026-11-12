"""Isolated, offline Wan 2.2 inference using the existing low-memory runtime."""
import argparse
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time

APP=pathlib.Path(__file__).resolve().parent
ROOT=APP/'work/motion_test'
sys.path.insert(0,str(ROOT/'LightX2V-main'))
for key,value in {'TRITON_CACHE_DIR':'triton-cache','TORCHINDUCTOR_CACHE_DIR':'torch-cache','HF_HOME':'hf-cache','TORCH_HOME':'torch-home'}.items():
    os.environ[key]=str(ROOT/value)
os.environ.update(DTYPE='BF16',LOGURU_LEVEL='INFO',TOKENIZERS_PARALLELISM='false',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTORCH_CUDA_ALLOC_CONF='')

def main():
    p=argparse.ArgumentParser()
    for key in ('name','prompt-file','image'):p.add_argument('--'+key,required=True)
    for key,default in [('frames',73),('height',1280),('width',704),('seed',42),('steps',50)]:p.add_argument('--'+key,type=int,default=default)
    p.add_argument('--encode-only',action='store_true');p.add_argument('--cached',action='store_true')
    a=p.parse_args()
    from runtime_health import assert_engine_allowed
    assert_engine_allowed('wan22_5b')
    from director_plan import ready_720
    if not ready_720(a.width,a.height,a.frames,a.steps):raise ValueError('此分辨率与时长尚未通过本机验收，不能自动启动。')
    import torch
    torch.set_num_threads(4)
    from lightx2v import LightX2VPipeline
    model=ROOT/'models/wan22_5b_bf16';source=ROOT/'models/wan22_5b_source';legacy=ROOT/'models/distill_fp8'
    if not (model/'准备完成.json').is_file():raise ValueError('Wan2.2 模型尚未完整准备。')
    config=dict(infer_steps=a.steps,num_frames=a.frames,text_len=512,size=[a.height,a.width],fps=24,
        num_channels_latents=48,vae_stride=[4,16,16],use_image_encoder=False,
        sample_guide_scale=5.0,sample_shift=5.0,enable_cfg=True,
        self_attn_1_type='torch_sdpa',cross_attn_1_type='torch_sdpa',cross_attn_2_type='torch_sdpa',
        rope_type='torch_complex_rope',cpu_offload=True,offload_granularity='phase',
        dit_quantized=False,dit_original_ckpt=str(model),lazy_load=True,num_disk_workers=2,
        t5_cpu_offload=True,t5_quantized=True,t5_quantized_ckpt=str(legacy/'models_t5_umt5-xxl-enc-fp8.pth'),
        t5_quant_scheme='fp8-triton',t5_tokenizer_path=str(source/'google/umt5-xxl'),
        vae_path=str(source/'Wan2.2_VAE.pth'),lightvae_encoder_vae_pth=str(source/'Wan2.2_VAE.pth'),
        use_tiling_vae=True,vae_cpu_offload=True,vae_offload_cache=True,
        clean_cuda_cache=True,rotary_chunk=True,rotary_chunk_size=64)
    cache=ROOT/'quality_runs'/a.name;cache.mkdir(parents=True,exist_ok=True)
    configpath=cache/'config.json';configpath.write_text(json.dumps(config,indent=2),'utf-8')
    prompt=pathlib.Path(a.prompt_file).read_text('utf-8').strip()
    key=hashlib.sha256((prompt+str(config['size'])+str(a.frames)+'wan22-bf16-v1').encode()+pathlib.Path(a.image).read_bytes()).hexdigest()
    start=time.monotonic()
    pipe=LightX2VPipeline(task='i2v',model_path=str(model),model_cls='wan2.2')
    pipe.create_generator(config_json=str(configpath),fps=24)
    pipe.runner.model=None
    cachepath=cache/'encoders.pt'
    def cpu_tree(v):
        if isinstance(v,torch.Tensor):return v.detach().cpu()
        if isinstance(v,dict):return {k:cpu_tree(x) for k,x in v.items()}
        if isinstance(v,list):return [cpu_tree(x) for x in v]
        if isinstance(v,tuple):return tuple(cpu_tree(x) for x in v)
        return v
    def save_cache(inputs):
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=cachepath.parent,prefix=cachepath.name+'.',suffix='.tmp',delete=False) as stream:
                temporary=pathlib.Path(stream.name)
            payload=dict(inputs=cpu_tree(inputs),latent_shape=pipe.runner.input_info.latent_shape,cache_key=key)
            torch.save(payload,temporary)
            verified=torch.load(temporary,map_location='cpu',weights_only=True)
            if verified.get('cache_key')!=key or 'inputs' not in verified or 'latent_shape' not in verified:
                raise ValueError('动作编码缓存写入校验失败。')
            os.replace(temporary,cachepath);temporary=None
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)
    if a.encode_only:
        def save():
            save_cache(pipe.runner.inputs)
            print('ENCODERS_SAVED',flush=True);raise SystemExit(0)
        pipe.runner.init_run=save
    elif a.cached:
        original_encoder=pipe.runner.run_input_encoder
        def load():
            try:
                if cachepath.stat().st_size<1024:raise EOFError('动作编码缓存为空或不完整。')
                data=torch.load(cachepath,map_location='cuda',weights_only=True)
                if data.get('cache_key')!=key:raise ValueError('动作编码缓存不匹配。')
                if 'inputs' not in data or 'latent_shape' not in data:raise ValueError('动作编码缓存缺少必要字段。')
                pipe.runner.input_info.latent_shape=data['latent_shape']
                print('ENCODERS_REUSED',flush=True)
                return data['inputs']
            except (EOFError,OSError,RuntimeError,ValueError,KeyError) as exc:
                print('ENCODERS_CACHE_INVALID',type(exc).__name__,flush=True)
                raise RuntimeError('动作编码缓存无效；已停止并保留原文件，请先检查资源后重试。') from exc
        pipe.runner.run_input_encoder=load
    out=APP/'outputs/motion_test';out.mkdir(parents=True,exist_ok=True)
    target=out/(a.name+'.mp4');temp=out/(a.name+'.partial.mp4')
    pipe.generate(seed=a.seed,prompt=prompt,negative_prompt='blur, malformed hands, extra fingers, duplicated people, identity changes, flicker, backwards motion, frozen frame, subtitles, text',image_path=str(a.image),save_result_path=str(temp))
    torch.cuda.synchronize();temp.replace(target)
    stats=dict(model='Wan2.2 TI2V 5B BF16',source_revision='921dbaf3f1674a56f47e83fb80a34bac8a8f203e',seed=a.seed,
        frames=a.frames,height=a.height,width=a.width,fps=24,steps=a.steps,cfg=5.,
        total_seconds=round(time.monotonic()-start,2),peak_torch_allocated_mib=round(torch.cuda.max_memory_allocated()/1024**2))
    target.with_name(target.stem+'_benchmark.json').write_text(json.dumps(stats,indent=2),'utf-8')
    print('SUCCESS',json.dumps(stats),flush=True)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main()

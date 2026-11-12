"""MuseTalk for an arbitrary single character; no office-template coordinates."""
import json,os,pathlib,sys,subprocess
from settings import WORKSPACE,CREATE_NO_WINDOW
from speaker_tracking import select_face
os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',HF_HOME=str(WORKSPACE/'work/local_test/hf-cache'))

def load_musetalk_unet(model_path):
    """Load the same checkpoint directly onto CUDA without duplicate CPU models."""
    import torch
    from diffusers import UNet2DConditionModel
    config=json.loads((model_path/'musetalk.json').read_text(encoding='utf-8'))
    with torch.device('meta'):
        unet=UNet2DConditionModel(**config)
    expected=unet.state_dict()
    weights=torch.load(model_path/'pytorch_model.bin',map_location='cpu',weights_only=True,mmap=True)
    if set(expected)!=set(weights) or any(expected[k].shape!=weights[k].shape for k in expected):
        raise ValueError('口型模型的结构与权重不匹配，已停止处理。')
    converted={}
    for key,value in weights.items():
        converted[key]=value.to(device='cuda',dtype=torch.float16 if value.is_floating_point() else value.dtype)
    unet.load_state_dict(converted,strict=True,assign=True)
    return unet.eval()


def main(job):
    import cv2,numpy as np,torch
    local=WORKSPACE/'work/local_test'
    sys.path.insert(0,str(local/'MuseTalk-main'))
    from musetalk.models.vae import VAE
    from musetalk.models.unet import PositionalEncoding
    from musetalk.whisper.whisper import load_model
    from musetalk.whisper.whisper.audio import load_audio,pad_or_trim,log_mel_spectrogram
    torch.set_num_threads(4)
    from face_motion import track_face
    frames,boxes,src_fps=track_face(job);h,w=frames[0].shape[:2]
    model=local/'models/Linly-MuseTalk/MuseTalk'
    vae=VAE(str(model/'sd-vae-ft-mse'),use_float16=True)
    unet=load_musetalk_unet(model/'musetalk')
    pe=PositionalEncoding(384).half().to('cuda')
    whisper=load_model(str(model/'whisper/tiny.pt'),device='cuda').eval()
    wave=load_audio(job['audio']);seconds=len(wave)/16000
    with torch.inference_mode():
        mel=log_mel_spectrogram(pad_or_trim(wave)).unsqueeze(0).to('cuda',dtype=torch.float16)
        _,emb=whisper.encoder(mel,include_embeddings=True);features=emb[0,:,:int(seconds*50)].transpose(1,0,2)
        del whisper,mel;torch.cuda.empty_cache()
        output=pathlib.Path(job['output']);silent=output.with_suffix('.silent.mp4')
        proc=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}','-r','25','-i','pipe:0','-an','-c:v','libx264','-crf','18','-pix_fmt','yuv420p',str(silent)],stdin=subprocess.PIPE,creationflags=CREATE_NO_WINDOW)
        try:
            for i in range(round(seconds*25)):
                source=min(len(frames)-1,round(i*src_fps/25));frame=frames[source].copy();x1,y1,x2,y2=boxes[source]
                time=i/25;start=job['speech_start'];end=start+job['speech_seconds']
                if start<=time<end:
                    crop=cv2.resize(frame[y1:y2,x1:x2],(256,256),interpolation=cv2.INTER_LANCZOS4)
                    latent=vae.get_latents_for_unet(crop)
                    ids=np.clip(np.arange(int(time*50)-4,int(time*50)+6),0,len(features)-1)
                    chunk=torch.from_numpy(features[ids].reshape(1,50,384)).to('cuda',dtype=torch.float16)
                    prediction=unet(latent,torch.tensor([0],device='cuda'),encoder_hidden_states=pe(chunk)).sample
                    face=vae.decode_latents(prediction)[0]
                    face=cv2.resize(face,(x2-x1,y2-y1),interpolation=cv2.INTER_CUBIC)
                    mask=np.zeros((y2-y1,x2-x1),np.float32)
                    cv2.ellipse(mask,(round(mask.shape[1]*.5),round(mask.shape[0]*.79)),(round(mask.shape[1]*.27),round(mask.shape[0]*.13)),0,0,360,1,-1)
                    mask=cv2.GaussianBlur(mask,(0,0),max(2,mask.shape[1]*.018))[...,None]
                    frame[y1:y2,x1:x2]=np.clip(frame[y1:y2,x1:x2]*(1-mask)+face*mask,0,255).astype(np.uint8)
                proc.stdin.write(frame.tobytes())
            proc.stdin.close()
            if proc.wait():raise RuntimeError('口型视频编码失败。')
        finally:
            if proc.poll() is None:proc.kill();proc.wait()
        subprocess.run(['ffmpeg','-y','-v','error','-i',str(silent),'-i',job['audio'],'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-t',str(seconds),str(output)],check=True,creationflags=CREATE_NO_WINDOW)
        output.with_suffix('.tracking.json').write_text(json.dumps(dict(frames=len(frames),boxes=boxes)),encoding='utf-8')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main(json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')))

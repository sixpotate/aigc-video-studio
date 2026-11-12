"""Tiled local Real-ESRGAN restoration before subtitles and final delivery.

SRVGG architecture adapted from xinntao/Real-ESRGAN v0.3.0 (BSD-3-Clause).
The upstream copyright and license are distributed with the model in LICENSE.
"""
import hashlib,json,pathlib,subprocess,sys,time
from settings import WORKSPACE,CREATE_NO_WINDOW
from progress_writer import atomic_json,write_progress

MODEL=WORKSPACE/'work/local_test/models/Real-ESRGAN/realesr-general-x4v3.pth'

def ready():return MODEL.is_file() and MODEL.stat().st_size==4885111

def create_model(device='cpu'):
    import torch
    from torch import nn
    class SRVGG(nn.Module):
        def __init__(self):
            super().__init__()
            self.body=nn.ModuleList([nn.Conv2d(3,64,3,1,1),nn.PReLU(num_parameters=64)])
            for _ in range(32):self.body.extend([nn.Conv2d(64,64,3,1,1),nn.PReLU(num_parameters=64)])
            self.body.append(nn.Conv2d(64,48,3,1,1));self.upsampler=nn.PixelShuffle(4)
        def forward(self,x):
            y=x
            for layer in self.body:y=layer(y)
            return self.upsampler(y)+nn.functional.interpolate(x,scale_factor=4,mode='nearest')
    model=SRVGG()
    state=torch.load(MODEL,map_location='cpu',weights_only=True)
    model.load_state_dict(state.get('params_ema',state.get('params',state)),strict=True)
    model=model.eval().to(device)
    return model.half() if device=='cuda' else model.float()

def restore_frame(model,rgb,tile=256,pad=40):
    import torch,numpy as np
    parameter=next(model.parameters())
    h,w=rgb.shape[:2];output=np.empty((h*4,w*4,3),dtype=np.uint8)
    with torch.inference_mode():
        for y in range(0,h,tile):
            for x in range(0,w,tile):
                x0,y0=max(0,x-pad),max(0,y-pad);x1,y1=min(w,x+tile+pad),min(h,y+tile+pad)
                chunk=torch.from_numpy(rgb[y0:y1,x0:x1].copy()).permute(2,0,1).unsqueeze(0).to(device=parameter.device,dtype=parameter.dtype)/255.
                value=model(chunk).clamp(0,1)[0].permute(1,2,0).float().cpu().numpy()
                tw,th=min(tile,w-x),min(tile,h-y)
                output[y*4:(y+th)*4,x*4:(x+tw)*4]=np.rint(value[(y-y0)*4:(y-y0+th)*4,(x-x0)*4:(x-x0+tw)*4]*255).astype('uint8')
    return output

def file_hash(path):
    with pathlib.Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def replace_strict(source,target):
    """Preserve production data and tolerate short Windows sharing conflicts."""
    for attempt in range(30):
        try:
            source.replace(target)
            return
        except PermissionError:
            if attempt==29:raise
            time.sleep(.1)


def valid_chunk(path,entry,expected_frames):
    if not path.is_file() or not isinstance(entry,dict) or entry.get('frames')!=expected_frames:return False
    return entry.get('sha256')==file_hash(path)


def encode_frames(width,height,fps,job,target):
    return subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','rgb24','-s',f'{width*4}x{height*4}',
        '-r',str(fps),'-i','pipe:0','-an','-vf',f'scale={job["width"]}:{job["height"]}:flags=lanczos,setsar=1',
        '-c:v','libx264','-threads','1','-crf','17','-pix_fmt','yuv420p','-movflags','+faststart',str(target)],stdin=subprocess.PIPE,creationflags=CREATE_NO_WINDOW)


def main(job,cancelled=lambda:False,progress_callback=None):
    import cv2,torch
    if not ready():raise ValueError('清晰度模型未准备完整。')
    torch.set_num_threads(1)
    cv2.setNumThreads(1)
    cap=cv2.VideoCapture(job['video'])
    width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH));height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT));fps=cap.get(cv2.CAP_PROP_FPS)
    frames=int(cap.get(cv2.CAP_PROP_FRAME_COUNT));target=pathlib.Path(job['output']);temp=target.with_suffix('.partial.mp4')
    if not width or not height or not fps or not frames:raise ValueError('清晰度处理输入无效。')
    from director_plan import policy
    device=policy().get('enhancement_device','cpu')
    if device not in ('cpu','cuda'):raise ValueError('清晰度计算设备设置无效。')
    identity=dict(source=file_hash(job['video']),model=file_hash(MODEL),device=device,width=job['width'],height=job['height'],version=2)
    key=hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest()
    cache=target.parent/'清晰度续跑缓存'/key;cache.mkdir(parents=True,exist_ok=True)
    manifest=cache/'进度.json'
    try:state=json.loads(manifest.read_text('utf-8'))
    except (OSError,ValueError):state={}
    if state.get('identity')!=identity or not isinstance(state.get('chunks'),dict):state=dict(identity=identity,chunks={})
    start=time.monotonic();model=None;reused=0;processed=0;parts=[];chunk_frames=8
    def check():
        if cancelled():raise InterruptedError('已停止清晰度修复，完成的小段已保留，继续时无需从第一帧重做。')
    def report(done):
        elapsed=time.monotonic()-start
        remaining=round((frames-done)*elapsed/processed) if processed>=4 else None
        message=f'正在修复画面细节 {done}/{frames}帧'
        if reused:message+=f'，接回已完成{reused}帧'
        if remaining is not None:message+=f'，估计还需{remaining//60}分{remaining%60:02d}秒'
        value=dict(completed=done,total=frames,processed=processed,reused=reused,remaining_seconds=remaining,message=message)
        # Status updates are informational: a transient Windows sharing
        # violation must not discard an otherwise valid enhancement chunk.
        if job.get('progress_path'):write_progress(pathlib.Path(job['progress_path']),value)
        if progress_callback:progress_callback(value)
        if done==frames or done%8==0:print('DETAIL_RESTORATION',done,frames,'REUSED',reused,flush=True)
    try:
        report(0)
        for at in range(0,frames,chunk_frames):
            check();count=min(chunk_frames,frames-at);part=cache/(f'片段_{at:06d}.mp4');label=str(at)
            if valid_chunk(part,state.get('chunks',{}).get(label),count):
                reused+=count;parts.append(part);report(at+count);continue
            if model is None:model=create_model(device)
            if not cap.set(cv2.CAP_PROP_POS_FRAMES,at):raise ValueError('视频无法定位到待修复的画面。')
            partial=part.with_suffix('.partial.mp4');process=encode_frames(width,height,fps,job,partial)
            try:
                for offset in range(count):
                    check();ok,frame=cap.read()
                    if not ok or abs(cap.get(cv2.CAP_PROP_POS_FRAMES)-(at+offset+1))>.5:
                        raise ValueError('待修复视频帧不完整，未用重复帧代替。')
                    restored=restore_frame(model,cv2.cvtColor(frame,cv2.COLOR_BGR2RGB))
                    process.stdin.write(restored.tobytes());processed+=1;report(at+offset+1)
                process.stdin.close()
                if process.wait(timeout=90):raise ValueError('清晰度片段编码失败。')
                replace_strict(partial,part)
            finally:
                if process.poll() is None:process.kill();process.wait()
                if not process.stdin.closed:
                    try:process.stdin.close()
                    except OSError:pass
            state['chunks'][label]=dict(frames=count,sha256=file_hash(part));atomic_json(manifest,state);parts.append(part)
        check()
        listing=cache/'合成清单.txt';listing.write_text(''.join("file '"+p.as_posix().replace("'","'\\''")+"'\n" for p in parts),'utf-8')
        subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),'-an','-c:v','copy',
            '-movflags','+faststart',str(temp)],check=True,creationflags=CREATE_NO_WINDOW)
        verify=cv2.VideoCapture(str(temp));actual=int(verify.get(cv2.CAP_PROP_FRAME_COUNT));verify.release()
        if actual!=frames:raise ValueError('清晰度片段合成后的帧数不一致，未提交结果。')
        replace_strict(temp,target)
    finally:
        cap.release()
    metadata=dict(applied=True,model='Real-ESRGAN general-x4v3',native_width=width,native_height=height,
        width=job['width'],height=job['height'],frames=frames,seconds=round(time.monotonic()-start,2),
        frames_reused=reused,frames_processed=processed,resume_supported=True,cache_key=key,
        device=device,description='AI修复放大后缩放至导出尺寸；增强细节不等于原生拍摄或原生2K。')
    atomic_json(target.with_suffix('.json'),metadata)

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');main(json.loads(pathlib.Path(sys.argv[1]).read_text('utf-8')))


"""Preserve anime artwork while moving native mouth poses with speech energy."""
import json,pathlib,subprocess,sys
import cv2,soundfile as sf
from settings import CREATE_NO_WINDOW
from face_motion import track_face
from native_mouth import MouthBank,envelope

def main(job):
    frames,boxes,source_fps=track_face(job);bank=MouthBank(frames,boxes)
    if bank.variation<.012:raise ValueError('原动作缺少嘴形变化，动漫口型无法凭空补出张嘴。请在动作中注明“自然讲话，嘴部明显开合”后重做动作，或改选写实口型。')
    audio,rate=sf.read(job['audio']);levels=envelope(audio,rate);seconds=len(audio)/rate
    output=pathlib.Path(job['output']);silent=output.with_suffix('.native.silent.mp4');h,w=frames[0].shape[:2]
    proc=subprocess.Popen(['ffmpeg','-y','-v','error','-f','rawvideo','-pix_fmt','bgr24','-s',f'{w}x{h}','-r','25','-i','pipe:0','-an','-c:v','libx264','-crf','17','-pix_fmt','yuv420p',str(silent)],stdin=subprocess.PIPE,creationflags=CREATE_NO_WINDOW)
    try:
        for i in range(round(seconds*25)):
            source=min(len(frames)-1,round(i*source_fps/25));level=levels[min(i,len(levels)-1)] if job['speech_start']<=i/25<job['speech_start']+job['speech_seconds'] else 0
            proc.stdin.write(bank.render(source,level).tobytes())
        proc.stdin.close()
        if proc.wait():raise RuntimeError('动漫口型视频编码失败。')
    finally:
        if proc.poll() is None:proc.kill();proc.wait()
    subprocess.run(['ffmpeg','-y','-v','error','-i',str(silent),'-i',job['audio'],'-map','0:v','-map','1:a','-c:v','copy','-c:a','aac','-t',str(seconds),str(output)],check=True,creationflags=CREATE_NO_WINDOW)
    output.with_suffix('.tracking.json').write_text(json.dumps(dict(frames=len(frames),boxes=boxes,method='native_mouth_audio_energy',phoneme_alignment=False)),'utf-8')

if __name__=='__main__':main(json.loads(pathlib.Path(sys.argv[1]).read_text('utf-8')))

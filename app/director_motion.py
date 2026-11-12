"""Frame-aligned, forward-only trimming. Coverage is planned before generation."""
import json
import subprocess
from settings import CREATE_NO_WINDOW


def probe_metadata(arguments):
    """Retry only a timed-out metadata process, never a corrupt video."""
    for seconds in (20,60):
        try:
            return subprocess.run(['ffprobe','-v','error',*arguments],
                capture_output=True,text=True,check=True,timeout=seconds,creationflags=CREATE_NO_WINDOW)
        except subprocess.TimeoutExpired:
            if seconds==60:raise


def video_duration(path):
    result=probe_metadata(['-show_entries','format=duration','-of','json',str(path)])
    return float(json.loads(result.stdout)['format']['duration'])


def video_size(path):
    result=probe_metadata(['-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(path)])
    streams=json.loads(result.stdout).get('streams',[])
    if not streams or not streams[0].get('width') or not streams[0].get('height'):raise ValueError('视频尺寸无法读取。')
    return streams[0]['width'],streams[0]['height']

def fit_command(video,target,seconds,image=False,width=384,height=672):
    if image:
        return ['ffmpeg','-y','-v','error','-loop','1','-i',video,'-vf',fr'scale={width}:{height},zoompan=z=min(zoom+0.00015\,1.06):d=1:s={width}x{height}:fps=25','-t',seconds,'-an','-c:v','libx264','-crf','16','-pix_fmt','yuv420p',target]
    duration=video_duration(video)
    if seconds-duration>.12:
        raise ValueError(f'动作只有{duration:.2f}秒，需覆盖{seconds:.2f}秒；应补生成连续镜头，不能倒放或静帧凑时长。')
    filters=f'setpts=PTS-STARTPTS,fps=25,tpad=stop_mode=clone:stop_duration=0.12,trim=duration={seconds},setsar=1'
    return ['ffmpeg','-y','-v','error','-i',video,'-vf',filters,'-an','-c:v','libx264','-crf','16','-pix_fmt','yuv420p',target]

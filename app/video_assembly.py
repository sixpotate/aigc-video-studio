"""Normalize each clip before concatenation; AAC packet padding is not scene time."""
def concat_command(clips, slots, destination):
    command=['ffmpeg','-y','-hide_banner','-loglevel','error']
    filters=[]
    for i,(clip,seconds) in enumerate(zip(clips,slots)):
        command += ['-i',str(clip)]
        filters += [f'[{i}:v]setpts=PTS-STARTPTS,fps=25,tpad=stop_mode=clone:stop_duration=0.2,trim=duration={seconds},setsar=1[v{i}]',
                    f'[{i}:a]aresample=48000,asetpts=PTS-STARTPTS,apad,atrim=end_sample={round(seconds*48000)},asetpts=PTS-STARTPTS[a{i}]']
    filters.append(''.join(f'[v{i}][a{i}]' for i in range(len(clips)))+f'concat=n={len(clips)}:v=1:a=1[v][a]')
    return command+['-filter_complex',';'.join(filters),'-map','[v]','-map','[a]','-c:v','libx264','-crf','18','-pix_fmt','yuv420p','-c:a','aac','-b:a','160k','-ar','48000','-ac','2',str(destination)]

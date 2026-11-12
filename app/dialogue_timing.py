"""Use measured speech pauses for visual cuts; never edit the dialogue waveform."""
import math

VERSION=1


def pause_windows(wave,sample_rate,speech_start=0.,speech_seconds=None):
    import numpy as np
    values=np.asarray(wave,dtype=np.float32)
    if values.ndim>1:values=values.mean(axis=1)
    hop=max(1,round(sample_rate*.02));count=len(values)//hop
    if count<2:return []
    rms=np.sqrt(np.mean(values[:count*hop].reshape(count,hop)**2,axis=1))
    peak=float(np.max(rms))
    if peak<.001:return []
    threshold=max(.001,min(.012,peak*.065))
    end=speech_start+speech_seconds if speech_seconds is not None else len(values)/sample_rate
    quiet=rms<threshold;result=[];start=None
    for index,is_quiet in enumerate([*quiet,False]):
        if is_quiet and start is None:start=index
        elif not is_quiet and start is not None:
            left,right=start*hop/sample_rate,index*hop/sample_rate
            if right-left>=.12 and left>speech_start+.12 and right<end-.12:
                result.append([round(left,3),round(right,3)])
            start=None
    return result


def cut_boundaries(seconds,max_seconds,pauses=(),fps=25):
    total=round(seconds*fps);limit=max(1,round(max_seconds*fps))
    count=max(1,math.ceil(total/limit))
    fallback=[round(total*i/count) for i in range(count+1)]
    windows=[(max(0,math.ceil(a*fps)),min(total,math.floor(b*fps))) for a,b in pauses if b>a]
    windows=[(a,b) for a,b in windows if b>a]
    if count==1 or not windows:return fallback
    minimum=min(limit,max(1,round(fps*1.0)))
    # A shortest path can add one useful reaction shot instead of cutting through speech.
    best=[float('inf')]*(total+1);previous=[None]*(total+1);best[0]=0.
    for end in range(minimum,total+1):
        at_pause=any(a<=end<=b for a,b in windows)
        penalty=0 if end==total else (.3 if at_pause else 3.)
        for start in range(max(0,end-limit),end-minimum+1):
            length=end-start
            cost=best[start]+.6+penalty+.35*((limit-length)/limit)**2
            if cost<best[end]:best[end]=cost;previous[end]=start
    if previous[total] is None:return fallback
    result=[total]
    while result[-1]:result.append(previous[result[-1]])
    return list(reversed(result))


def boundary_basis(frame,pauses,fps=25):
    return 'speech_pause' if any(a<=frame/fps<=b for a,b in pauses) else 'duration_limit'

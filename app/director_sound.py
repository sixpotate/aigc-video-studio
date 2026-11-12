"""Offline sample-based music, local effects and editable final mixing."""
import json,math,pathlib
from fractions import Fraction
from settings import WORKSPACE
from director_schema import digest
from director_assets import asset_path

def music_track(style,seconds,folder):
    if style.startswith('asset:'):return asset_path(style[6:],'music')
    import numpy as np,soundfile as sf
    from scipy import signal
    root=WORKSPACE/'work/knight_score_v2';manifest=root/'assets_manifest.json'
    if not manifest.is_file():raise ValueError('缺少本机内置音乐采样，请选择导入的本机音乐。')
    dest=folder/(digest(dict(style=style,seconds=seconds,score_version=1))+'.music.wav')
    if dest.is_file():return dest
    sr=48000;n=round(seconds*sr);track=np.zeros((n,2),np.float32);bank={};cache={}
    for item in json.loads(manifest.read_text('utf-8'))['samples']:
        if item['group'] not in ('violin_short','cello_short'):continue
        wav,rate=sf.read(root/'assets'/item['path'],always_2d=True,dtype='float32');wav=wav.mean(axis=1)
        if rate!=sr:
            r=Fraction(sr,rate);wav=signal.resample_poly(wav,r.numerator,r.denominator)
        active=np.flatnonzero(abs(wav)>.025*max(abs(wav)))
        if len(active):wav=wav[max(0,active[0]-150):]
        wav/=max(float(np.max(abs(wav))),1e-6);bank.setdefault(item['group'],[]).append((item['root_midi'],wav))
    if len(bank)!=2:raise ValueError('内置音乐采样不完整，请导入本机音乐。')
    def note(group,pitch,at,length,gain,pan):
        key=(group,pitch,length)
        if key not in cache:
            root_note,wav=min(bank[group],key=lambda v:abs(v[0]-pitch));r=Fraction(2**((root_note-pitch)/12)).limit_denominator(500)
            wav=signal.resample_poly(wav,r.numerator,r.denominator)[:round((length+.07)*sr)].copy();t=np.arange(len(wav))/sr
            wav*=np.minimum(t/.006,1)*np.clip((length+.07-t)/.07,0,1);cache[key]=wav
        start=round(at*sr);count=min(len(cache[key]),n-start)
        if count>0:track[start:start+count]+=cache[key][:count,None]*gain*np.sqrt([1-pan,1+pan])
    beat=60/(120 if style=='comedy' else 106)
    chords=[[60,64,67],[57,60,64],[53,57,60],[55,59,62]] if style=='comedy' else [[57,60,64],[53,57,60],[50,53,57],[52,56,59]]
    for bar in range(math.ceil(seconds/(4*beat))):
        chord=chords[bar%4];at=bar*4*beat
        for k in range(4):note('cello_short',chord[0]-12+(7 if k%2 else 0),at+k*beat,.22,.18,.18)
        for k,j in enumerate([0,2,1,2,0,1,2,1]):note('violin_short',chord[j]+12,at+(k*.5+(.05 if k%2 else 0))*beat,.13,.13,-.22)
    sf.write(dest,track,sr);return dest

def effects_track(project,slots,folder):
    import numpy as np,soundfile as sf
    from scipy import signal
    sr=48000;seconds=sum(slots);fx=np.zeros((round(seconds*sr),2),np.float32);at=0;rng=np.random.default_rng(501)
    from sound_library import media_path, mix_identity
    sample_cache={}
    for shot,duration in zip(project['shots'],slots):
        kind=shot.get('effect','none')
        if kind!='none':
            offset=shot.get('effect_time',0)
            if offset>=duration:raise ValueError(f'镜头{project["shots"].index(shot)+1}的音效时间超出实际时长，请调整音效位置。')
            length={'ding':.7,'bang':.28,'ring':.95,'boing':.65,'whistle':.3,'paper':.3}[kind];t=np.arange(round(sr*length))/sr
            if kind=='ding':wave=(np.sin(2*np.pi*1046.5*t)+.3*np.sin(2*np.pi*2093*t))*np.exp(-t*7)
            elif kind=='bang':wave=(np.sin(2*np.pi*(88*t-35*t*t))*.75+rng.normal(0,.2,len(t)))*np.exp(-t*22)
            elif kind=='ring':wave=(np.sin(2*np.pi*880*t)+.3*np.sin(2*np.pi*1320*t))*((t%.27)<.16)*np.sin(np.pi*t/length)**2
            elif kind=='boing':wave=np.sin(2*np.pi*(220*t+110*t*t+1.8*np.sin(t*20)))*np.exp(-t*6)
            elif kind=='whistle':wave=np.sin(2*np.pi*(1650*t+8*np.sin(35*t)))*np.sin(np.pi*t/length)**2
            else:wave=signal.sosfilt(signal.butter(2,[700,5000],btype='bandpass',fs=sr,output='sos'),rng.normal(0,.4,len(t)))*np.sin(np.pi*t/length)**2
            start=round((at+offset)*sr);count=min(len(wave),len(fx)-start);fx[start:start+count]+=wave[:count,None]*10**(shot.get('effect_level',-12)/20)
        for cue in shot.get('sound_cues',[]):
            ident=cue['asset_id']
            if ident not in sample_cache:
                wave,rate=sf.read(media_path(ident),always_2d=True,dtype='float32')
                if wave.shape[1]==1:wave=np.repeat(wave,2,axis=1)
                elif wave.shape[1]>2:wave=wave[:,:2]
                if rate!=sr:
                    r=Fraction(sr,rate);wave=signal.resample_poly(wave,r.numerator,r.denominator,axis=0)
                wave=wave/max(float(np.max(abs(wave))),1e-6)*.9
                sample_cache[ident]=wave
            wave=sample_cache[ident]
            offset=duration*cue['at_ratio'];count=max(0,round((duration-offset)*sr))
            if cue['loop'] and count:
                wave=np.tile(wave,(math.ceil(count/len(wave)),1))[:count]
            else:wave=wave[:count]
            wave=wave.copy();attack=min(round((.06 if cue['loop'] else .002)*sr),len(wave)//2);fade=min(round(.06*sr),len(wave)//2)
            if attack:wave[:attack]*=np.linspace(0,1,attack)[:,None]
            if fade:wave[-fade:]*=np.linspace(1,0,fade)[:,None]
            start=round((at+offset)*sr);count=min(len(wave),len(fx)-start)
            if count>0:fx[start:start+count]+=wave[:count]*10**(cue['level']/20)
        at+=duration
    dest=folder/(digest(dict(effects=[mix_identity(s) for s in project['shots']],slots=slots,version=1))+'.effects.wav')
    sf.write(dest,fx,sr);return dest

def mix_command(dry,music,effects,target,seconds,sound):
    command=['ffmpeg','-y','-v','error','-i',str(dry)]
    filters=['[0:a]aresample=48000,loudnorm=I=-16:TP=-3:LRA=9,asplit=2[voice][control]']
    sources=['[voice]'];next_input=1
    if music:
        command+=['-stream_loop','-1','-i',str(music)];fade=min(sound['fade'],seconds/2)
        filters.append(f'[{next_input}:a]aresample=48000,atrim=duration={seconds},asetpts=PTS-STARTPTS,loudnorm=I=-16:TP=-3:LRA=7,volume={sound["level"]}dB,afade=t=in:d={fade},afade=t=out:st={max(0,seconds-fade)}:d={fade}[music]');next_input+=1
        if sound['duck']:filters.append('[music][control]sidechaincompress=threshold=0.045:ratio=3:attack=20:release=240[ducked]');sources.append('[ducked]')
        else:filters.append('[control]anullsink');sources.append('[music]')
    else:filters.append('[control]anullsink')
    command+=['-i',str(effects)];filters.append(f'[{next_input}:a]aresample=48000[effects]');sources.append('[effects]')
    filters.append(''.join(sources)+f'amix=inputs={len(sources)}:duration=first:normalize=0,loudnorm=I=-16:TP=-1.5:LRA=9[audio]')
    return command+['-filter_complex',';'.join(filters),'-map','0:v','-map','[audio]','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-ac','2','-t',str(seconds),'-movflags','+faststart',str(target)]

def assemble(project,clips,slots,target,work,run):
    from video_assembly import concat_command
    sound=project['sound'];current=list(clips);lengths=list(slots);level=0
    while len(current)>8:
        batches=[];times=[]
        for start in range(0,len(current),8):
            batch=current[start:start+8];timing=lengths[start:start+8];name=digest(dict(clips=list(map(str,batch)),timing=timing));dest=work/(name+'.batch.mp4')
            if not dest.is_file():run(concat_command(batch,timing,dest))
            batches.append(dest);times.append(sum(timing))
        current,lengths=batches,times;level+=1
    dry=work/'dialogue_only.mp4';run(concat_command(current,lengths,dry))
    music=None if sound['track']=='none' else music_track(sound['track'],sum(slots),work)
    effects=effects_track(project,slots,work);run(mix_command(dry,music,effects,target,sum(slots),sound))

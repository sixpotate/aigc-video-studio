"""Audio-driven mouth poses sampled from the character's own animation.

This preserves drawn facial features. It matches speech energy, not phonemes.
"""
import cv2,numpy as np

def envelope(audio,rate,fps=25):
    audio=np.asarray(audio,dtype=np.float32)
    if audio.ndim==2:audio=audio.mean(axis=1)
    count=int(np.ceil(len(audio)/rate*fps));energy=[]
    for i in range(count):
        chunk=audio[round(i*rate/fps):round((i+1)*rate/fps)]
        energy.append(float(np.sqrt(np.mean(chunk**2))) if len(chunk) else 0.)
    energy=np.asarray(energy);peak=max(float(np.quantile(energy,.9)),1e-5)
    level=np.clip((energy/peak-.10)/.90,0,1)**.65
    return np.convolve(level,[.2,.6,.2],'same')

class MouthBank:
    def __init__(self,frames,boxes):
        self.frames=frames;self.boxes=boxes
        self.faces=np.asarray([cv2.resize(f[y:yy,x:xx],(64,64),interpolation=cv2.INTER_AREA) for f,(x,y,xx,yy) in zip(frames,boxes)])
        gray=np.asarray([cv2.cvtColor(f,cv2.COLOR_BGR2GRAY) for f in self.faces])
        self.mask=np.zeros((64,64),np.float32);cv2.ellipse(self.mask,(33,49),(16,10),0,0,360,1,-1)
        measure=np.zeros((64,64),np.uint8);cv2.ellipse(measure,(33,49),(13,8),0,0,360,1,-1)
        opening=np.mean((gray[:,measure>0]<85),axis=1)
        low,high=np.quantile(opening,[.05,.95]);self.variation=float(high-low);self.opening=np.clip((opening-low)/max(high-low,.025),0,1)
        self.choices=np.unique(np.linspace(0,len(frames)-1,min(80,len(frames))).astype(int))
        guides=gray[:,:38].astype(np.float32)
        self.pose=np.asarray([np.mean((guides[self.choices]-g)**2,axis=(1,2))/650 for g in guides])
        self.mask=cv2.GaussianBlur(self.mask,(0,0),.8)[...,None]

    def render(self,index,level,frame=None):
        level=float(np.clip(level,0,1));cost=self.pose[index]+3.8*(self.opening[self.choices]-level*.9)**2
        selected=int(self.choices[np.argmin(cost)])
        base=self.frames[index] if frame is None else frame
        if selected==index:return base.copy()
        x,y,xx,yy=self.boxes[index];sx,sy,sxx,syy=self.boxes[selected]
        patch=cv2.resize(self.frames[selected][sy:syy,sx:sxx],(xx-x,yy-y),interpolation=cv2.INTER_CUBIC)
        mask=cv2.resize(self.mask,(xx-x,yy-y),interpolation=cv2.INTER_LINEAR)[...,None]
        result=base.copy();result[y:yy,x:xx]=np.uint8(np.clip(result[y:yy,x:xx]*(1-mask)+patch*mask,0,255))
        return result

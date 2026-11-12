"""Spatial text attention for known full-body portrait layouts.

This is soft layout guidance, not image segmentation or a pose guarantee.
Use only for a new supported composition, never for reference edits. Seated
layouts are applied by the worker only alongside the matching pose skeleton.
"""
import math
from portrait_spec import feature_text

REGIONS={
    'hair':(0,.30), 'face':(.02,.34), 'top':(.16,.58),
    'bottom':(.42,.93), 'garment':(.17,.83), 'shoes':(.78,1),
    'accessory':(.3,.78),
}
SEATED_REGIONS={
    'hair':(.04,.34), 'face':(.08,.38), 'top':(.23,.60),
    'bottom':(.53,.85), 'garment':(.23,.80), 'shoes':(.69,.91),
    'accessory':(.37,.83),
}


class RegionGuide:
    def __init__(self,labels,width,height,regions=None):
        self.labels=labels;self.width=width;self.height=height;self.cache={}
        self.regions=REGIONS if regions is None else regions

    def mask(self,states,context):
        import torch
        batch=states.shape[0]
        if batch!=2 or context.shape[1]!=len(self.labels):return None
        count=states.shape[1] if states.ndim==3 else states.shape[2]*states.shape[3]
        key=(count,states.device,states.dtype)
        if key in self.cache:return self.cache[key]
        rows=round(math.sqrt(count*self.height/self.width))
        if rows<1 or count%rows:return None
        cols=count//rows
        y=((torch.arange(rows,device=states.device,dtype=torch.float32)+.5)/rows).repeat_interleave(cols)
        x=((torch.arange(cols,device=states.device,dtype=torch.float32)+.5)/cols).repeat(rows)
        bias=torch.zeros((batch,count,len(self.labels)),device=states.device,dtype=states.dtype)
        for region in set(self.labels):
            if region=='background':
                # Keep the background color from painting the person's clothes.
                central=(x>.23)&(x<.77)&(y>.06)&(y<.97)
                penalty=central.to(torch.float32)*-4.0
            elif region in self.regions:
                low,high=self.regions[region]
                distance=(low-y).clamp_min(0)+(y-high).clamp_min(0)
                penalty=-4.0*(distance/.10).clamp(max=1)
            else:continue
            indices=[i for i,label in enumerate(self.labels) if label==region]
            bias[1,:,indices]=penalty[:,None].to(states.dtype)
        self.cache[key]=bias
        return bias


class RegionalProcessor:
    def __init__(self,original,guide):self.original=original;self.guide=guide
    def __call__(self,attn,hidden_states,encoder_hidden_states=None,attention_mask=None,temb=None,*args,**kwargs):
        if encoder_hidden_states is not None and attention_mask is None:
            attention_mask=self.guide.mask(hidden_states,encoder_hidden_states)
        return self.original(attn,hidden_states,encoder_hidden_states,attention_mask,temb,*args,**kwargs)


def supports_regions(role,mode):
    pose=role.get('look',{}).get('pose','')
    return mode=='new' and role.get('framing')=='full' and pose in ('front','正面站立，双臂自然下垂')


def apply_regions(pipe,labels,role,mode,width,height):
    regions=region_layout(role,mode)
    if regions is None:return False
    guide=RegionGuide(labels,width,height,regions)
    processors={name:RegionalProcessor(processor,guide) if name.endswith('attn2.processor') else processor
                for name,processor in pipe.unet.attn_processors.items()}
    pipe.unet.set_attn_processor(processors)
    return True


def region_layout(role,mode):
    if supports_regions(role,mode):return REGIONS
    if mode=='new' and role.get('framing')=='full' and feature_text(role.get('look',{}),'pose') in (
        '盘腿而坐','盘腿坐','盘腿坐在地上','sitting cross-legged','sitting cross-legged on the floor'):
        return SEATED_REGIONS
    return None

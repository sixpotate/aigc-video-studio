"""Local pose conditioning and a separate, auditable face-detail pass."""
import math
import re
from portrait_regions import supports_regions
from portrait_spec import feature_text


def pose_preset(role,mode):
    if mode!='new' or role.get('framing')!='full':return None
    if supports_regions(role,mode):return 'front-arms-down-v1'
    pose=feature_text(role.get('look',{}),'pose')
    # Do not apply a front-facing preset to side views or an unspecified pose.
    if re.fullmatch(r'盘腿而坐|盘腿坐|盘腿坐在地上|sitting cross-legged(?: on the floor)?',pose,re.I):
        return 'front-cross-legged-v1'
    return None


def pose_supported(role,mode):
    return pose_preset(role,mode) is not None


def standing_pose(size, preset='front-arms-down-v1'):
    """COCO-18 joints/limb palette used by OpenPose ControlNet.

    Protocol reference: lllyasviel/ControlNet, annotator/openpose/util.py.
    Presets constrain major joints only, not hands, shoes or garment shape.
    """
    import cv2
    import numpy as np
    from PIL import Image
    width,height=size
    joints=[(.5,.11),(.5,.19),(.40,.20),(.37,.35),(.35,.49),
            (.60,.20),(.63,.35),(.65,.49),(.44,.50),(.435,.70),(.43,.91),
            (.56,.50),(.565,.70),(.57,.91),(.476,.102),(.524,.102),(.456,.108),(.544,.108)]
    if preset=='front-cross-legged-v1':
        joints=[(.5,.16),(.5,.26),(.36,.28),(.30,.46),(.27,.65),
                (.64,.28),(.70,.46),(.73,.65),(.42,.58),(.21,.72),(.61,.79),
                (.58,.58),(.79,.72),(.39,.79),(.474,.152),(.526,.152),(.452,.16),(.548,.16)]
    elif preset!='front-arms-down-v1':raise ValueError('未知的姿势参考')
    edges=[(1,2),(1,5),(2,3),(3,4),(5,6),(6,7),(1,8),(8,9),(9,10),
           (1,11),(11,12),(12,13),(1,0),(0,14),(14,16),(0,15),(15,17)]
    colors=[(255,0,0),(255,85,0),(255,170,0),(255,255,0),(170,255,0),(85,255,0),
            (0,255,0),(0,255,85),(0,255,170),(0,255,255),(0,170,255),(0,85,255),
            (0,0,255),(85,0,255),(170,0,255),(255,0,255),(255,0,170),(255,0,85)]
    points=[(round(x*width),round(y*height)) for x,y in joints]
    canvas=np.zeros((height,width,3),dtype=np.uint8)
    radius=max(2,round(width/128))
    for i,point in enumerate(points):cv2.circle(canvas,point,radius,colors[i],-1)
    for i,(a,b) in enumerate(edges):
        ax,ay=points[a];bx,by=points[b]
        polygon=cv2.ellipse2Poly((round((ax+bx)/2),round((ay+by)/2)),
            (max(1,round(math.hypot(ax-bx,ay-by)/2)),radius),round(math.degrees(math.atan2(by-ay,bx-ax))),0,360,1)
        overlay=canvas.copy();cv2.fillConvexPoly(overlay,polygon,colors[i])
        canvas=cv2.addWeighted(canvas,.4,overlay,.6,0)
    return Image.fromarray(canvas)


def clear_regions(pipe):
    from portrait_regions import RegionalProcessor
    processors={name:(processor.original if isinstance(processor,RegionalProcessor) else processor)
                for name,processor in pipe.unet.attn_processors.items()}
    pipe.unet.set_attn_processor(processors)


def face_crop(image,framing):
    """Refine only a confidently detected single face; never guess a face box."""
    import cv2
    import numpy as np
    cascade=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    if cascade.empty():return None
    gray=cv2.cvtColor(np.asarray(image),cv2.COLOR_RGB2GRAY)
    faces=cascade.detectMultiScale(gray,scaleFactor=1.08,minNeighbors=5,
                                  minSize=(max(28,image.width//24),)*2)
    candidates=[tuple(map(int,box)) for box in faces if box[1]+box[3]/2 < image.height*(.38 if framing=='full' else .65)
                and box[2] < image.width*.75]
    if len(candidates)!=1:return None
    x,y,w,h=candidates[0]
    edge=min(image.width,image.height,round(max(w,h)*1.75))
    left=max(0,min(image.width-edge,round(x+w/2-edge/2)))
    top=max(0,min(image.height-edge,round(y+h/2-edge/2)))
    return dict(box=(left,top,left+edge,top+edge),face=(x-left,y-top,w,h))


def face_plan(plan):
    segments=[dict(p,region='global') for p in plan['segments'] if p['group'] in ('identity','hair','face','style','description')]
    segments.insert(1,dict(text='close-up face portrait, detailed eyes, aligned pupils, natural facial proportions',group='face',region='global',weight=1.0))
    # Body/framing exclusions are irrelevant and can obstruct a cropped pass.
    negatives=[p.strip() for p in plan['negative_prompt'].split(',') if p.strip() not in
               ('cropped feet','cropped head','out of frame','close-up','bust portrait')]
    negatives.extend(['cross-eyed','misaligned eyes','deformed pupils'])
    return dict(segments=segments,negative_prompt=', '.join(negatives))


def blend_face(original,refined,crop):
    from PIL import Image,ImageDraw,ImageFilter
    box=crop['box'];x,y,w,h=crop['face'];size=(box[2]-box[0],box[3]-box[1])
    patch=refined.resize(size,Image.Resampling.LANCZOS)
    mask=Image.new('L',size,0)
    ImageDraw.Draw(mask).ellipse((x-w*.1,y-h*.15,x+w*1.1,y+h*1.12),fill=255)
    mask=mask.filter(ImageFilter.GaussianBlur(max(2,w*.08)))
    result=original.copy();result.paste(patch,box[:2],mask)
    return result


def local_focus(image,mask,role,plan):
    """Spend pixels on a small face/shoe edit, preserving the original canvas.

    Restrict automatic targeting to clearly separated full-body regions. An
    arbitrary/large brush selection continues using the original whole image.
    """
    if not supports_regions(role,'new'):return None
    bounds=mask.getbbox()
    if not bounds:return None
    x0,y0,x1,y1=bounds
    if y0>image.height*.76 and any(s['group']=='shoes' for s in plan['segments']):
        area='shoes'
        segments=[dict(s,region='global') for s in plan['segments'] if s['group'] in ('shoes','style')]
        segments.insert(0,dict(text='close-up of feet and shoes, natural foot anatomy',group='shoes',region='global',weight=1.0))
        negative='blurry, deformed feet, fused toes, extra toes, extra feet, text, watermark, logo'
        if any('single ankle strap' in s['text'] for s in segments):negative+=', multiple ankle straps, closed-toe shoes'
        focused=dict(segments=segments,negative_prompt=negative)
    elif y1<image.height*.30:
        area='face';focused=face_plan(plan)
    else:return None
    edge=min(image.width,image.height,max(round(max(x1-x0,y1-y0)*1.5),round(image.width*.3)))
    # Never crop away part of a brush stroke.
    if edge<max(x1-x0,y1-y0):return None
    left=max(0,min(image.width-edge,round((x0+x1-edge)/2)))
    top=max(0,min(image.height-edge,round((y0+y1-edge)/2)))
    box=(left,top,left+edge,top+edge)
    focused.update(prompt='. '.join(s['text'] for s in focused['segments']),version='focused-local-v1',
        priorities=plan.get('priorities',[]),warnings=[f'本次仅将{"鞋子" if area=="shoes" else "面部"}相关要求用于局部绘制，其余部位保留原图。'])
    return dict(box=box,area=area,plan=focused)

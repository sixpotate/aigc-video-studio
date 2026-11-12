"""Shared CPU face tracking for both mouth renderers."""
import hashlib
import pathlib
import cv2,numpy as np
from speaker_tracking import select_face
from settings import WORKSPACE
from production_errors import SharedRuntimeFailure

FACE_MODEL = WORKSPACE/'work/local_test/models/YuNet/face_detection_yunet_2023mar.onnx'
FACE_SHA256 = '8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4'


def reference_faces(frame):
    """Detect likely faces in color, on CPU; uncertain frames fail closed."""
    try:
        data=FACE_MODEL.read_bytes()
        if hashlib.sha256(data).hexdigest()!=FACE_SHA256:
            raise ValueError('模型校验失败')
        h,w=frame.shape[:2]
        detector=cv2.FaceDetectorYN.create('onnx',np.frombuffer(data,np.uint8),
            np.empty((0,),np.uint8),(w,h),0.75,0.3,5000,
            cv2.dnn.DNN_BACKEND_OPENCV,cv2.dnn.DNN_TARGET_CPU)
        _,found=detector.detect(frame)
        return [] if found is None else [np.asarray(face[:4],dtype=float) for face in found]
    except (OSError,ValueError,AttributeError,cv2.error) as exc:
        raise SharedRuntimeFailure('本地人脸预检模型不可用或校验失败，已暂停口型处理。') from exc


def check_reference(job):
    """Use the mouth renderer's own detector before spending time on motion."""
    import pathlib
    frame=cv2.imdecode(np.frombuffer(pathlib.Path(job['image']).read_bytes(),np.uint8),cv2.IMREAD_COLOR)
    if frame is None:raise ValueError('镜头参考图无法读取，请重新准备这一镜的画面。')
    if job.get('size'):frame=cv2.resize(frame,tuple(job['size']))
    h,w=frame.shape[:2]
    manual=job.get('face_box')
    if manual:
        x,y,bw,bh=manual
        if x<0 or y<0 or x+bw>100 or y+bh>100 or bw/100*w<32 or bh/100*h<32:
            raise ValueError('说话人的人脸范围过小或超出画面，请调整这一镜的取景。')
        return {'status':'ready','method':'manual'}
    region=job.get('actor_region')
    if region:region=[region[0]/100*w,region[1]/100*h,region[2]/100*w,region[3]/100*h]
    found=reference_faces(frame)
    box=select_face(found,None,region)
    if box is None or min(box[2:])<32:
        raise ValueError('当前画面里无法识别说话人的正脸，或脸部太小；尚未开始耗时的动作生成。请让该人物更靠近镜头、露出正脸后重试。')
    return {'status':'ready','method':'detector','face_box':[float(v) for v in box]}

def track_face(job):
    cap=cv2.VideoCapture(job['video']);src_fps=cap.get(cv2.CAP_PROP_FPS);frames=[]
    while True:
        ok,im=cap.read()
        if not ok:break
        frames.append(im)
    cap.release()
    if not frames:raise ValueError('动作视频没有可读取的画面。')
    h,w=frames[0].shape[:2]
    window=None
    if job.get('track_speech_only',False):
        start=float(job.get('speech_start',0));length=float(job.get('speech_seconds',0))
        if not np.isfinite([start,length]).all() or start<0 or length<=0 or start+length>len(frames)/src_fps+.1:
            raise ValueError('台词时间范围与动作片段不符，请重新准备本镜配音。')
        window=(start,start+length)
    detector=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_default.xml')
    alternate=cv2.CascadeClassifier(cv2.data.haarcascades+'haarcascade_frontalface_alt2.xml')
    previous=None;boxes=[];missed=0
    manual=job.get('face_box')
    hint=job.get('face_hint')
    region=job.get('actor_region')
    if region:region=[region[0]/100*w,region[1]/100*h,region[2]/100*w,region[3]/100*h]
    initial=manual or hint
    if initial:
        if len(initial)!=4 or not np.isfinite(initial).all():raise ValueError('说话人的人脸定位信息无效。')
        x,y,bw,bh=map(float,initial)
        if min(x,y)<0 or min(bw,bh)<=0 or x+bw>100 or y+bh>100:raise ValueError('说话人的人脸定位超出画面。')
        previous=np.array([x/100*w,y/100*h,bw/100*w,bh/100*h],np.float32)
    # A detected reference face is only an identity anchor, not a manual override.
    # Keep detecting and reject lost tracking instead of selecting a larger false
    # positive on the first video frame (foliage and hands can resemble faces).
    points=None;gray_before=None
    for index,frame in enumerate(frames):
        required=window is None or window[0]<=index/src_fps<window[1]
        gray=cv2.cvtColor(frame,cv2.COLOR_BGR2GRAY)
        if previous is not None and points is not None and len(points)>=6:
            nxt,status,_=cv2.calcOpticalFlowPyrLK(gray_before,gray,points,None,winSize=(25,25),maxLevel=3)
            good=status.ravel()==1
            if good.sum()>=6:
                matrix,_=cv2.estimateAffinePartial2D(points[good],nxt[good],method=cv2.RANSAC)
                if matrix is not None:
                    shift=np.median(nxt[good]-points[good],axis=0).ravel()
                    if np.linalg.norm(shift)<max(previous[2:])*.4:previous[:2]+=shift
        found=detector.detectMultiScale(gray,1.08,4,minSize=(28,28)) if not manual else []
        box=select_face(found,previous,region)
        if box is None and not manual:
            box=select_face(alternate.detectMultiScale(gray,1.06,4,minSize=(28,28)),previous,region)
        if box is not None:
            box=np.array(box,np.float32)
            previous=box if previous is None else previous*.65+box*.35
            missed=0
        else:
            # No mouth pixels are rendered before/after speech. Keep the verified
            # identity anchor through an impact or smoke, then reacquire it before
            # speech. Never relax lost-face rejection during actual dialogue.
            missed=missed+1 if required else 0
            if previous is None or (missed>16 and not manual):raise ValueError('无法稳定识别当前说话人的脸。请改用近景、减少转头，或手动填写该说话人的人脸位置。已生成的同框动作会保留，不会改给其他人配口型。')
        x,y,bw,bh=previous
        # End near the chin: including the neck makes the model repaint an
        # oversized lower face and shifts the generated mouth downwards.
        x1=max(0,round(x-.08*bw));y1=max(0,round(y-.07*bh));x2=min(w,round(x+1.08*bw));y2=min(h,round(y+1.03*bh))
        if x2-x1<32 or y2-y1<32:raise ValueError('人脸太小，口型需要更近的取景。')
        boxes.append((x1,y1,x2,y2))
        mask=np.zeros((h,w),np.uint8);mask[max(0,round(y)):min(h,round(y+bh*.58)),max(0,round(x)):min(w,round(x+bw))]=255
        points=cv2.goodFeaturesToTrack(gray,70,.015,4,mask=mask);gray_before=gray
    return frames,boxes,src_fps

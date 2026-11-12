"""Constrain initial face selection to the selected speaker, then gate tracking."""
import math


def select_face(found, previous=None, region=None):
    candidates=[]
    for box in found:
        x,y,w,h=map(float,box);cx=x+w/2;cy=y+h/2
        if previous is None and region:
            rx,ry,rw,rh=region
            if not (rx<=cx<=rx+rw and ry<=cy<=ry+rh):continue
        if previous is not None:
            px,py,pw,ph=previous
            distance=math.hypot(cx-px-pw/2,cy-py-ph/2)
            if distance>max(pw,ph)*.85 or not .45<=w/max(pw,1)<=2:continue
            score=-distance
        else:score=w*h
        candidates.append((score,box))
    return max(candidates,key=lambda item:item[0])[1] if candidates else None

"""Validated local image/audio uploads. Clients only receive content IDs."""
import base64,hashlib,io,json,re,subprocess
from settings import SCENE_ASSET_DIR,CREATE_NO_WINDOW

ASSET_DIR=SCENE_ASSET_DIR
def asset_path(value,kind='background'):
    suffix='png' if kind=='background' else 'wav'
    if not isinstance(value,str) or not re.fullmatch(r'[a-f0-9]{64}',value):raise ValueError('素材编号无效。')
    path=ASSET_DIR/kind/(value+'.'+suffix)
    if not path.is_file():raise ValueError('素材不存在，请重新导入。')
    return path

def assets():
    result=[]
    for path in ASSET_DIR.glob('*/*.json'):
        try:
            item=json.loads(path.read_text('utf-8'));asset_path(item['id'],item['kind']);result.append(item)
        except (OSError,ValueError,KeyError):continue
    return sorted(result,key=lambda x:x['name'])

def upload(data):
    kind=data.get('kind');name=data.get('name','本机素材')
    if kind not in ('background','music'):raise ValueError('素材类型无效。')
    if not isinstance(name,str) or len(name)>160:raise ValueError('素材名称过长。')
    try:raw=base64.b64decode(data.get('data',''),validate=True)
    except (ValueError,TypeError):raise ValueError('素材内容不是有效文件。')
    if not raw or len(raw)>20*1024*1024:raise ValueError('素材最大20MB。')
    folder=ASSET_DIR/kind;folder.mkdir(parents=True,exist_ok=True)
    ident=hashlib.sha256(raw).hexdigest();meta=dict(id=ident,name=name,kind=kind)
    if kind=='background':
        from PIL import Image,ImageOps,UnidentifiedImageError
        try:
            with Image.open(io.BytesIO(raw)) as source:
                if source.width*source.height>32_000_000:raise ValueError('图片尺寸过大。')
                image=ImageOps.exif_transpose(source).convert('RGB');image.thumbnail((2560,2560))
                target=folder/(ident+'.png');temp=target.with_suffix('.partial.png');image.save(temp);temp.replace(target)
                meta.update(width=image.width,height=image.height)
        except (UnidentifiedImageError,OSError):raise ValueError('请选择有效的PNG、JPG或WebP图片。')
    else:
        source=folder/(ident+'.upload');temp=folder/(ident+'.partial.wav');target=folder/(ident+'.wav')
        source.write_bytes(raw)
        try:
            result=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','json',str(source)],capture_output=True,creationflags=CREATE_NO_WINDOW,timeout=15)
            info=json.loads(result.stdout);seconds=float(info.get('format',{}).get('duration',0))
            if result.returncode or not 1<=seconds<=900:raise ValueError('音乐需为1至900秒的有效音频。')
            subprocess.run(['ffmpeg','-y','-v','error','-i',str(source),'-vn','-ar','48000','-ac','2',str(temp)],check=True,creationflags=CREATE_NO_WINDOW,timeout=90)
            temp.replace(target);meta['seconds']=seconds
        except (subprocess.SubprocessError,ValueError,KeyError):raise ValueError('无法读取音乐，请使用MP3、WAV或M4A文件。')
        finally:
            source.unlink(missing_ok=True);temp.unlink(missing_ok=True)
    meta['url']=f'/director-asset/{kind}/{target.name}'
    (folder/(ident+'.json')).write_text(json.dumps(meta,ensure_ascii=False),'utf-8')
    from asset_names import try_sync_scenes
    try_sync_scenes(ASSET_DIR)
    return dict(asset=meta,assets=assets())

def preview_music(data):
    from director_production import sound_settings
    from director_sound import music_track
    import shutil
    track=sound_settings({'track':data.get('track')})['track']
    if track=='none':raise ValueError('请先选择配乐。')
    folder=ASSET_DIR/'music';folder.mkdir(exist_ok=True,parents=True)
    source=music_track(track,12,folder);ident=hashlib.sha256(source.read_bytes()).hexdigest();target=folder/(ident+'.wav')
    if source!=target and not target.is_file():shutil.copy2(source,target)
    return dict(url=f'/director-asset/music/{ident}.wav',seconds=12)

"""Loopback-only HTTP interface. Generation and validation live in jobs.py."""
import io
import json
import os
import re
import secrets
import socket
import sys
import threading
import traceback
import urllib.request
import webbrowser
import zipfile
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse
from jobs import Jobs
from settings import APP_DIR, CHARACTER_DIR, EXPORT_DIR, LIBRARY, ROLES, STORAGE, VIDEO_DIR, LOG_DIR
from director_schema import DIRECTOR_DIR,VOICES,EMOTIONS,CAMERAS,MAX_SHOTS
from director_script import split_script
from voice_catalog import VOICE_DETAILS,PREVIEW_DIR
from portrait_spec import public_options, inspect_role
from characters import normalize_role
from director_assets import assets,upload,asset_path,preview_music
from director_production import MUSIC_STYLES,EFFECTS,SPEECH_KINDS
from local_browser import open_studio
from production_errors import SharedRuntimeFailure
from runtime_health import runtime_status

HOST = '127.0.0.1'
PORT = int(os.environ.get('AI_DRAMA_PORT', '8765'))
TOKEN = secrets.token_urlsafe(24)
JOBS = None
PRODUCT = 'local-drama-studio-v2'
ASSETS = {'/': 'create.html', '/library': 'index.html', '/styles.css': 'static/styles.css', '/app.js': 'static/app.js', '/api.js': 'static/api.js', '/characters.js':'static/characters.js', '/characters.css':'static/characters.css'}
ASSETS.update({'/director':'director.html','/director.js':'static/director.js','/director.css':'static/director.css'})
ASSETS['/director_cast.js']='static/director_cast.js'
ASSETS['/portrait-controls.js'] = 'static/portrait-controls.js'
ASSETS['/image-model-select.js'] = 'static/image-model-select.js'
ASSETS['/role-voice.js'] = 'static/role-voice.js'
ASSETS['/material-library.js'] = 'static/material-library.js'
ASSETS['/director_production.js']='static/director_production.js'
ASSETS['/production_quality.js']='static/production_quality.js'
ASSETS.update({'/create':'create.html', '/story.js':'static/story.js', '/story.css':'static/story.css', '/director_story.js':'static/director_story.js'})


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def respond(self, body, content_type='application/json; charset=utf-8', status=200, filename=None):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if filename:
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def do_GET(self):
        path = unquote(urlparse(self.path).path)
        if path in ASSETS:
            file = APP_DIR / ASSETS[path]
            kind = {'.html':'text/html', '.css':'text/css', '.js':'text/javascript'}[file.suffix]
            return self.respond(file.read_bytes(), kind+'; charset=utf-8')
        if path == '/api/config':
            return self.respond(dict(episodes=json.loads((LIBRARY if LIBRARY.is_file() else APP_DIR/'defaults'/'scripts.json').read_text(encoding='utf-8'))['episodes'], characters=ROLES, token=TOKEN, product=PRODUCT,voices=VOICES,voice_details=VOICE_DETAILS,max_director_shots=MAX_SHOTS,emotions=EMOTIONS,cameras=CAMERAS,portrait_options=public_options(),assets=assets(),music_styles=MUSIC_STYLES,effects=EFFECTS,speech_kinds=SPEECH_KINDS))
        if path == '/api/status':
            return self.respond(JOBS.snapshot())
        if path == '/api/sound-library':
            from sound_library import public_catalogue
            return self.respond(public_catalogue())
        if re.fullmatch(r'/sound-library/[a-f0-9]{32}',path):
            from sound_library import media_path
            try:
                file=media_path(path.rsplit('/',1)[-1])
                return self.respond(file.read_bytes(),{'.ogg':'audio/ogg','.wav':'audio/wav','.mp3':'audio/mpeg','.flac':'audio/flac'}[file.suffix.lower()])
            except (OSError,ValueError,KeyError):
                return self.respond({'error':'本地音效不可用。'},status=404)
        if path == '/api/director/projects':
            return self.respond(JOBS.director.catalogue())
        if path == '/api/story/projects':
            return self.respond(JOBS.story.catalogue())
        if path == '/api/ping':
            return self.respond(dict(ok=True, product=PRODUCT))
        asset=re.fullmatch(r'/director-asset/(background|music)/([a-f0-9]{64})\.(png|wav)',path)
        if asset:
            try:return self.media(asset_path(asset[2],asset[1]))
            except ValueError:return self.respond({'error':'素材不存在。'},status=404)
        if re.fullmatch(r'/voice-preview/[a-f0-9]{64}\.wav',path):
            file=PREVIEW_DIR/path.rsplit('/',1)[1]
            if file.is_file():return self.media(file)
        if re.fullmatch(r'/media/[a-f0-9]{32}/shot_\d{2}_v\d+\.png', path):
            file = STORAGE / path.removeprefix('/media/')
            if file.is_file():
                return self.respond(file.read_bytes(), 'image/png')
        if re.fullmatch(r'/characters/media/[a-zA-Z0-9_-]{1,48}/[a-f0-9]{32}\.png',path):
            file=CHARACTER_DIR/path.removeprefix('/characters/media/')
            if file.is_file():
                return self.respond(file.read_bytes(),'image/png')
        if re.fullmatch(r'/director-media/[a-f0-9]{32}/[a-f0-9]{64}\.(wav|mp4|png)',path):
            file=DIRECTOR_DIR/path.removeprefix('/director-media/')
            if file.is_file():return self.media(file)
        self.respond({'error':'没有找到这个文件。'}, status=404)

    def media(self,file):
        size=file.stat().st_size;start=0;end=size-1;status=200
        requested=self.headers.get('Range')
        if requested:
            match=re.fullmatch(r'bytes=(\d*)-(\d*)',requested)
            if not match or not any(match.groups()):
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            a,b=match.groups()
            if not a:start=max(0,size-int(b))
            else:start=int(a)
            if a and b:end=min(end,int(b))
            if start>=size or start>end:
                self.send_response(416);self.send_header('Content-Range',f'bytes */{size}');self.end_headers();return
            status=206
        self.send_response(status)
        self.send_header('Content-Type',{'.wav':'audio/wav','.mp4':'video/mp4','.png':'image/png'}[file.suffix])
        self.send_header('Content-Length',str(end-start+1));self.send_header('Accept-Ranges','bytes')
        self.send_header('X-Content-Type-Options','nosniff')
        if status==206:self.send_header('Content-Range',f'bytes {start}-{end}/{size}')
        self.end_headers()
        try:
            with file.open('rb') as source:
                source.seek(start);remaining=end-start+1
                while remaining:
                    chunk=source.read(min(1024*256,remaining))
                    if not chunk:break
                    self.wfile.write(chunk);remaining-=len(chunk)
        except (BrokenPipeError,ConnectionResetError):pass

    def do_POST(self):
        path = urlparse(self.path).path
        if self.headers.get('X-Local-Token') != TOKEN:
            return self.respond({'error':'页面已过期，请刷新后重试。'}, status=403)
        origin = self.headers.get('Origin')
        if origin and origin != f'http://{HOST}:{PORT}':
            return self.respond({'error':'不允许来自其他页面的请求。'}, status=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > (30*1024*1024 if path=='/api/director/upload' else 8*1024*1024 if path in ('/api/director/generate','/api/director/save') else 2*1024*1024):
                raise ValueError('提交的内容过长。')
            data = json.loads(self.rfile.read(length) or b'{}')
            if not isinstance(data, dict):
                raise ValueError('提交的数据格式不正确。')
            actions = {'/api/generate': JOBS.generate, '/api/regenerate': JOBS.regenerate, '/api/video': JOBS.video,
                       '/api/stop': lambda _d: JOBS.stop(), '/api/reset': lambda _d: JOBS.reset(),
                       '/api/director/save':JOBS.director.save,'/api/director/generate':JOBS.director.start,
                       '/api/director/split':lambda value:split_script(value,JOBS.characters),'/api/voices/preview':JOBS.voice_previews.start,
                       '/api/director/upload':upload,'/api/director/music-preview':preview_music,'/api/director/open':JOBS.director.open_project}
            actions.update({'/api/story/start':JOBS.story.start, '/api/story/save':JOBS.story.save,
                            '/api/story/produce':JOBS.story.produce, '/api/story/open':JOBS.story.open, '/api/story/commit':JOBS.story.commit,
                            '/api/story/research':JOBS.story.research})
            if path in actions:
                return self.respond(actions[path](data))
            if path=='/api/image-engine/encoder':
                return self.respond(JOBS.set_text_encoder(data))
            if path=='/api/image-engine/select':
                return self.respond(JOBS.set_image_engine(data))
            if path=='/api/characters/generate':
                return self.respond(JOBS.portrait(data))
            if path=='/api/characters/inspect':
                return self.respond(dict(issues=inspect_role(normalize_role(data))))
            if path=='/api/characters/detail':
                return self.respond(JOBS.characters.portrait_detail(data.get('id'),data.get('image')))
            if path in ('/api/characters/save','/api/characters/archive','/api/characters/restore','/api/characters/choose'):
                return self.respond(JOBS.character_action(path.split('/')[-1],data))
            if path=='/api/characters/open-folder':
                os.startfile(CHARACTER_DIR)
                return self.respond({'ok':True})
            if path == '/api/export':
                return self.export(data)
            if path == '/api/open-output':
                VIDEO_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(VIDEO_DIR)
                return self.respond({'ok':True})
            if path == '/api/open-images':
                EXPORT_DIR.mkdir(parents=True, exist_ok=True)
                os.startfile(EXPORT_DIR)
                return self.respond({'ok':True})
            if path == '/api/shutdown':
                if JOBS.snapshot()['running']:
                    raise ValueError('请先停止生成，再关闭制作器。')
                self.respond({'ok':True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return
            self.respond({'error':'未知操作。'}, status=404)
        except SharedRuntimeFailure as exc:
            self.respond({'error':str(exc),'runtime_safety':runtime_status()},status=409)
        except (ValueError, TypeError, KeyError) as exc:
            self.respond({'error':str(exc)}, status=400)
        except Exception:
            traceback.print_exc()
            self.respond({'error':'操作未完成，请查看启动日志。'}, status=500)

    def export(self, data):
        state = JOBS.snapshot()
        project = state.get('project')
        if not project or data.get('project_id') != project['id']:
            raise ValueError('请先生成分镜，再导出图片。')
        if state['running']:
            raise ValueError('请等待任务完成或停止后再导出。')
        ids = data.get('ids', [])
        if not isinstance(ids, list) or not ids or any(type(x) is not int for x in ids):
            raise ValueError('请至少选择一张图片。')
        selected = [s for s in project['shots'] if s['id'] in ids and s.get('image')]
        if len(selected) != len(set(ids)):
            raise ValueError('所选分镜尚未生成完成。')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
            for shot in selected:
                source = STORAGE / project['id'] / shot['image'].split('/')[-1]
                archive.write(source, f'镜头{shot["id"]:02d}.png')
            metadata = dict(title=project['title'], script=project['script'], characters=project['characters'], settings=project['settings'], shots=selected,
                            note=('画面使用已生成的自定义角色立绘与剧本文字排版，不生成新动作。' if project['settings'].get('source')=='character' else '画面来自本地3D动作模板，编辑角色不会替换模板人物。')+' 更高输出尺寸使用缩放。')
            archive.writestr('分镜说明.json', json.dumps(metadata, ensure_ascii=False, indent=2))
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        title = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', project['title']).strip(' .')[:48] or '未命名漫剧'
        output = EXPORT_DIR / f'{datetime.now():%Y%m%d_%H%M%S_%f}_{title}_分镜.zip'
        output.write_bytes(buffer.getvalue())
        self.respond(buffer.getvalue(), 'application/zip', filename='storyboard-images.zip')


class LocalHTTPServer(ThreadingHTTPServer):
    # On Windows SO_REUSEADDR can allow two live servers to own the same port,
    # leaving different pages connected to different in-memory job queues.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name == 'nt':
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def main():
    global JOBS
    url = f'http://{HOST}:{PORT}/'
    try:
        server = LocalHTTPServer((HOST, PORT), Handler)
    except OSError:
        existing = json.load(urllib.request.urlopen(url+'api/ping', timeout=2))
        if existing.get('product') != PRODUCT:
            raise RuntimeError('端口被旧版程序或其他服务占用，请先关闭旧版制作器。')
        if '--no-browser' not in sys.argv:
            open_studio(url+'create')
        return
    # Only the process that owns the port may restore or change saved job state.
    # In particular, opening a second window must not cancel an active story job.
    JOBS = Jobs()
    if '--no-browser' not in sys.argv:
        threading.Timer(.5, lambda: open_studio(url+'create')).start()
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        (LOG_DIR/'启动错误.log').write_text(traceback.format_exc(), encoding='utf-8')
        raise


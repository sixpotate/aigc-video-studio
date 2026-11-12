"""Readable user-facing names; stable internal IDs remain unchanged."""
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import shutil
import tempfile
import unicodedata


def safe_name(value, fallback='未命名'):
    value = unicodedata.normalize('NFC', str(value or ''))
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', value).strip().rstrip('. ')
    value = value[:70].rstrip('. ') or fallback
    if re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', value, re.I):
        value = '文件_' + value
    return value


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_write(path, content):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.命名-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def inside(root, relative):
    root = Path(root).resolve()
    path = (root / relative).resolve()
    if path == root or not path.is_relative_to(root):
        raise ValueError('文件路径超出素材目录。')
    return path


def _export_named(root, records, kind):
    """Copies are independent of originals. Never overwrite a user-edited export."""
    root = Path(root).resolve()
    view = root / '按名称查看'
    view.mkdir(exist_ok=True)
    manifest_path = view / '文件对应表.json'
    previous = json.loads(manifest_path.read_text('utf-8')) if manifest_path.exists() else {}
    entries, lines = {}, [kind + '文件目录', '这些文件可以直接取用；软件内部原图和编号保持不变。', '']
    for record in records:
        key, source, relative, title = record
        source = Path(source).resolve()
        if not source.is_relative_to(root) or not source.is_file():
            continue
        digest = sha(source)
        target = inside(view, relative)
        old = previous.get(key, {})
        # Prefer an existing intact managed copy, including after a user rename.
        if target.exists() and sha(target) != digest:
            target = target.with_name(target.stem + '_原始版本_' + digest[:8] + target.suffix)
        if target.exists() and sha(target) != digest:
            raise ValueError('同名文件已被修改，请保留文件并检查命名冲突。')
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            fd, temp = tempfile.mkstemp(prefix='.图片-', suffix='.tmp', dir=target.parent)
            os.close(fd)
            try:
                shutil.copy2(source, temp)
                os.replace(temp, target)
            finally:
                Path(temp).unlink(missing_ok=True)
        relative = target.relative_to(view).as_posix()
        entries[key] = dict(file=relative, source=source.relative_to(root).as_posix(), sha256=digest)
        lines.append(title + '：' + relative.replace('/', '\\'))
        # Only remove our old copy if its bytes are still unchanged.
        if old.get('file') and old['file'] != relative:
            old_path = inside(view, old['file'])
            if old_path.is_file() and sha(old_path) == old.get('sha256'):
                old_path.unlink()
                parent = old_path.parent
                if parent != view:
                    try:
                        parent.rmdir()
                    except OSError:
                        pass
    # Preserve entries not in this snapshot: another job may still reference them.
    merged = dict(previous)
    merged.update(entries)
    atomic_write(manifest_path, json.dumps(merged, ensure_ascii=False, indent=2))
    atomic_write(view / '文件目录.txt', '\n'.join(lines) + '\n')
    return entries


def sync_character_exports(root, roles):
    root = Path(root)
    records = []
    for role in roles:
        ident = str(role.get('id', ''))
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,48}', ident):
            continue
        name = safe_name(role.get('name'), '未命名角色')
        status = '历史角色' if role.get('archived') else '在用角色'
        folder = name + '（' + hashlib.sha256(ident.encode()).hexdigest()[:8] + '）'
        for number, version in enumerate(role.get('images', []), 1):
            url = str(version.get('image', ''))
            match = re.fullmatch(r'/characters/media/([a-zA-Z0-9_-]{1,48})/([a-f0-9]{32})\.png', url)
            if not match or match[1] != ident:
                continue
            relative = f'{status}/{folder}/{name}_形象{number:03d}.png'
            title = name + f' · 形象{number:03d}' + ('（当前选用）' if role.get('image') == url else '')
            records.append((ident + '/' + match[2], inside(root, ident + '/' + match[2] + '.png'), relative, title))
    return _export_named(root, records, '角色图片')


def sync_scene_exports(root):
    root = Path(root)
    records = []
    for kind, label, extension in [('background', '场景图片', '.png'), ('music', '音乐', '.wav')]:
        for metadata in sorted((root / kind).glob('*.json')):
            item = json.loads(metadata.read_text('utf-8'))
            ident = str(item.get('id', ''))
            if not re.fullmatch(r'[a-f0-9]{64}', ident) or item.get('kind') != kind:
                continue
            name = safe_name(item.get('name'), label)
            if name.lower().endswith(('.png', '.jpg', '.jpeg', '.webp', '.wav', '.mp3', '.m4a')):
                name = name.rsplit('.', 1)[0]
            filename = f'{label}/{name}_{ident[:8]}{extension}'
            records.append((kind + '/' + ident, inside(root, kind + '/' + ident + extension), filename, name))
    return _export_named(root, records, '场景与音乐')


def try_sync_characters(root, roles):
    try:
        return sync_character_exports(root, roles)
    except (OSError, ValueError, TypeError, KeyError):
        logging.exception('角色已保存，但中文取用目录未同步。原图仍可正常使用。')


def try_sync_scenes(root):
    try:
        return sync_scene_exports(root)
    except (OSError, ValueError, TypeError, KeyError):
        logging.exception('素材已保存，但中文取用目录未同步。原文件仍可正常使用。')

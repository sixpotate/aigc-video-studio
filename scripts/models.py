#!/usr/bin/env python3
"""Download pinned publicly available components. Never overwrites local files.

Use --check-only for a no-write plan. A successful component verification checks
file SHA-256, but does not assert an end-to-end inference test.
"""
from __future__ import annotations
import argparse, hashlib, json, os, shutil, sys, tempfile, urllib.error, urllib.request, zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'scripts' / 'model-manifest.json'
GROUPS = {'basic': (), 'image': ('image',), 'voice': ('voice',),
          'motion': ('motion',), 'lip': ('lip',), 'all': ('image','voice','motion','lip')}
# These are blocked *before* any download, including under --yes. This is not a
# statement that the user may not install the components manually.
UNAVAILABLE = {
}
CHUNK = 1024 * 1024

def within(path: Path) -> Path:
    result = path.resolve()
    try:
        result.relative_to(ROOT.resolve())
    except ValueError:
        raise RuntimeError('目标路径或链接越出安装目录：' + str(path))
    return result

def entries(profile):
    data = json.loads(MANIFEST.read_text(encoding='utf-8'))
    if data.get('schema') != 1:
        raise RuntimeError('模型清单格式不支持')
    groups = GROUPS[profile]
    return [item for item in data['files'] if item['group'] in groups]

def hash_file(path):
    d = hashlib.sha256()
    with path.open('rb') as source:
        while True:
            block = source.read(CHUNK)
            if not block:
                break
            d.update(block)
    return d.hexdigest()

def matches(path, item):
    return path.is_file() and path.stat().st_size == item['size'] and hash_file(path) == item['sha256']

def members(archive):
    with zipfile.ZipFile(archive) as z:
        result=[]
        for info in z.infolist():
            name=info.filename.replace('\\','/')
            p=PurePosixPath(name)
            if (p.is_absolute() or '..' in p.parts or ':' in name or not p.parts
                or (info.external_attr >> 16) & 0o170000 == 0o120000):
                raise RuntimeError('压缩包包含不安全的路径：'+name)
            if not info.is_dir():
                result.append((info, p))
        if not result:
            raise RuntimeError('压缩包为空')
        return result

def install_archive(item, archive, verify_only=False):
    target=within(ROOT / item['extract_to'])
    # First inspect every path and compare existing content; never replace one.
    listing=members(archive)
    with zipfile.ZipFile(archive) as z:
        for info, rel in listing:
            out=within(target.joinpath(*rel.parts))
            if out.exists():
                if not out.is_file() or out.stat().st_size != info.file_size:
                    raise RuntimeError('运行器文件冲突，保留原文件：'+str(out))
                h=hashlib.sha256()
                with z.open(info) as src:
                    for b in iter(lambda: src.read(CHUNK), b''):
                        h.update(b)
                if hash_file(out) != h.hexdigest():
                    raise RuntimeError('运行器文件冲突，保留原文件：'+str(out))
            elif verify_only:
                raise RuntimeError('缺少运行器文件：'+str(out))
        if verify_only:
            return
        for info, rel in listing:
            out=within(target.joinpath(*rel.parts))
            if out.exists():
                continue
            out.parent.mkdir(parents=True, exist_ok=True)
            # Exclusive create: no overwriting even if another process races us.
            with z.open(info) as src, out.open('xb') as dst:
                shutil.copyfileobj(src,dst,CHUNK)


# A fixed upstream commit plus narrowly checked changes used by the existing
# offload runner. Hashes bind both the original file and the patched output.
SOURCE_PATCHES = {
    'lightx2v/common/ops/mm/mm_weight.py': (
        'e69c900065d9746bd7d6f29cec45f9f5134f04b5d97b6079662613d540fe0fd5',
        'fea3a590f891edda99f83d574572cbb806d6052128aac5c594751ee911d35ffd',
        b'        self.bias_name = bias_name\n        self.create_cuda_buffer = create_cuda_buffer',
        b'        self.bias_name = bias_name\n        # Bias-free offloaded layers do not populate a bias buffer.\n        self.bias = None\n        self.create_cuda_buffer = create_cuda_buffer'),
    'lightx2v/models/input_encoders/hf/wan/t5/model.py': (
        'a0166f73dead4c1655d2d54d19afe102c16cc1f2add2cb021472bb6a53e02a69',
        'bd8e10084415760088b2c2fd9d6e5ee5e21ef68f8097406e77549777fbb6f94a',
        b'        self.token_embedding = vocab.to(dtype) if isinstance(vocab, nn.Embedding) else nn.Embedding(vocab, dim, dtype=dtype)',
        b'        # Inference loads the complete pretrained embedding immediately below.\n        # Avoid a costly random initialization of the 256k-token table.\n        self.token_embedding = vocab.to(dtype) if isinstance(vocab, nn.Embedding) else nn.Embedding(vocab, dim, _weight=torch.empty(vocab, dim, dtype=dtype))'),
}

def source_files(item, archive):
    result={}
    with zipfile.ZipFile(archive) as z:
        for info, p in members(archive):
            if p.parts[0] != item['source_root'] or len(p.parts) < 2:
                raise RuntimeError('源码包目录结构不符合固定版本：'+str(p))
            rel=PurePosixPath(*p.parts[1:]).as_posix()
            allowed=item.get('source_include')
            if allowed and not any(rel == prefix or (prefix.endswith('/') and rel.startswith(prefix)) for prefix in allowed):
                continue
            if rel in result:
                raise RuntimeError('源码包包含重复路径：'+rel)
            data=z.read(info)
            if item.get('source_patch') == 'lightx2v' and rel in SOURCE_PATCHES:
                before,after,old,new=SOURCE_PATCHES[rel]
                if hashlib.sha256(data).hexdigest()!=before or data.count(old)!=1:
                    raise RuntimeError('源码补丁输入不匹配：'+rel)
                data=data.replace(old,new,1)
                if hashlib.sha256(data).hexdigest()!=after:
                    raise RuntimeError('源码补丁输出不匹配：'+rel)
            result[rel]=data
    if not result:
        raise RuntimeError('源码包不含必要文件')
    if item.get('source_patch') == 'lightx2v' and not SOURCE_PATCHES.keys() <= result.keys():
        raise RuntimeError('源码包缺少补丁目标文件')
    return result

def install_source(item,archive,verify_only=False):
    target=within(ROOT/item['source_to'])
    content=source_files(item,archive)
    if target.exists():
        if not target.is_dir(): raise RuntimeError('源码目标被已有文件占用：'+str(target))
        for rel,data in content.items():
            dest=within(target.joinpath(*PurePosixPath(rel).parts))
            if not dest.is_file() or dest.stat().st_size!=len(data) or hash_file(dest)!=hashlib.sha256(data).hexdigest():
                raise RuntimeError('已有源码不完整或内容不同；已保留，未修改：'+str(dest))
        return
    if verify_only:
        raise RuntimeError('缺少源码运行器：'+str(target))
    target.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.aigc-source-stage-',dir=target.parent))
    for rel,data in content.items():
        dest=within(stage.joinpath(*PurePosixPath(rel).parts))
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('xb') as out:out.write(data)
    # Windows rename does not replace an existing destination; hard-stop rather
    # than modify a directory the user may have created meanwhile.
    if target.exists(): raise RuntimeError('源码目录已出现；保留新目录与暂存目录：'+str(stage))
    os.rename(stage,target)

def download(item):
    dest=within(ROOT / item['dest'])
    if dest.exists():
        print('校验已有文件：',dest,flush=True)
        if not matches(dest,item):
            raise RuntimeError('已有文件不匹配，已保留，请自行确认：'+str(dest))
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    part=within(dest.with_name(dest.name+'.aigc-download-part'))
    meta=within(dest.with_name(dest.name+'.aigc-download.json'))
    marker={'url':item['url'],'size':item['size'],'sha256':item['sha256']}
    if part.exists() or meta.exists():
        if not meta.is_file() or (part.exists() and not part.is_file()):
            raise RuntimeError('检测到不完整的续传标记；原文件已保留：'+str(part))
        if json.loads(meta.read_text(encoding='utf-8')) != marker:
            raise RuntimeError('续传来源不匹配，已保留：'+str(part))
        if not part.exists():
            with part.open('xb'):
                pass
    else:
        with meta.open('x',encoding='utf-8') as m:
            json.dump(marker,m)
        with part.open('xb'):
            pass
    offset=part.stat().st_size
    if offset > item['size']:
        raise RuntimeError('续传文件超过预期大小，已保留：'+str(part))
    if offset < item['size']:
        headers={'User-Agent':'AIGC-open-source-installer/1.0','Accept-Encoding':'identity'}
        if offset: headers['Range']=f'bytes={offset}-'
        print(f"下载 {dest.name}：从 {offset / 1e9:.2f} GB / {item['size']/1e9:.2f} GB 开始",flush=True)
        req=urllib.request.Request(item['url'],headers=headers)
        with urllib.request.urlopen(req,timeout=60) as resp:
            if offset and (resp.status != 206 or not resp.headers.get('Content-Range','').startswith(f'bytes {offset}-')):
                raise RuntimeError('服务器不支持安全续传，旧文件保留：'+str(part))
            previous=-1
            with part.open('ab') as out:
                while True:
                    block=resp.read(CHUNK)
                    if not block: break
                    out.write(block)
                    offset += len(block)
                    if offset > item['size']:
                        raise RuntimeError('服务器发送数据超出预期，已保留下载文件')
                    percent=int(offset*100/item['size'])
                    if percent != previous and (percent % 5 == 0 or percent == 100):
                        print(f'  {percent}% ({offset/1e9:.2f} GB)',flush=True)
                        previous=percent
    print('校验 SHA-256：',dest.name,flush=True)
    if not matches(part,item):
        raise RuntimeError('下载文件大小或 SHA-256 不匹配，已保留：'+str(part))
    # Hardlink provides atomic exclusive placement without duplicating huge files.
    os.link(part,dest)
    part.unlink()
    meta.unlink()

def verify(items):
    for item in items:
        path=within(ROOT/item['dest'])
        print('核验：',path,flush=True)
        if not matches(path,item):
            raise RuntimeError('缺少文件或大小/哈希不匹配：'+str(path))
        if item.get('extract_to'):
            install_archive(item,path,True)
        if item.get('source_to'):
            install_source(item,path,True)

def preflight(profile, items):
    for group in GROUPS[profile]:
        if group in UNAVAILABLE:
            raise RuntimeError(UNAVAILABLE[group]+' 当前安装选择不可用，尚未下载任何内容。')
    total=0
    for item in items:
        path=within(ROOT/item['dest'])
        if path.exists():
            print('预检查已有文件：',path,flush=True)
            if not matches(path,item):
                raise RuntimeError('已有文件大小或哈希不符，已保留：'+str(path))
        else:
            part=within(path.with_name(path.name+'.aigc-download-part'))
            meta=within(path.with_name(path.name+'.aigc-download.json'))
            if part.exists() or meta.exists():
                marker={'url':item['url'],'size':item['size'],'sha256':item['sha256']}
                if not meta.is_file() or (part.exists() and not part.is_file()):
                    raise RuntimeError('检测到不完整的续传标记；原文件已保留：'+str(part))
                if json.loads(meta.read_text(encoding='utf-8')) != marker:
                    raise RuntimeError('续传来源不匹配，已保留：'+str(part))
                downloaded=part.stat().st_size if part.exists() else 0
                if downloaded > item['size']:
                    raise RuntimeError('续传文件超过预期大小，已保留：'+str(part))
                total+=item['size']-downloaded
            else:
                total+=item['size']
    print(f'计划包含 {len(items)} 个文件，缺少文件最多需下载 {total/1e9:.2f} GB。')
    print('解压和安装依赖还需要额外空间；下载固定上游版本并逐文件校验。')
    print('本项目不包含用户作品；模型、第三方程序及许可证各自适用。')
    if profile in ('image','all'):
        print('图像使用 FLUX.2 klein 4B；CUDA 12.4 运行器要求兼容的 NVIDIA 驱动与硬件。')
        print('Qwen3.5 当前仅安装文本权重；视觉审核所需的额外投影模型尚未包含。')
    return total

def main():
    p=argparse.ArgumentParser(description='安装或验证所选本地模型；不会覆盖已有文件。')
    p.add_argument('command',choices=('list','install','verify'))
    p.add_argument('--profile',choices=tuple(GROUPS),default='basic')
    p.add_argument('--check-only',action='store_true')
    p.add_argument('--yes',action='store_true')
    args=p.parse_args()
    if args.command=='list':
        print('basic: 应用基础环境；image: 4B 绘图、翻译、编剧；voice: Qwen 语音；motion: Wan 动作模型；lip: MuseTalk 口型；all: 全部组件。')
        return 0
    items=entries(args.profile)
    need=preflight(args.profile,items)
    if args.check_only: return 0
    if args.command=='verify':
        verify(items)
        print('文件完整性校验通过；这不等于完整推理验收。')
        return 0
    if not items:
        print('基础配置无需下载模型。')
        return 0
    free=shutil.disk_usage(ROOT).free
    # Extra 2 GB provides minimum unpacking space; Python/package requirements
    # are checked separately by the outer installer.
    required=need+2_000_000_000
    if free < required:
        raise RuntimeError(f'磁盘可用 {free/1e9:.2f} GB，低于预计 {required/1e9:.2f} GB。')
    if not args.yes:
        print('将从模型作者和第三方官方站点下载，须遵守各自许可证及使用条件。')
        if input('继续？[y/N] ').strip().lower() not in ('y','yes'):
            print('已取消。');return 1
    for item in items:
        download(item)
        if item.get('extract_to'):
            install_archive(item,within(ROOT/item['dest']))
        if item.get('source_to'):
            install_source(item,within(ROOT/item['dest']))
    verify(items)
    if 'image' in GROUPS[args.profile]:
        # Do not alter any existing preference; the visible dropdown can choose flux.
        print('绘图模型已就绪：请在程序设置中选择“FLUX.2 klein 4B · 本地”。已有首选项未被修改。')
    print('所选文件已核验；需在目标机器另行测试实际生成。')
    return 0

if __name__=='__main__':
    try:
        sys.exit(main())
    except (OSError,ValueError,RuntimeError,urllib.error.URLError,zipfile.BadZipFile) as exc:
        print('安装/校验未完成：',exc,file=sys.stderr)
        sys.exit(1)

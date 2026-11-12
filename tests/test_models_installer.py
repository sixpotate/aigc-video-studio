import hashlib, importlib.util, io, json, os, pathlib, tempfile, threading, unittest, zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

SPEC=importlib.util.spec_from_file_location('aigc_models',pathlib.Path(__file__).resolve().parents[1]/'scripts'/'models.py')
models=importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(models)
DATA=b'a small fictional model'*900
class Handler(BaseHTTPRequestHandler):
    ignore=False
    def do_GET(self):
        requested=self.headers.get('Range')
        if requested and not type(self).ignore:
            start=int(requested.split('=')[1].split('-')[0]); self.send_response(206)
            self.send_header('Content-Range',f'bytes {start}-{len(DATA)-1}/{len(DATA)}')
        else: start=0; self.send_response(200)
        self.end_headers();self.wfile.write(DATA[start:])
    def log_message(self,*args): pass

class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=HTTPServer(('127.0.0.1',0),Handler)
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()
    @classmethod
    def tearDownClass(cls): cls.server.shutdown();cls.server.server_close()
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.temp.name);self.old=models.ROOT;models.ROOT=self.root
        self.item={'url':f'http://127.0.0.1:{self.server.server_port}/file','dest':'models/test.bin','size':len(DATA),'sha256':hashlib.sha256(DATA).hexdigest()}
    def tearDown(self): models.ROOT=self.old;Handler.ignore=False;self.temp.cleanup()
    def partial(self):
        dest=self.root/self.item['dest'];dest.parent.mkdir(parents=True)
        dest.with_name(dest.name+'.aigc-download-part').write_bytes(DATA[:123])
        dest.with_name(dest.name+'.aigc-download.json').write_text(json.dumps({k:self.item[k] for k in ('url','size','sha256')}),encoding='utf-8')
        return dest
    def test_resume(self):
        dest=self.partial();models.download(self.item);self.assertEqual(dest.read_bytes(),DATA)
    def test_preflight_counts_only_remaining_bytes(self):
        self.partial()
        self.assertEqual(models.preflight('image',[self.item]),len(DATA)-123)
    def test_resume_when_interrupted_before_partial_creation(self):
        dest=self.root/self.item['dest'];dest.parent.mkdir(parents=True)
        meta=dest.with_name(dest.name+'.aigc-download.json')
        meta.write_text(json.dumps({k:self.item[k] for k in ('url','size','sha256')}),encoding='utf-8')
        self.assertEqual(models.preflight('image',[self.item]),len(DATA))
        models.download(self.item)
        self.assertEqual(dest.read_bytes(),DATA)
    def test_partial_without_metadata_is_preserved(self):
        dest=self.root/self.item['dest'];dest.parent.mkdir(parents=True)
        part=dest.with_name(dest.name+'.aigc-download-part');part.write_bytes(b'unknown')
        with self.assertRaisesRegex(RuntimeError,'续传标记'):
            models.preflight('image',[self.item])
        self.assertEqual(part.read_bytes(),b'unknown')
    def test_range_ignored_is_safe(self):
        dest=self.partial();Handler.ignore=True
        with self.assertRaisesRegex(RuntimeError,'续传'):models.download(self.item)
        self.assertFalse(dest.exists());self.assertEqual(dest.with_name(dest.name+'.aigc-download-part').read_bytes(),DATA[:123])
    def test_bad_hash_preserves_partial(self):
        self.item['sha256']='0'*64
        with self.assertRaisesRegex(RuntimeError,'SHA-256'):models.download(self.item)
        self.assertFalse((self.root/self.item['dest']).exists())
        self.assertTrue((self.root/(self.item['dest']+'.aigc-download-part')).exists())
    def test_conflict_does_not_overwrite(self):
        dest=self.root/self.item['dest'];dest.parent.mkdir(parents=True);dest.write_bytes(b'private')
        with self.assertRaisesRegex(RuntimeError,'不匹配'):models.download(self.item)
        self.assertEqual(dest.read_bytes(),b'private')
    def test_zip_path_traversal(self):
        z=self.root/'bad.zip'
        with zipfile.ZipFile(z,'w') as a:a.writestr('../outside.txt','bad')
        with self.assertRaisesRegex(RuntimeError,'不安全'):models.install_archive({'extract_to':'runtime'},z)
        self.assertFalse((self.root.parent/'outside.txt').exists())
    def test_merge_archives_and_reject_conflict(self):
        def zfile(name,files):
            z=self.root/name
            with zipfile.ZipFile(z,'w') as a:
                for key,value in files.items():a.writestr(key,value)
            return z
        first=zfile('a.zip',{'run.exe':'first'});second=zfile('b.zip',{'lib.dll':'second'})
        item={'extract_to':'runtime'};models.install_archive(item,first);models.install_archive(item,second)
        self.assertEqual((self.root/'runtime/run.exe').read_text(),'first');self.assertEqual((self.root/'runtime/lib.dll').read_text(),'second')
        collision=zfile('c.zip',{'run.exe':'other'})
        with self.assertRaisesRegex(RuntimeError,'冲突'):models.install_archive(item,collision)
        self.assertEqual((self.root/'runtime/run.exe').read_text(),'first')

    def test_source_install_and_existing_conflict(self):
        z=self.root/'source.zip'
        with zipfile.ZipFile(z,'w') as a:a.writestr('Project-123/lib/module.py','print(1)')
        item={'source_to':'runtime/Project','source_root':'Project-123'}
        models.install_source(item,z)
        output=self.root/'runtime/Project/lib/module.py'
        self.assertEqual(output.read_text(),'print(1)')
        models.install_source(item,z,True)
        output.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'不完整或内容不同'):
            models.install_source(item,z)
        self.assertEqual(output.read_text(),'changed')

if __name__=='__main__':unittest.main()

"""Desktop entry via its CLI; only Windows COM/browser boundaries are replaced."""
import json
import os
from pathlib import Path
import signal
import shutil
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'skills/wechat-group-daily/scripts/tools/desktop.py'


class DesktopTest(unittest.TestCase):
    def test_windows_launch_opens_local_url_through_system_browser(self):
        self.check_windows_url_open(fail_browser=False)

    def test_windows_browser_failure_is_reported_instead_of_claiming_opened(self):
        self.check_windows_url_open(fail_browser=True)

    def check_windows_url_open(self, *, fail_browser):
        with tempfile.TemporaryDirectory(prefix='magic-browser-') as folder:
            root = Path(folder)
            wrapper = root / 'windows_url_boundary.py'
            wrapper.write_text('''import json,os,pathlib,runpy,subprocess,sys,types,webbrowser
sys.path.insert(0,str(pathlib.Path(sys.argv[1]).resolve().parents[1]/'lib'))
from wechat_data import desktop
# Replace only Windows platform flags and ShellExecute, retaining the real server.
desktop.sys=types.SimpleNamespace(platform='win32',executable=sys.executable)
subprocess.CREATE_NO_WINDOW=0
sys.modules['ctypes']=types.SimpleNamespace(windll=types.SimpleNamespace(user32=types.SimpleNamespace(MessageBoxW=lambda *args: 0)))
webbrowser.open=lambda url: False
def startfile(url):
 pathlib.Path(os.environ['MAGIC_BROWSER_URL']).write_text(url,encoding='utf-8')
 if os.environ['MAGIC_BROWSER_FAIL']=='1': raise OSError('synthetic shell failure')
os.startfile=startfile
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
''', encoding='utf-8')
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            config = root / 'configuration.json'
            # Keep a known PID for cleanup even when the browser fails afterward.
            running = subprocess.run([sys.executable, '-B', str(TOOL), 'launch', '--no-open',
                                      '--config', str(config), '--port', str(port)],
                                     capture_output=True, text=True, timeout=15)
            self.assertEqual(running.returncode, 0, running.stdout + running.stderr)
            self.addCleanup(os.kill, json.loads(running.stdout)['started_pid'], signal.SIGTERM)
            env = dict(os.environ, MAGIC_BROWSER_URL=str(root / 'opened-url.txt'),
                       MAGIC_BROWSER_FAIL='1' if fail_browser else '0',
                       PROGRAMFILES=str(root / 'absent'), LOCALAPPDATA=str(root / 'absent'))
            result = subprocess.run([sys.executable, '-B', str(wrapper), str(TOOL), 'launch',
                                     '--config', str(config), '--port', str(port)],
                                    capture_output=True, text=True, env=env, timeout=15)
            self.assertEqual(result.returncode, 1 if fail_browser else 0, result.stdout + result.stderr)
            self.assertEqual((root / 'opened-url.txt').read_text(), f'http://127.0.0.1:{port}/')
            report = json.loads(result.stdout)
            if fail_browser:
                self.assertEqual(report['code'], 'READER_BROWSER_OPEN_FAILED')
            else:
                self.assertEqual(report['state'], 'opened')
                self.assertTrue(report['reused'])

    def test_start_then_reuse_actual_reader(self):
        with tempfile.TemporaryDirectory(prefix='magic-reader-') as folder:
            with socket.socket() as listener:
                listener.bind(('127.0.0.1', 0))
                port = listener.getsockname()[1]
            command = [sys.executable, '-B', str(TOOL), 'launch', '--no-open',
                       '--config', str(Path(folder) / 'config.json'), '--port', str(port)]
            first = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            created = json.loads(first.stdout)
            self.addCleanup(os.kill, created['started_pid'], signal.SIGTERM)
            self.assertFalse(created['reused'])
            second = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            reused = json.loads(second.stdout)
            self.assertTrue(reused['reused'])
            self.assertIsNone(reused['started_pid'])
            self.assertEqual(created['url'], reused['url'])
            self.assertFalse((Path(folder) / 'config.json').exists())

    def test_install_twice_updates_same_shortcut_and_unicode_arguments(self):
        with tempfile.TemporaryDirectory(prefix='magic-desktop-') as folder:
            root = Path(folder)
            wrapper = root / 'windows_boundary.py'
            wrapper.write_text('''import base64,json,os,pathlib,re,runpy,shutil,subprocess,sys
sys.path.insert(0,str(pathlib.Path(sys.argv[1]).resolve().parents[1]/'lib'))
import wechat_data.desktop
sys.platform='win32'
subprocess.CREATE_NO_WINDOW=0
def run(command,**kwargs):
 script=base64.b64decode(command[-1]).decode('utf-16le')
 encoded=re.search(r"FromBase64String\\('([^']+)'\\)",script)[1]
 payload=json.loads(base64.b64decode(encoded))
 assert "GetFolderPath('Desktop')" in script and 'CreateShortcut($path)' in script
 assert 'Copy-Item -LiteralPath $p.icon_source -Destination $iconPath -Force' in script
 assert "$link.IconLocation = $iconPath + ',0'" in script
 source=pathlib.Path(payload['icon_source'])
 storage=pathlib.Path(payload['storage'])
 storage.mkdir(parents=True,exist_ok=True)
 shutil.copyfile(source,storage/payload['icon_name'])
 desktop=pathlib.Path(os.environ['MAGIC_TEST_DESKTOP'])
 desktop.mkdir(exist_ok=True)
 path=desktop/(payload['name']+'.lnk')
 existed=path.exists()
 path.write_text(json.dumps(payload,ensure_ascii=False),encoding='utf-8')
 return subprocess.CompletedProcess(command,0,json.dumps({'state':'updated' if existed else 'created','shortcut':str(path)}),'')
subprocess.run=run
sys.argv=sys.argv[1:]
runpy.run_path(sys.argv[0],run_name='__main__')
''', encoding='utf-8')
            config = root / '含空格 data' / 'config.json'
            installed = root / '安装 副本'
            shutil.copytree(TOOL.parents[2], installed, ignore=shutil.ignore_patterns('__pycache__'))
            env = dict(os.environ, MAGIC_TEST_DESKTOP=str(root / 'Desktop'))
            command = [sys.executable, '-B', str(wrapper), str(installed / 'scripts/tools/desktop.py'),
                       'install', '--config', str(config)]
            first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            # Reinstallation also repairs a lost package-external icon.
            saved = json.loads(Path(json.loads(first.stdout)['shortcut']).read_text(encoding='utf-8'))
            icon = Path(saved['storage']) / saved['icon_name']
            icon.unlink()
            second = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            one, two = json.loads(first.stdout), json.loads(second.stdout)
            self.assertEqual(one['state'], 'created')
            self.assertEqual(two['state'], 'updated')
            self.assertEqual(one['shortcut'], two['shortcut'])
            self.assertEqual(len(list((root / 'Desktop').glob('*.lnk'))), 1)
            payload = json.loads(Path(two['shortcut']).read_text(encoding='utf-8'))
            self.assertIn(str(config), payload['arguments'])
            self.assertEqual(payload['name'], 'Magic 群日报')
            self.assertEqual(icon.read_bytes(), (installed / 'scripts/assets/magic-reader.ico').read_bytes())
            self.assertTrue(icon.name.startswith('magic-reader-'))

    def test_incomplete_install_reports_missing_icon_without_creating_shortcut(self):
        with tempfile.TemporaryDirectory(prefix='magic-missing-icon-') as folder:
            root = Path(folder)
            installed = root / 'installed'
            shutil.copytree(TOOL.parents[2], installed, ignore=shutil.ignore_patterns('__pycache__'))
            (installed / 'scripts/assets/magic-reader.ico').unlink()
            wrapper = root / 'windows.py'
            wrapper.write_text('import pathlib,runpy,sys\n'
                               'sys.path.insert(0,str(pathlib.Path(sys.argv[1]).resolve().parents[1]/"lib"))\n'
                               'import wechat_data.desktop\nsys.platform="win32"\n'
                               'sys.argv=sys.argv[1:]\nrunpy.run_path(sys.argv[0],run_name="__main__")\n',
                               encoding='utf-8')
            result = subprocess.run([sys.executable, '-B', str(wrapper),
                                     str(installed / 'scripts/tools/desktop.py'), 'install',
                                     '--no-open', '--config', str(root / 'external/config.json')],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(json.loads(result.stdout)['code'], 'SHORTCUT_ICON_MISSING')
            self.assertFalse((root / 'external').exists())

    @unittest.skipIf(sys.platform == 'win32', 'Non-Windows no-op')
    def test_non_windows_install_has_no_desktop_side_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'configuration.json'
            result = subprocess.run([sys.executable, '-B', str(TOOL), 'install', '--config', str(config)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['state'], 'not_applicable')
            self.assertEqual(list(Path(folder).iterdir()), [])

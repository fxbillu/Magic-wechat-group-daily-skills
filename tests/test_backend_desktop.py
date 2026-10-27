"""Desktop entry via its CLI; only Windows COM/browser boundaries are replaced."""
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / 'skills/wechat-group-daily/scripts/tools/desktop.py'


class DesktopTest(unittest.TestCase):
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
            wrapper.write_text('''import base64,json,os,pathlib,re,runpy,subprocess,sys
sys.path.insert(0,str(pathlib.Path(sys.argv[1]).resolve().parents[1]/'lib'))
import wechat_data.desktop
sys.platform='win32'
subprocess.CREATE_NO_WINDOW=0
def run(command,**kwargs):
 script=base64.b64decode(command[-1]).decode('utf-16le')
 encoded=re.search(r"FromBase64String\\('([^']+)'\\)",script)[1]
 payload=json.loads(base64.b64decode(encoded))
 assert "GetFolderPath('Desktop')" in script and 'CreateShortcut($path)' in script
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
            env = dict(os.environ, MAGIC_TEST_DESKTOP=str(root / 'Desktop'))
            command = [sys.executable, '-B', str(wrapper), str(TOOL), 'install', '--config', str(config)]
            first = subprocess.run(command, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
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

    @unittest.skipIf(sys.platform == 'win32', 'Non-Windows no-op')
    def test_non_windows_install_has_no_desktop_side_effect(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'configuration.json'
            result = subprocess.run([sys.executable, '-B', str(TOOL), 'install', '--config', str(config)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(json.loads(result.stdout)['state'], 'not_applicable')
            self.assertEqual(list(Path(folder).iterdir()), [])

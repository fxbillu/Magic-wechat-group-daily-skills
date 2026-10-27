"""One Windows shortcut, backed by the existing local reader."""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

BASE = Path(__file__).resolve().parents[2]
TITLE = 'Magic 群日报'

# Ship the reviewed multi-size icon; Windows installation needs no image library.
INSTALL_SCRIPT = r'''
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$p = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('__PAYLOAD__')) | ConvertFrom-Json
$desktop = [Environment]::GetFolderPath('Desktop')
if (-not $desktop) { throw 'DESKTOP_NOT_FOUND' }
[IO.Directory]::CreateDirectory($desktop) | Out-Null
[IO.Directory]::CreateDirectory($p.storage) | Out-Null
$iconPath = Join-Path $p.storage $p.icon_name
Copy-Item -LiteralPath $p.icon_source -Destination $iconPath -Force
$path = Join-Path $desktop ($p.name + '.lnk')
$existed = Test-Path -LiteralPath $path
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($path)
$link.TargetPath = $p.python
$link.Arguments = $p.arguments
$link.WorkingDirectory = $p.workdir
$link.IconLocation = $iconPath + ',0'
$link.Description = 'Magic WeChat daily reader'
$link.WindowStyle = 7
$link.Save()
@{state=$(if($existed){'updated'}else{'created'});shortcut=$path} | ConvertTo-Json -Compress
'''


def install_shortcut(config_path, port=8765):
    if sys.platform != 'win32':
        return {'state': 'not_applicable', 'platform': 'Windows'}
    config = Path(config_path).resolve()
    python = Path(sys.executable)
    windowless = python.with_name('pythonw.exe')
    python = windowless if windowless.is_file() else python
    tool = BASE / 'tools/desktop.py'
    icon = BASE / 'assets/magic-reader.ico'
    try:
        icon_digest = hashlib.sha256(icon.read_bytes()).hexdigest()[:12]
    except OSError:
        return {'state': 'failed', 'code': 'SHORTCUT_ICON_MISSING',
                'next_action': 'update_skill_then_recreate_desktop_shortcut_in_workbuddy'}
    payload = {'name': TITLE, 'python': str(python), 'workdir': str(BASE),
               'storage': str(config.parent / 'desktop'),
               'icon_source': str(icon), 'icon_name': f'magic-reader-{icon_digest}.ico',
               'arguments': subprocess.list2cmdline([str(tool), 'launch', '--config', str(config),
                                                     '--port', str(port)])}
    encoded = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode('utf-8')).decode('ascii')
    script = INSTALL_SCRIPT.replace('__PAYLOAD__', encoded)
    command = base64.b64encode(script.encode('utf-16le')).decode('ascii')
    try:
        result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive',
                                 '-EncodedCommand', command], capture_output=True,
                                encoding='utf-8', errors='replace', timeout=30,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if result.returncode:
            raise ValueError('SHORTCUT_INSTALL_FAILED')
        return json.loads(result.stdout.strip())
    except (OSError, ValueError, subprocess.SubprocessError):
        return {'state': 'failed', 'code': 'SHORTCUT_INSTALL_FAILED',
                'next_action': 'recreate_desktop_shortcut_in_workbuddy'}


def reader_available(url):
    try:
        with urllib.request.urlopen(url + 'api/status', timeout=0.5) as response:
            status = json.load(response)
        return isinstance(status, dict) and 'configuration' in status and 'reading' in status
    except (OSError, ValueError, urllib.error.URLError):
        return False


def open_reader(url):
    try:
        if sys.platform == 'win32':
            # Let the registered HTTP handler receive the URL directly. A
            # successful browser process spawn does not guarantee --app navigation.
            os.startfile(url)
        elif not webbrowser.open(url):
            raise OSError('No browser accepted the URL')
    except OSError:
        raise RuntimeError('READER_BROWSER_OPEN_FAILED') from None


def launch(config_path, port=8765, *, open_window=True):
    url = f'http://127.0.0.1:{port}/'
    reused = reader_available(url)
    pid = None
    if not reused:
        env = dict(os.environ, WECHAT_DAILY_CONFIG=str(Path(config_path).resolve()))
        options = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {'start_new_session': True}
        process = subprocess.Popen([sys.executable, '-B', str(BASE / 'tools/serve.py'), '--port', str(port)],
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, env=env, cwd=BASE, **options)
        pid = process.pid
        for _ in range(60):
            if reader_available(url):
                break
            if process.poll() is not None:
                raise RuntimeError('READER_START_FAILED')
            time.sleep(0.1)
        else:
            process.terminate()
            raise RuntimeError('READER_START_TIMEOUT')
    if open_window:
        open_reader(url)
    return {'state': 'opened' if open_window else 'running', 'url': url, 'reused': reused, 'started_pid': pid}


def main():
    from wechat_data import settings
    parser = argparse.ArgumentParser(description='Magic reader and one reusable Windows desktop shortcut')
    parser.add_argument('action', choices=('install', 'launch'))
    parser.add_argument('--config', default=settings.CONFIG_PATH)
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-open', action='store_true', help='Start/reuse reader without opening a window')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('port must be between 1 and 65535')
    try:
        result = install_shortcut(args.config, args.port) if args.action == 'install' else launch(args.config, args.port, open_window=not args.no_open)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        result = {'state': 'failed', 'code': str(error), 'next_action': 'open_reader_in_workbuddy'}
        message = '请在 WorkBuddy 中重新打开 Magic 群日报阅读台。'
        if str(error) == 'READER_BROWSER_OPEN_FAILED':
            result['url'] = f'http://127.0.0.1:{args.port}/'
            message = f'服务已就绪，但浏览器未能打开。请手动访问 {result["url"]}'
        if sys.platform == 'win32' and not args.no_open:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, TITLE, 0x10)
    print(json.dumps(result, ensure_ascii=False))
    return 1 if result['state'] == 'failed' else 0

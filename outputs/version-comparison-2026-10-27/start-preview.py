"""Serve the review wrapper and two isolated real readers on loopback only."""
import argparse
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8877)
    args = parser.parse_args()
    sample = json.loads((HERE / 'sample.json').read_text())
    processes, logs = [], []
    config = {'group': sample['group'], 'day': sample['day'], 'synthetic': True}
    try:
        for version in ('before', 'after'):
            root = HERE / 'runtime' / version
            log_path = root / 'reader.log'
            log = log_path.open('w')
            logs.append(log)
            env = dict(os.environ, WECHAT_DAILY_CONFIG=str(root / 'preview-config.json'),
                       TZ='Asia/Shanghai', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1')
            process = subprocess.Popen([sys.executable, '-B', str(root / 'skill/scripts/tools/serve.py'), '--port', '0'],
                                       env=env, stdout=log, stderr=subprocess.STDOUT)
            processes.append(process)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                match = re.search(r'http://127\.0\.0\.1:(\d+)/', log_path.read_text())
                if match:
                    config[version] = match[0].rstrip('/')
                    break
                if process.poll() is not None:
                    raise RuntimeError(log_path.read_text())
                time.sleep(.05)
            else:
                raise RuntimeError('Preview reader did not start')

        class Handler(SimpleHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/preview.json':
                    body = json.dumps(config).encode()
                    self.send_response(200)
                    self.send_header('Content-Type', 'application/json')
                    self.send_header('Content-Length', str(len(body)))
                    self.send_header('Cache-Control', 'no-store')
                    self.end_headers()
                    self.wfile.write(body)
                elif self.path.startswith('/runtime/'):
                    self.send_error(404)
                else:
                    super().do_GET()

            def log_message(self, *args):
                pass

        def stop(*args):
            raise KeyboardInterrupt()

        signal.signal(signal.SIGTERM, stop)
        server = ThreadingHTTPServer(('127.0.0.1', args.port), partial(Handler, directory=str(HERE)))
        print(f'COMPARISON_URL=http://127.0.0.1:{server.server_port}/', flush=True)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for process in processes:
            process.terminate()
        for process in processes:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
        for log in logs:
            log.close()


if __name__ == '__main__':
    main()

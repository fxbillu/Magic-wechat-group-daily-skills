"""Public browser checks against versioned contract fixtures, not backend acceptance.

Requires the installed ego-browser CLI. Each run owns a unique browser task space.
Run: python3 -B -m unittest discover -s tests/frontend -p 'test_*.py' -v
"""
import pathlib
import subprocess
import time
import unittest
import urllib.request
import uuid

HERE = pathlib.Path(__file__).resolve().parent

class ReaderBrowserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.space = 'wechat-frontend-' + uuid.uuid4().hex[:10]
        cls.servers = []
        try:
            for port, scenario in [(8873,'normal'), (8874,'unconfigured'), (8875,'empty'), (8876,'browse-error')]:
                process = subprocess.Popen(['python3','-B',str(HERE/'fixture_server.py'),'--port',str(port),'--scenario',scenario], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                cls.servers.append(process)
                for _ in range(60):
                    if process.poll() is not None:
                        raise RuntimeError(process.stderr.read().decode())
                    try:
                        urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=1).close()
                        break
                    except OSError:
                        time.sleep(.05)
                else:
                    raise RuntimeError(f'fixture peer on {port} did not start')
        except Exception:
            cls.stop_servers()
            raise

    @classmethod
    def stop_servers(cls):
        for process in cls.servers:
            process.terminate()
            process.wait(timeout=5)
            process.stderr.close()

    @classmethod
    def tearDownClass(cls):
        result=subprocess.run(['ego-browser','nodejs'], input=f'const task=await taskSpace("{cls.space}"); await task.finish({{keep:[]}});', text=True, capture_output=True,timeout=30)
        cls.stop_servers()
        if result.returncode:
            raise RuntimeError(result.stderr + result.stdout)

    def run_flow(self,name):
        script=(HERE/name).read_text().replace('taskSpace("wechat-t1-frontend")',f'taskSpace("{self.space}")')
        result=subprocess.run(['ego-browser','nodejs'],input=script,text=True,capture_output=True,timeout=120)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        print(result.stdout)

    def test_collection_report_contract_states(self):
        self.run_flow('check-states.mjs')

    def test_history_and_combined_filters(self):
        self.run_flow('check-history.mjs')

    def test_reading_routes_keyboard_empty_error_and_responsive(self):
        self.run_flow('check-interactions.mjs')

if __name__=='__main__':
    unittest.main()

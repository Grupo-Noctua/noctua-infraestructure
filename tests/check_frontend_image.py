"""Exercise the real frontend image/proxy against a disposable HTTP fixture.

Usage: python tests/check_frontend_image.py noctua-frontend:automation-check
Requires Docker. No AWS, credentials, host project mounts or real databases.
"""

import argparse
import base64
import json
import re
import subprocess
import time
import urllib.error
import urllib.request
import uuid


FIXTURE = '''
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({'total': 7, 'path': self.path}).encode())
HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
'''


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def verify(image):
    suffix = uuid.uuid4().hex[:10]
    network, backend, frontend = [f'noctua-check-{part}-{suffix}' for part in ['net', 'api', 'web']]
    created = []
    docker('network', 'create', network)
    try:
        # Keep the Docker CLI argument on one line (Windows native argument handling).
        fixture_code = "import base64;exec(base64.b64decode('" + base64.b64encode(FIXTURE.encode()).decode() + "'))"
        docker('run', '-d', '--name', backend, '--network', network, '--network-alias', 'api-fixture',
               'python:3.12-alpine', 'python', '-u', '-c', fixture_code)
        created.append(backend)
        deadline = time.monotonic() + 60
        while True:
            probe = subprocess.run(['docker', 'exec', backend, 'python', '-c',
                "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/ready',timeout=3).read()"],
                capture_output=True, timeout=10)
            if probe.returncode == 0:
                break
            if time.monotonic() > deadline:
                raise RuntimeError('HTTP fixture did not become ready')
            time.sleep(1)
        docker('run', '-d', '--name', frontend, '--network', network,
               '-p', '127.0.0.1::8080', '-e', 'BACKEND_UPSTREAM=http://api-fixture:8080', image)
        created.append(frontend)
        metadata = json.loads(docker('inspect', frontend))[0]
        port = metadata['NetworkSettings']['Ports']['8080/tcp'][0]['HostPort']
        base = 'http://127.0.0.1:' + port
        def get(path):
            with urllib.request.urlopen(base + path, timeout=15) as response:
                return response.read()
        deadline = time.monotonic() + 60
        while True:
            try:
                assert get('/healthz') == b'ok'
                break
            except (OSError, AssertionError):
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        html = get('/').decode()
        assert '<html' in html.lower()
        assert get('/projects/deep-link').decode() == html
        script = re.search(r'src="([^"]+\.js)"', html).group(1)
        javascript = get(script).decode()
        document = re.search(r'/assets/DocumentacaoBase-Projetos-[a-zA-Z0-9_-]+\.docx', javascript).group(0)
        assert get(document).startswith(b'PK')
        path = '/api/dashboard/projetos/total'
        assert json.loads(get(path)) == {'total': 7, 'path': path}
        docker('stop', backend)
        try:
            get(path)
        except urllib.error.HTTPError as error:
            assert error.code in {502, 504}
        else:
            raise AssertionError('Unavailable API must not fall back to the SPA HTML')
        print('PASS: HTML, SPA deep links, DOCX asset, /healthz, API prefix and upstream failure propagation')
    except Exception:
        for container in created:
            print(docker('inspect', '--format', '{{json .State}}', container))
            subprocess.run(['docker', 'logs', container], check=False)
        raise
    finally:
        for container in reversed(created):
            subprocess.run(['docker', 'rm', '-f', container], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'network', 'rm', network], check=True, stdout=subprocess.DEVNULL)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('image')
    verify(parser.parse_args().image)

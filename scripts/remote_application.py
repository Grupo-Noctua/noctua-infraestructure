"""Executed as root through SSM on Ubuntu EC2s. Uses only Python's standard library.

Secrets are fetched on the instance, never passed in SSM commands or printed.
"""

import argparse
import datetime
import fcntl
import gzip
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time


ROOT = Path('/opt/noctua')
MYSQL_NETWORK_CONFIG = Path('/etc/mysql/mysql.conf.d/noctua.cnf')
JDBC_ROUTES = ['projetos/total', 'projetos', 'ferramentas/mais-utilizada', 'projetos/tecnologia']
ATHENA_ROUTES = ['funcionarios/total', 'funcionarios/tecnologia', 'funcionarios/senioridade', 'funcionarios/area']


def run(*args, input=None, timeout=600, check=True):
    result = subprocess.run(args, input=input, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        # Do not propagate SQL/passwords, env contents or authentication output into SSM logs.
        raise RuntimeError(f'{Path(args[0]).name} failed (exit {result.returncode}); inspect the service on the instance')
    return result


def write_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as file:
        file.write(text)
    path.chmod(0o600)


def aws(config, *args):
    output = run('aws', *args, '--region', config['region'], '--output', 'json', '--no-cli-pager').stdout
    return json.loads(output) if output.strip() else {}


def secret(config, name):
    parameter = aws(config, 'ssm', 'get-parameter', '--name', name, '--with-decryption')['Parameter']
    if parameter['Type'] != 'SecureString':
        raise RuntimeError('Secrets must be stored as SSM SecureString')
    return parameter['Value']


def db_password(config):
    password = secret(config, config['db_password_parameter'])
    if not re.fullmatch(r'[A-Za-z0-9._~\-]{32,128}', password):
        raise ValueError('Database password must contain 32-128 characters: letters, digits, dot, underscore, tilde or dash')
    return password


def mysql(sql):
    return run('mysql', '--batch', '--skip-column-names', input=sql).stdout.strip()


def wait_bootstrap():
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        if (ROOT / 'bootstrap-ready').exists():
            return
        time.sleep(10)
    raise RuntimeError('EC2 bootstrap did not finish; inspect /var/log/cloud-init-output.log')


def volume_device(volume_id):
    serial = volume_id.replace('-', '')
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        for line in run('lsblk', '-dn', '-o', 'PATH,SERIAL').stdout.splitlines():
            fields = line.split()
            if len(fields) == 2 and fields[1].replace('-', '') == serial:
                return fields[0]
        # Xen instances expose the explicitly attached /dev/sdf as /dev/xvdf.
        if Path('/dev/xvdf').exists():
            return '/dev/xvdf'
        time.sleep(5)
    raise RuntimeError('Dedicated MySQL EBS volume did not appear')


def fstab_entry(line, target):
    path = Path('/etc/fstab')
    text = path.read_text()
    existing = [row for row in text.splitlines() if row.strip() and not row.startswith('#')
                and len(row.split()) > 1 and row.split()[1] == target]
    if existing and existing != [line]:
        raise RuntimeError(f'Unexpected existing mount configuration for {target}')
    if not existing:
        path.write_text(text.rstrip() + '\n' + line + '\n')


def ensure_mysql_networking():
    # This file contains no secrets and must be readable by the mysql service user.
    MYSQL_NETWORK_CONFIG.chmod(0o644)
    run('systemctl', 'enable', '--now', 'mysql')
    query = 'SELECT @@GLOBAL.bind_address, @@GLOBAL.require_secure_transport;'
    expected = '0.0.0.0\t1'
    # enable --now does not reload configuration for an already running server.
    if mysql(query) != expected:
        run('systemctl', 'restart', 'mysql')
        if mysql(query) != expected:
            raise RuntimeError('MySQL must listen on 0.0.0.0 with require_secure_transport enabled')


def prepare_database_storage(config):
    device = volume_device(config['database_volume_id'])
    filesystem = run('blkid', '-s', 'TYPE', '-o', 'value', device, check=False).stdout.strip()
    if not filesystem:
        signatures = json.loads(run('wipefs', '--json', device).stdout).get('signatures', [])
        if signatures or len(run('lsblk', '-nr', '-o', 'NAME', device).stdout.splitlines()) != 1:
            raise RuntimeError('Refusing to format a volume containing unknown signatures or partitions')
        run('mkfs.ext4', '-m', '0', device)
    elif filesystem != 'ext4':
        raise RuntimeError('Expected ext4 on the MySQL data volume')
    uuid = run('blkid', '-s', 'UUID', '-o', 'value', device).stdout.strip()
    mount = Path('/srv/noctua-mysql')
    mount.mkdir(exist_ok=True)
    fstab_entry(f'UUID={uuid} /srv/noctua-mysql ext4 defaults 0 2', str(mount))
    if run('mountpoint', '-q', str(mount), check=False).returncode:
        run('mount', str(mount))
    mounted_uuid = run('findmnt', '-n', '-o', 'UUID', '--target', str(mount)).stdout.strip()
    if mounted_uuid != uuid:
        raise RuntimeError('MySQL mount does not match the stack data volume')

    # Ordinary application redeploys should not stop an already prepared database.
    if (mount / '.mysql-seeded').exists() and not run('mountpoint', '-q', '/var/lib/mysql', check=False).returncode:
        if run('findmnt', '-n', '-o', 'UUID', '--target', '/var/lib/mysql').stdout.strip() != uuid:
            raise RuntimeError('MySQL datadir is mounted from another volume')
        if MYSQL_NETWORK_CONFIG.exists() and Path('/etc/systemd/system/mysql.service.d/noctua-storage.conf').exists():
            ensure_mysql_networking()
            return

    run('systemctl', 'stop', 'mysql')
    data = mount / 'data'
    marker = mount / '.mysql-seeded'
    if not marker.exists():
        if data.exists() and any(data.iterdir()):
            raise RuntimeError('Incomplete MySQL data copy; recover the volume before retrying')
        data.mkdir(exist_ok=True)
        run('rsync', '-a', '/var/lib/mysql/', str(data) + '/')
        marker.touch()
    fstab_entry('/srv/noctua-mysql/data /var/lib/mysql none bind 0 0', '/var/lib/mysql')
    if run('mountpoint', '-q', '/var/lib/mysql', check=False).returncode:
        run('mount', '/var/lib/mysql')
    if run('findmnt', '-n', '-o', 'UUID', '--target', '/var/lib/mysql').stdout.strip() != uuid:
        raise RuntimeError('MySQL datadir is not on the expected persistent volume')
    run('chown', '-R', 'mysql:mysql', '/var/lib/mysql')
    MYSQL_NETWORK_CONFIG.write_text(
        '[mysqld]\nbind-address=0.0.0.0\nrequire_secure_transport=ON\n')
    # Fail closed when the persistent mounts are unavailable after reboot.
    directory = Path('/etc/systemd/system/mysql.service.d')
    directory.mkdir(parents=True, exist_ok=True)
    (directory / 'noctua-storage.conf').write_text(
        '[Unit]\nRequiresMountsFor=/srv/noctua-mysql /var/lib/mysql\n')
    run('systemctl', 'daemon-reload')
    ensure_mysql_networking()


def bootstrap_database(config, schema):
    # Resolve before touching the database so expired/insufficient credentials fail early.
    password = db_password(config)
    backend_ip = str(ipaddress.IPv4Address(config['backend_private_ip']))
    installed = run('dpkg-query', '-W', '-f=${Status}', 'mysql-server', check=False)
    if installed.returncode or installed.stdout.strip() != 'install ok installed':
        run('apt-get', 'update')
        run('apt-get', 'install', '-y', 'mysql-server', timeout=900)
    prepare_database_storage(config)

    checksum = hashlib.sha256(schema.read_bytes()).hexdigest()
    exists = mysql("SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name='NOCTUA';") == '1'
    if exists:
        marker = mysql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='noctua_deployment' AND table_name='schema_versions';")
        if marker != '1':
            raise RuntimeError('NOCTUA already exists without a completed bootstrap record; inspect partial initialization')
        recorded = mysql("SELECT checksum FROM noctua_deployment.schema_versions WHERE version='baseline-v1';")
        if recorded != checksum:
            raise RuntimeError('Schema checksum changed; apply an explicit migration rather than re-running the baseline')
    else:
        mysql(schema.read_text(encoding='utf-8'))
        if mysql("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='NOCTUA';") != '11':
            raise RuntimeError('Baseline schema did not create the expected 11 tables')
        mysql('CREATE DATABASE IF NOT EXISTS noctua_deployment; '
              'CREATE TABLE IF NOT EXISTS noctua_deployment.schema_versions '
              '(version VARCHAR(100) PRIMARY KEY, checksum CHAR(64) NOT NULL, applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP); '
              f"INSERT INTO noctua_deployment.schema_versions(version,checksum) VALUES ('baseline-v1','{checksum}');")
    if mysql("SELECT COUNT(*) FROM information_schema.columns WHERE table_schema='NOCTUA' AND table_name='Documento_Projeto' AND column_name='orcamento';") != '1':
        raise RuntimeError('Required orcamento column is missing')
    mysql(f"CREATE USER IF NOT EXISTS 'noctua_api'@'{backend_ip}' IDENTIFIED BY '{password}'; "
          f"ALTER USER 'noctua_api'@'{backend_ip}' IDENTIFIED BY '{password}' REQUIRE SSL; "
          f"REVOKE ALL PRIVILEGES, GRANT OPTION FROM 'noctua_api'@'{backend_ip}'; "
          f"GRANT SELECT ON NOCTUA.* TO 'noctua_api'@'{backend_ip}';")
    # This user belongs to this deployment; remove stale source-IP accounts after replacement.
    for host in mysql("SELECT Host FROM mysql.user WHERE User='noctua_api';").splitlines():
        if host != backend_ip and re.fullmatch(r'[0-9.%]+|localhost', host):
            mysql(f"DROP USER 'noctua_api'@'{host}';")
    tools = ROOT / 'tools'
    tools.mkdir(exist_ok=True)
    shutil.copyfile(__file__, tools / 'remote_application.py')
    write_private(tools / 'backup.json', json.dumps({
        'region': config['region'], 'backup_bucket': config['backup_bucket']}))
    Path('/etc/systemd/system/noctua-backup.service').write_text(
        '[Unit]\nDescription=Noctua consistent MySQL backup to S3\nAfter=mysql.service\n'
        '[Service]\nType=oneshot\nUMask=0077\n'
        'ExecStart=/usr/bin/python3 /opt/noctua/tools/remote_application.py backup /opt/noctua/tools/backup.json\n')
    Path('/etc/systemd/system/noctua-backup.timer').write_text(
        '[Unit]\nDescription=Daily Noctua backup\n[Timer]\nOnCalendar=*-*-* 03:00:00 UTC\n'
        'Persistent=true\nRandomizedDelaySec=300\n[Install]\nWantedBy=timers.target\n')
    run('systemctl', 'daemon-reload')
    run('systemctl', 'enable', '--now', 'noctua-backup.timer')
    backup(config)
    print('Database baseline, read-only user and initial S3 backup validated')


def backup(config):
    with tempfile.TemporaryDirectory(prefix='noctua-backup-') as temp:
        dump = Path(temp) / 'database.sql'
        with dump.open('wb') as output:
            result = subprocess.run(['mysqldump', '--single-transaction', '--no-tablespaces',
                                     '--databases', 'NOCTUA', 'noctua_deployment'],
                                    stdout=output, stderr=subprocess.PIPE, timeout=600)
        if result.returncode:
            raise RuntimeError('MySQL backup failed')
        archive = Path(temp) / 'database.sql.gz'
        with dump.open('rb') as source, gzip.open(archive, 'wb') as target:
            shutil.copyfileobj(source, target)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        run('aws', 's3', 'cp', str(archive), f"s3://{config['backup_bucket']}/mysql/{stamp}.sql.gz",
            '--region', config['region'], '--sse', 'AES256', '--only-show-errors')
    print('Consistent backup uploaded to S3')


def pull_image(config, image):
    if not re.fullmatch(r'docker\.io/[a-z0-9_-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}', image):
        raise ValueError('Use a Docker Hub image pinned by sha256 digest')
    with tempfile.TemporaryDirectory(prefix='noctua-docker-') as directory:
        name = config.get('dockerhub_credentials_parameter')
        if name:
            credential = json.loads(secret(config, name))
            username, token = credential['username'], credential['token']
            if not re.fullmatch(r'[a-z0-9_-]+', username) or not token or '\n' in token:
                raise ValueError('Invalid Docker Hub read credential')
            run('docker', '--config', directory, 'login', '--username', username,
                '--password-stdin', input=token)
        run('docker', '--config', directory, 'pull', image, timeout=900)


def fetch(base, path, server_name=None):
    args = ['curl', '--fail', '--silent', '--show-error', '--max-time', '45', '--noproxy', '*']
    if server_name:
        args += ['--resolve', f'{server_name}:443:127.0.0.1']
    return run(*args, base + path, timeout=50).stdout


def smoke(config, component):
    if component == 'backend':
        base, server = 'http://127.0.0.1:8080', None
        if json.loads(fetch(base, '/actuator/health')).get('status') != 'UP':
            raise RuntimeError('JDBC health is not UP')
    else:
        server = config['server_name'] if config.get('tls_parameter') else None
        base = f'https://{server}' if server else 'http://127.0.0.1'
        if '<html' not in fetch(base, '/', server).lower():
            raise RuntimeError('Frontend did not return HTML')
    routes = JDBC_ROUTES + (ATHENA_ROUTES if config['athena_enabled'] else [])
    for route in routes:
        result = json.loads(fetch(base, '/api/dashboard/' + route, server))
        if route.endswith('/total'):
            if not isinstance(result, dict) or type(result.get('total')) is not int or result['total'] < 0:
                raise RuntimeError(f'Invalid count returned by {route}')
        elif not isinstance(result, list):
            raise RuntimeError(f'Expected a list from {route}')


def backend_options(config):
    ip = str(ipaddress.IPv4Address(config['database_private_ip']))
    values = {
        'DB_URL': f'jdbc:mysql://{ip}:3306/NOCTUA?sslMode=REQUIRED',
        'DB_USERNAME': 'noctua_api', 'DB_PASSWORD': db_password(config), 'DB_POOL_SIZE': '3',
        'AWS_REGION': config['region'], 'ATHENA_ENABLED': str(config['athena_enabled']).lower(),
        'ATHENA_DATABASE': config['athena_database'], 'ATHENA_WORKGROUP': config['athena_workgroup'],
        'ATHENA_OUTPUT_LOCATION': '', 'PORT': '8080',
        'JAVA_TOOL_OPTIONS': '-XX:MaxRAMPercentage=65.0 -XX:+ExitOnOutOfMemoryError',
    }
    for key, filename in [('TOTAL', 'total'), ('TECNOLOGIA', 'tecnologia'),
                          ('SENIORIDADE', 'senioridade'), ('AREA', 'area')]:
        values[f'ATHENA_SQL_{key}'] = f'file:/app/config/funcionarios-{filename}.sql'
    if any('\n' in value or '\r' in value for value in values.values()):
        raise ValueError('Environment values cannot contain newlines')
    env = ROOT / 'backend.env'
    write_private(env, ''.join(f'{key}={value}\n' for key, value in values.items()))
    memory = config['backend_memory']
    if not re.fullmatch(r'[1-9][0-9]*[mg]', memory):
        raise ValueError('Invalid backend memory limit')
    return ['--env-file', str(env), '--memory', memory, '-p', '8080:8080']


def nginx_configuration(upstream, server_name='_', tls=False):
    ipaddress.IPv4Address(upstream)
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', server_name):
        raise ValueError('Invalid frontend server_name')
    locations = f'''
    root /usr/share/nginx/html;
    index index.html;
    location = /healthz {{ default_type text/plain; return 200 'ok'; }}
    location /api/ {{
        proxy_pass http://{upstream}:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
    }}
    location / {{ try_files $uri $uri/ /index.html; }}
'''
    if not tls:
        return f'server {{ listen 8080; server_name {server_name};\n{locations}\n}}\n'
    return f'''server {{
    listen 8080;
    server_name {server_name};
    location = /healthz {{ default_type text/plain; return 200 'ok'; }}
    location / {{ return 301 https://{server_name}$request_uri; }}
}}
server {{
    listen 8443 ssl;
    server_name {server_name};
    ssl_certificate /etc/noctua-tls/certificate.pem;
    ssl_certificate_key /etc/noctua-tls/private-key.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
{locations}
}}
'''


def frontend_options(config):
    tls = bool(config.get('tls_parameter'))
    options = ['-p', '80:8080', '-e', 'NGINX_ENVSUBST_TEMPLATE_DIR=/nonexistent']
    if tls:
        if config['server_name'] == '_':
            raise ValueError('TLS requires a real server_name matching the certificate')
        certificate = json.loads(secret(config, config['tls_parameter']))
        directory = ROOT / 'tls'
        directory.mkdir(mode=0o700, exist_ok=True)
        write_private(directory / 'certificate.pem', certificate['certificate_pem'])
        write_private(directory / 'private-key.pem', certificate['private_key_pem'])
        options += ['-p', '443:8443', '-v', f'{directory}:/etc/noctua-tls:ro']
    path = ROOT / 'frontend.conf'
    write_private(path, nginx_configuration(config['backend_private_ip'], config['server_name'], tls))
    options += ['-v', f'{path}:/etc/nginx/conf.d/default.conf:ro']
    return options


def start_container(component, image, options):
    name = f'noctua-{component}'
    existing = run('docker', 'container', 'inspect', name, check=False)
    if existing.returncode == 0:
        run('docker', 'stop', '--time', '30', name)
        run('docker', 'rm', name)
    run('docker', 'run', '-d', '--name', name, '--restart', 'unless-stopped',
        '--log-driver', 'json-file', '--log-opt', 'max-size=10m', '--log-opt', 'max-file=3',
        *options, image)


def wait_smoke(config, component):
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        try:
            smoke(config, component)
            return
        except (RuntimeError, ValueError, subprocess.TimeoutExpired):
            time.sleep(5)
    raise RuntimeError(f'{component} did not pass all smoke tests within the startup window')


def deploy(config, component):
    image = config[f'{component}_image']
    pull_image(config, image)
    options = backend_options(config) if component == 'backend' else frontend_options(config)
    if component == 'frontend':
        run('docker', 'run', '--rm',
            '-e', 'NGINX_ENVSUBST_TEMPLATE_DIR=/nonexistent',
            '-v', f'{ROOT / "frontend.conf"}:/etc/nginx/conf.d/default.conf:ro',
            *(['-v', f'{ROOT / "tls"}:/etc/noctua-tls:ro'] if config.get('tls_parameter') else []),
            image, 'nginx', '-t')
    state_file = ROOT / f'{component}-release.json'
    previous = json.loads(state_file.read_text()) if state_file.exists() else None
    try:
        start_container(component, image, options)
        wait_smoke(config, component)
    except Exception:
        if previous:
            print(f'{component} validation failed; attempting previous image with current configuration', flush=True)
            start_container(component, previous['image'], options)
            wait_smoke(config, component)
            print(f'{component} previous image restored', flush=True)
        raise
    write_private(state_file, json.dumps({
        'image': image, 'previous_image': previous['image'] if previous else None,
        'deployed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'athena_validated': config['athena_enabled'],
        'database_private_ip': config['database_private_ip'],
        'backend_private_ip': config['backend_private_ip'],
    }, indent=2))
    print(f'{component} deployed and validated: {image}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['database', 'backend', 'frontend', 'backup', 'verify-backend', 'verify-frontend'])
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise RuntimeError('SSM must run this script as root')
    os.umask(0o077)
    os.environ['DEBIAN_FRONTEND'] = 'noninteractive'
    ROOT.mkdir(mode=0o700, exist_ok=True)
    config = json.loads(args.config.read_text())
    # Entire operation is serialized per instance, including backups.
    with (ROOT / 'deployment.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if args.action == 'backup':
            backup(config)
        else:
            wait_bootstrap()
            if args.action == 'database':
                bootstrap_database(config, Path(__file__).with_name('schema.sql'))
            elif args.action.startswith('verify-'):
                component = args.action.removeprefix('verify-')
                state = json.loads((ROOT / f'{component}-release.json').read_text())
                if state['image'] != config[f'{component}_image'] or any(
                    state[key] != config[key] for key in ['database_private_ip', 'backend_private_ip']
                ):
                    raise RuntimeError('Deployment record does not match the current stack and images')
                smoke(config, component)
                print(f'{component} current deployment revalidated')
            else:
                deploy(config, args.action)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Exception messages from this module are secret-free. Avoid full tracebacks/input dumps.
        print(f'FAILED: {type(error).__name__}: {error}', flush=True)
        raise SystemExit(1)

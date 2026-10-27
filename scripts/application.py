"""Local AWS Academy deployment driver (Python 3.10+ and AWS CLI v2).

Uses an AWS CLI profile with the lab's three temporary credential fields. Does not
copy these credentials into EC2s, images, SSM requests or generated n8n files.
"""

import argparse
import base64
import datetime
import hashlib
import io
import ipaddress
import json
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import tempfile
import time
import uuid


ROOT = Path(__file__).resolve().parents[1]
IMAGE_PATTERN = r'docker\.io/[a-z0-9_-]+/[a-z0-9_.-]+@sha256:[0-9a-f]{64}'
FINAL_STACK_FAILURES = {'ROLLBACK_COMPLETE', 'ROLLBACK_FAILED', 'UPDATE_ROLLBACK_COMPLETE',
                        'UPDATE_ROLLBACK_FAILED', 'CREATE_FAILED', 'UPDATE_FAILED', 'DELETE_FAILED'}


class AwsError(RuntimeError):
    pass


def aws(config, service, operation, payload=None):
    args = ['aws', service, operation, '--region', config['region'], '--output', 'json', '--no-cli-pager']
    if config.get('profile'):
        args += ['--profile', config['profile']]
    with tempfile.TemporaryDirectory(prefix='noctua-aws-') as directory:
        if payload is not None:
            path = Path(directory) / 'request.json'
            path.write_text(json.dumps(payload), encoding='utf-8')
            args += ['--cli-input-json', 'file://' + str(path)]
        result = subprocess.run(args, text=True, capture_output=True, timeout=180)
    if result.returncode:
        raise AwsError(result.stderr.strip())
    return json.loads(result.stdout) if result.stdout.strip() else {}


def validate_config(config, images=False):
    if config.get('region') != 'us-east-1':
        raise ValueError('The current base network uses us-east-1a; use us-east-1')
    if not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9-]{0,127}', config['stack_name']):
        raise ValueError('Invalid application stack name')
    network = ipaddress.ip_network(config['frontend_ingress_cidr'], strict=False)
    if network.version != 4:
        raise ValueError('Frontend ingress must be IPv4')
    if network.prefixlen == 0 and not config.get('tls_parameter'):
        raise ValueError('Use a restricted CIDR for HTTP validation, or configure TLS before public access')
    if type(config.get('athena_enabled')) is not bool:
        raise ValueError('athena_enabled must be a JSON boolean')
    for key in ['db_password_parameter', 'dockerhub_credentials_parameter', 'tls_parameter']:
        value = config.get(key, '')
        if (key == 'db_password_parameter' or value) and not re.fullmatch(r'/[a-zA-Z0-9_./-]+', value):
            raise ValueError(f'Invalid SSM parameter name: {key}')
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', config['server_name']):
        raise ValueError('Invalid server_name')
    if config.get('tls_parameter') and config['server_name'] == '_':
        raise ValueError('TLS requires server_name matching your certificate')
    if images:
        for key in ['backend_image', 'frontend_image']:
            if not re.fullmatch(IMAGE_PATTERN, config[key]):
                raise ValueError(f'{key} must be a docker.io image pinned by sha256 digest')


def stack(config, name):
    return aws(config, 'cloudformation', 'describe-stacks', {'StackName': name})['Stacks'][0]


def outputs(data):
    return {entry['OutputKey']: entry['OutputValue'] for entry in data.get('Outputs', [])}


def stack_exists(config, name):
    try:
        stack(config, name)
        return True
    except AwsError as error:
        if 'does not exist' in str(error):
            return False
        raise


def create_plan(config, name, template, parameters, description):
    aws(config, 'cloudformation', 'validate-template', {'TemplateBody': template})
    exists = stack_exists(config, name)
    if exists and stack(config, name)['StackStatus'] == 'REVIEW_IN_PROGRESS':
        exists = False
    change_name = 'noctua-' + uuid.uuid4().hex[:16]
    result = aws(config, 'cloudformation', 'create-change-set', {
        'StackName': name, 'ChangeSetName': change_name,
        'ChangeSetType': 'UPDATE' if exists else 'CREATE',
        'TemplateBody': template, 'Parameters': parameters,
        'Description': description,
    })
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        plan = aws(config, 'cloudformation', 'describe-change-set', {'ChangeSetName': result['Id']})
        if plan['Status'] == 'CREATE_COMPLETE':
            print('Change set:', result['Id'])
            for change in plan.get('Changes', []):
                resource = change['ResourceChange']
                print(resource['Action'], resource['LogicalResourceId'],
                      'Replacement=' + resource.get('Replacement', 'n/a'))
            print('Review the changes, then use apply --change-set with this ARN.')
            return plan
        if plan['Status'] == 'FAILED':
            reason = plan.get('StatusReason', '')
            if "didn't contain changes" in reason or 'No updates are to be performed' in reason:
                print('No infrastructure changes.')
                return None
            raise RuntimeError(reason)
        time.sleep(3)
    raise TimeoutError('CloudFormation change set did not finish')


def plan_application(config):
    exports = aws(config, 'cloudformation', 'list-exports')['Exports']
    available = {item['Name'] for item in exports}
    required = {'VPC-ID', 'PUBLIC-SUBNET', 'PRIVATE-BACKEND', 'PRIVATE-DB'}
    if not required.issubset(available):
        raise ValueError('Base network exports missing: ' + ', '.join(sorted(required - available)))
    mapping = {
        'InstanceProfileName': 'instance_profile', 'FrontendIngressCidr': 'frontend_ingress_cidr',
        'FrontendInstanceType': 'frontend_instance_type', 'BackendInstanceType': 'backend_instance_type',
        'DatabaseInstanceType': 'database_instance_type',
    }
    parameters = [{'ParameterKey': key, 'ParameterValue': config[value]} for key, value in mapping.items()]
    # Preserve parameters not managed by the config during updates (e.g. enlarged data volume).
    if stack_exists(config, config['stack_name']):
        current = stack(config, config['stack_name'])
        if current['StackStatus'] != 'REVIEW_IN_PROGRESS':
            for parameter in current.get('Parameters', []):
                if parameter['ParameterKey'] not in mapping:
                    parameters.append({'ParameterKey': parameter['ParameterKey'], 'UsePreviousValue': True})
    create_plan(config, config['stack_name'], (ROOT / 'files/application.yaml').read_text(), parameters,
                'Noctua application layer, Docker Hub and instance role credentials')


def apply_plan(config, change_set):
    plan = aws(config, 'cloudformation', 'describe-change-set', {'ChangeSetName': change_set})
    if plan['StackName'] not in {config['stack_name'], config['compute_stack_name']}:
        raise ValueError('Change set does not belong to either configured Noctua stack')
    aws(config, 'cloudformation', 'execute-change-set', {'ChangeSetName': change_set})
    deadline = time.monotonic() + 2400
    while time.monotonic() < deadline:
        data = stack(config, plan['StackName'])
        status = data['StackStatus']
        execution = aws(config, 'cloudformation', 'describe-change-set', {'ChangeSetName': change_set})
        if execution['ExecutionStatus'] == 'EXECUTE_COMPLETE' and status in {'CREATE_COMPLETE', 'UPDATE_COMPLETE'}:
            print('Stack ready:', plan['StackName'])
            return
        if status in FINAL_STACK_FAILURES:
            raise RuntimeError(f'Stack failed: {status}; inspect CloudFormation events')
        time.sleep(10)
    raise TimeoutError('Stack did not finish within 40 minutes; inspect AWS before retrying')


def wait_ssm(config, instance_ids):
    deadline = time.monotonic() + 1200
    while time.monotonic() < deadline:
        response = aws(config, 'ssm', 'describe-instance-information', {
            'Filters': [{'Key': 'InstanceIds', 'Values': instance_ids}]})
        online = {item['InstanceId'] for item in response['InstanceInformationList'] if item['PingStatus'] == 'Online'}
        if set(instance_ids).issubset(online):
            return
        time.sleep(10)
    raise TimeoutError('Instances are not Online in SSM; inspect role, agent and NAT connectivity')


def deployment_context(config):
    validate_config(config, images=True)
    data = stack(config, config['stack_name'])
    if data['StackStatus'] not in {'CREATE_COMPLETE', 'UPDATE_COMPLETE'}:
        raise RuntimeError('Application stack must be healthy before deployment')
    out = outputs(data)
    analytics = outputs(stack(config, config['compute_stack_name'])) if config['athena_enabled'] else {}
    keys = ['region', 'backend_image', 'frontend_image', 'db_password_parameter',
            'dockerhub_credentials_parameter', 'tls_parameter', 'server_name', 'athena_enabled', 'backend_memory']
    remote = {key: config[key] for key in keys}
    remote.update({
        'backend_private_ip': out['BackendPrivateIp'], 'database_private_ip': out['DatabasePrivateIp'],
        'database_volume_id': out['DatabaseVolumeId'], 'backup_bucket': out['DatabaseBackupBucket'],
        'athena_database': analytics.get('GlueDatabaseName', ''),
        'athena_workgroup': analytics.get('AthenaWorkGroupName', 'primary'),
    })
    if config['athena_enabled'] and not remote['athena_database']:
        raise ValueError('Glue database output is missing from compute stack')
    wait_ssm(config, [out[key] for key in ['DatabaseInstanceId', 'BackendInstanceId', 'FrontendInstanceId']])
    return remote, out


def package_sources(schema_path):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
        for path, name in [(ROOT / 'scripts/remote_application.py', 'remote_application.py'),
                           (schema_path, 'schema.sql')]:
            archive.add(path, arcname=name, recursive=False)
    return buffer.getvalue()


def remote_commands(action, config, package):
    if action not in {'database', 'backend', 'frontend', 'verify-backend', 'verify-frontend'}:
        raise ValueError('Invalid remote action')
    encoded = base64.b64encode(package).decode()
    context = base64.b64encode(json.dumps(config).encode()).decode()
    checksum = hashlib.sha256(package).hexdigest()
    return [
        'set -eu', 'umask 077', 'work=$(mktemp -d)', "trap 'rm -rf \"$work\"' EXIT",
        f"printf '%s' '{encoded}' | base64 -d > \"$work/package.tar.gz\"",
        f'echo "{checksum}  $work/package.tar.gz" | sha256sum -c -',
        'tar -xzf "$work/package.tar.gz" -C "$work"',
        f"printf '%s' '{context}' | base64 -d > \"$work/config.json\"",
        f'python3 "$work/remote_application.py" {action} "$work/config.json"',
    ]


def deployment_request(config, schema_path):
    remote, out = deployment_context(config)
    package = package_sources(schema_path)
    steps = []
    for component, key in [('database', 'DatabaseInstanceId'), ('backend', 'BackendInstanceId'), ('frontend', 'FrontendInstanceId')]:
        steps.append({'component': component, 'instanceId': out[key],
                      'commands': remote_commands(component, remote, package)})
    return {'region': config['region'], 'stackName': config['stack_name'],
            'generatedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'frontendIp': out['FrontendPublicIp'], 'athenaEnabled': config['athena_enabled'], 'steps': steps}


def send_and_wait(config, step):
    result = aws(config, 'ssm', 'send-command', {
        'DocumentName': 'AWS-RunShellScript', 'InstanceIds': [step['instanceId']],
        'Comment': 'Noctua deploy ' + step['component'], 'TimeoutSeconds': 600,
        'Parameters': {'commands': step['commands'], 'executionTimeout': ['3600']},
    })
    command_id = result['Command']['CommandId']
    print(step['component'], 'SSM command:', command_id, flush=True)
    deadline = time.monotonic() + 4200
    while time.monotonic() < deadline:
        try:
            status = aws(config, 'ssm', 'get-command-invocation', {
                'CommandId': command_id, 'InstanceId': step['instanceId']})
        except AwsError as error:
            if 'InvocationDoesNotExist' in str(error):
                time.sleep(5)
                continue
            raise
        if status['Status'] == 'Success' and status['ResponseCode'] == 0:
            print(status.get('StandardOutputContent', '').strip())
            return
        if status['Status'] not in {'Pending', 'InProgress', 'Delayed', 'Cancelling'}:
            raise RuntimeError(f"{step['component']} failed: {status['Status']}; inspect SSM command {command_id}")
        time.sleep(10)
    raise TimeoutError(f'SSM command {command_id} did not finish; inspect it before another deployment')


def retire_database_plan(config):
    # Require the new application infrastructure and a completed deployment before retiring the old EC2.
    remote, out = deployment_context(config)
    package = package_sources(ROOT.parent / 'noctua-backend/database/script-noctua.sql')
    for component, key in [('backend', 'BackendInstanceId'), ('frontend', 'FrontendInstanceId')]:
        send_and_wait(config, {'component': 'verify-' + component, 'instanceId': out[key],
                              'commands': remote_commands('verify-' + component, remote, package)})
    print('New application validated before planning legacy removal. Frontend:', out['FrontendPublicIp'])
    name = config['compute_stack_name']
    current = stack(config, name)
    response = aws(config, 'cloudformation', 'get-template', {'StackName': name, 'TemplateStage': 'Original'})
    template = response['TemplateBody']
    if isinstance(template, str):
        # Convert short CloudFormation YAML tags without losing intrinsic functions.
        from cloudformation_yaml import load_template
        template = load_template(template)
    resource = template.get('Resources', {}).get('EC2Database')
    if not resource:
        print('Old EC2Database is already absent from the deployed compute template.')
        return
    if resource.get('Type') != 'AWS::EC2::Instance':
        raise ValueError('EC2Database is not the expected EC2 instance')
    del template['Resources']['EC2Database']
    plan = create_plan(config, name, json.dumps(template),
                       [{'ParameterKey': item['ParameterKey'], 'UsePreviousValue': True}
                        for item in current.get('Parameters', [])],
                       'Retire unused legacy MySQL EC2 after application migration')
    if plan:
        changes = [change['ResourceChange'] for change in plan.get('Changes', [])]
        if len(changes) != 1 or changes[0]['Action'] != 'Remove' or changes[0]['LogicalResourceId'] != 'EC2Database':
            aws(config, 'cloudformation', 'delete-change-set', {'ChangeSetName': plan['ChangeSetId']})
            raise RuntimeError('Unexpected changes in retirement plan; change set deleted')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, default=ROOT / 'files/application.local.json')
    sub = parser.add_subparsers(dest='action', required=True)
    for name in ['plan', 'init-db-secret', 'retire-database-plan']:
        sub.add_parser(name)
    apply = sub.add_parser('apply')
    apply.add_argument('--change-set', required=True)
    for name in ['prepare', 'deploy']:
        command = sub.add_parser(name)
        command.add_argument('--schema', type=Path, default=ROOT.parent / 'noctua-backend/database/script-noctua.sql')
    args = parser.parse_args()
    config = json.loads(args.config.read_text(encoding='utf-8-sig'))
    validate_config(config)
    identity = aws(config, 'sts', 'get-caller-identity')
    print('AWS account:', identity['Account'], '| region:', config['region'])
    if args.action == 'plan':
        plan_application(config)
    elif args.action == 'apply':
        apply_plan(config, args.change_set)
    elif args.action == 'init-db-secret':
        # Overwrite is deliberately false: re-running must not rotate an in-use password.
        aws(config, 'ssm', 'put-parameter', {
            'Name': config['db_password_parameter'], 'Type': 'SecureString',
            'Value': secrets.token_hex(32), 'Overwrite': False,
        })
        print('Database password created as SecureString. Its value was not printed.')
    elif args.action == 'retire-database-plan':
        retire_database_plan(config)
    else:
        request = deployment_request(config, args.schema)
        if args.action == 'prepare':
            path = ROOT / 'files/application-deployment.json'
            path.write_text(json.dumps(request, indent=2), encoding='utf-8')
            print('Fresh n8n deployment request:', path)
        else:
            for step in request['steps']:
                send_and_wait(config, step)
            print('Application deployed. Frontend IP:', request['frontendIp'])
            print('Athena validated:', request['athenaEnabled'])


if __name__ == '__main__':
    try:
        main()
    except (AwsError, ValueError, RuntimeError, TimeoutError) as error:
        raise SystemExit(str(error))

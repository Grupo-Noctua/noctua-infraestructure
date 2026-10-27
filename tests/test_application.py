import base64
import copy
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shlex
import subprocess
import sys
import tarfile
import tempfile
import unittest
from urllib.parse import parse_qs
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import application
from cloudformation_yaml import load_template

# Remote entrypoint is Linux-only; mock just the advisory lock module on Windows.
if sys.platform == 'win32':
    sys.modules.setdefault('fcntl', Mock())
import remote_application as remote


def configuration():
    data = json.loads((ROOT / 'files/application.example.json').read_text())
    data['frontend_ingress_cidr'] = '203.0.113.10/32'
    data['backend_image'] = 'docker.io/noctua/backend@sha256:' + 'a' * 64
    data['frontend_image'] = 'docker.io/noctua/frontend@sha256:' + 'b' * 64
    return data


class ApplicationTests(unittest.TestCase):
    def test_mysql_restarts_when_runtime_network_configuration_is_stale(self):
        with patch.object(remote, 'mysql', side_effect=['127.0.0.1\t0', '0.0.0.0\t1']), \
                patch.object(remote, 'MYSQL_NETWORK_CONFIG') as network_config, \
                patch.object(remote, 'run') as run:
            remote.ensure_mysql_networking()
        network_config.chmod.assert_called_once_with(0o644)
        run.assert_any_call('systemctl', 'restart', 'mysql')

    def test_mysql_healthy_redeploy_does_not_restart_database(self):
        with patch.object(remote, 'mysql', return_value='0.0.0.0\t1'), \
                patch.object(remote, 'MYSQL_NETWORK_CONFIG'), \
                patch.object(remote, 'run') as run:
            remote.ensure_mysql_networking()
        run.assert_called_once_with('systemctl', 'enable', '--now', 'mysql')

    def test_mysql_rejects_runtime_configuration_still_wrong_after_restart(self):
        for state in ['127.0.0.1\t1', '0.0.0.0\t0']:
            with self.subTest(state=state), \
                    patch.object(remote, 'mysql', return_value=state), \
                    patch.object(remote, 'MYSQL_NETWORK_CONFIG'), \
                    patch.object(remote, 'run'):
                with self.assertRaisesRegex(RuntimeError, 'require_secure_transport'):
                    remote.ensure_mysql_networking()

    def test_example_cannot_deploy_before_configuration(self):
        with self.assertRaises(ValueError):
            application.validate_config(json.loads((ROOT / 'files/application.example.json').read_text()))

    def test_only_digest_images_are_deployed(self):
        config = configuration()
        application.validate_config(config, images=True)
        config['backend_image'] = 'docker.io/noctua/backend:latest'
        with self.assertRaisesRegex(ValueError, 'sha256'):
            application.validate_config(config, images=True)

    def test_role_secrets_not_embedded_in_remote_package(self):
        config = configuration()
        package = application.package_sources(ROOT.parent / 'noctua-backend/database/script-noctua.sql')
        with tarfile.open(fileobj=io.BytesIO(package), mode='r:gz') as archive:
            self.assertEqual(set(archive.getnames()), {'schema.sql', 'remote_application.py'})
        commands = application.remote_commands('backend', config, package)
        self.assertIn('sha256sum -c', '\n'.join(commands))
        encoded = commands[4].split("'")[3]
        self.assertEqual(base64.b64decode(encoded), package)
        self.assertLess(len(json.dumps({'commands': commands}).encode()), 64000)
        self.assertNotIn('AWS_ACCESS_KEY_ID=', '\n'.join(commands))
        with self.assertRaises(ValueError):
            application.remote_commands('backend; rm -rf /', config, package)

    def test_network_and_storage_are_isolated_and_retained(self):
        template = load_template((ROOT / 'files/application.yaml').read_text())
        resources = template['Resources']
        self.assertEqual(resources['EC2DatabaseApp']['Properties']['SubnetId'], {'Fn::ImportValue': 'PRIVATE-DB'})
        self.assertEqual(resources['DatabaseDataVolume']['DeletionPolicy'], 'Retain')
        self.assertEqual(resources['DatabaseDataVolume']['UpdateReplacePolicy'], 'Retain')
        db_rule = resources['DatabaseSecurityGroup']['Properties']['SecurityGroupIngress'][0]
        self.assertEqual(db_rule['SourceSecurityGroupId'], {'Ref': 'BackendSecurityGroup'})
        self.assertEqual(db_rule['FromPort'], 3306)
        self.assertNotIn('EC2Database', load_template((ROOT / 'files/compute.yaml').read_text())['Resources'])

    def test_replanning_unexecuted_creation_does_not_use_update_parameters(self):
        current = {'StackStatus': 'REVIEW_IN_PROGRESS',
                   'Parameters': [{'ParameterKey': 'UbuntuAmi', 'ParameterValue': 'previous'}]}
        exports = {'Exports': [{'Name': name} for name in ['VPC-ID', 'PUBLIC-SUBNET', 'PRIVATE-BACKEND', 'PRIVATE-DB']]}
        with patch.object(application, 'stack_exists', return_value=True), \
                patch.object(application, 'stack', return_value=current), \
                patch.object(application, 'aws', return_value=exports), \
                patch.object(application, 'create_plan') as plan:
            application.plan_application(configuration())
        self.assertFalse(any('UsePreviousValue' in value for value in plan.call_args.args[3]))
        with patch.object(application, 'stack_exists', return_value=True), \
                patch.object(application, 'stack', return_value=current), \
                patch.object(application, 'aws', side_effect=[{}, {'Id': 'plan'}, {'Status': 'CREATE_COMPLETE'}]) as aws:
            application.create_plan(configuration(), 'noctua-application', '{}', [], 'test')
        self.assertEqual(aws.call_args_list[1].args[3]['ChangeSetType'], 'CREATE')

    def test_retirement_uses_deployed_template_and_removes_only_legacy_database(self):
        config = configuration()
        live = {'Resources': {'EC2Database': {'Type': 'AWS::EC2::Instance'},
                              'UnrelatedUserResource': {'Type': 'AWS::S3::Bucket'}}}
        plan = {'Changes': [{'ResourceChange': {'Action': 'Remove', 'LogicalResourceId': 'EC2Database'}}]}
        with patch.object(application, 'deployment_context', return_value=(configuration(), {
                'FrontendPublicIp': 'test', 'BackendInstanceId': 'i-test1', 'FrontendInstanceId': 'i-test2'})), \
                patch.object(application, 'send_and_wait'), \
                patch.object(application, 'stack', return_value={'Parameters': []}), \
                patch.object(application, 'aws', return_value={'TemplateBody': copy.deepcopy(live)}), \
                patch.object(application, 'create_plan', return_value=plan) as create:
            application.retire_database_plan(config)
        sent = json.loads(create.call_args.args[2])
        self.assertEqual(sent['Resources'], {'UnrelatedUserResource': live['Resources']['UnrelatedUserResource']})

    def test_nginx_preserves_api_prefix_and_tls_redirect(self):
        config = remote.nginx_configuration('10.0.2.10', 'app.example.com', True)
        self.assertIn('proxy_pass http://10.0.2.10:8080;', config)
        self.assertNotIn('proxy_pass http://10.0.2.10:8080/;', config)
        self.assertIn('https://app.example.com$request_uri', config)
        self.assertIn('listen 8443 ssl;', config)
        with self.assertRaises(ValueError):
            remote.nginx_configuration('10.0.2.10', 'example.com; return 200;')

    def test_failed_deploy_restores_previous_image_and_still_fails(self):
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = {'image': 'docker.io/noctua/backend@sha256:' + 'c' * 64}
            (root / 'backend-release.json').write_text(json.dumps(old))
            with patch.object(remote, 'ROOT', root), \
                    patch.object(remote, 'pull_image'), patch.object(remote, 'backend_options', return_value=['--env-file', '/current.env']), \
                    patch.object(remote, 'start_container') as start, \
                    patch.object(remote, 'wait_smoke', side_effect=[RuntimeError('bad image'), None]):
                with self.assertRaisesRegex(RuntimeError, 'bad image'):
                    remote.deploy(configuration(), 'backend')
            self.assertEqual(start.call_args_list[1].args, ('backend', old['image'], ['--env-file', '/current.env']))
            self.assertEqual(json.loads((root / 'backend-release.json').read_text()), old)

    def test_athena_failure_prevents_smoke_success(self):
        responses = [json.dumps({'status': 'UP'}), json.dumps({'total': 1}), '[]', '[]', '[]', RuntimeError('Athena denied')]
        with patch.object(remote, 'fetch', side_effect=responses):
            with self.assertRaisesRegex(RuntimeError, 'Athena denied'):
                remote.smoke(configuration(), 'backend')


class WorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = json.loads((ROOT / 'application-n8n-noctua.json').read_text())
        cls.nodes = {node['name']: node for node in cls.workflow['nodes']}

    def test_workflow_uses_cloudformation_and_ssm_with_central_credentials(self):
        http = [node for node in self.nodes.values() if node['type'] == 'n8n-nodes-base.httpRequest']
        self.assertEqual(len(http), 4)
        self.assertFalse(self.workflow['active'])
        for node in http:
            self.assertEqual(node['parameters']['nodeCredentialType'], 'aws')
            self.assertNotIn('credentials', node)
        for name, outputs in self.workflow['connections'].items():
            self.assertIn(name, self.nodes)
            for branch in outputs['main']:
                for connection in branch:
                    self.assertIn(connection['node'], self.nodes)

    def run_code(self, name, body=None, context=None, files=None):
        program = """
const fs = require('fs');
const x = JSON.parse(fs.readFileSync(0, 'utf8'));
const AsyncFunction = Object.getPrototypeOf(async function() {}).constructor;
const entries = Object.entries(x.files || {});
const items = entries.map(([fileName]) => ({json: {}, binary: {data: {fileName}}}));
const helpers = {getBinaryDataBuffer: async (index) => Buffer.from(entries[index][1], 'utf8')};
(async () => {
  try {
    const result = await new AsyncFunction('$json', '$', '$input', 'require', x.code).call(
      {helpers}, x.body, () => ({item: {json: x.context}}),
      {all: () => items, first: () => items[0]}, require);
    console.log(JSON.stringify(result));
  } catch (e) { console.log(JSON.stringify({error: e.message})); }
})();
"""
        payload = {'code': self.nodes[name]['parameters']['jsCode'], 'body': body,
                   'context': context, 'files': files}
        output = subprocess.check_output(['node', '-e', program], input=json.dumps(payload), text=True)
        return json.loads(output)

    def input_files(self):
        return {'application.local.json': json.dumps(configuration()),
                'application.yaml': (ROOT / 'files/application.yaml').read_text(encoding='utf-8'),
                'remote_application.py': (ROOT / 'scripts/remote_application.py').read_text(encoding='utf-8'),
                'script-noctua.sql': 'CREATE DATABASE NOCTUA;'}

    def initial(self):
        result = self.run_code('Load deployment inputs', files=self.input_files())
        self.assertNotIn('error', result, result)
        return result[0]['json']

    def app_stack(self, status='CREATE_COMPLETE'):
        out = {'DatabaseInstanceId': 'i-' + 'a' * 17, 'BackendInstanceId': 'i-' + 'b' * 17,
               'FrontendInstanceId': 'i-' + 'c' * 17, 'FrontendPublicIp': '203.0.113.10',
               'BackendPrivateIp': '10.0.2.10', 'DatabasePrivateIp': '10.0.3.10',
               'DatabaseVolumeId': 'vol-' + 'd' * 17, 'DatabaseBackupBucket': 'noctua-backups-test'}
        return {'StackName': 'noctua-application', 'StackId': 'test-stack-id', 'StackStatus': status,
                'Outputs': {'member': [{'OutputKey': key, 'OutputValue': value} for key, value in out.items()]},
                'Parameters': {'member': [{'ParameterKey': 'DatabaseVolumeSize', 'ParameterValue': '50'},
                                           {'ParameterKey': 'UbuntuAmi', 'ParameterValue': 'previous-ami-path'}]}}

    def ready_state(self):
        state = self.initial()
        state.update(phase='ready', ready=True, infrastructureAction='CREATE', stackId='test-stack-id',
                     changeSetId='test-change-set', analytics={'GlueDatabaseName': 'noctua_analytics',
                                                            'AthenaWorkGroupName': 'noctua-athena-wg'},
                     applicationOutputs={item['OutputKey']: item['OutputValue']
                                         for item in self.app_stack()['Outputs']['member']})
        return state

    def infra(self, state, body, status=200):
        request = self.run_code('Prepare infrastructure request', state)
        self.assertNotIn('error', request, request)
        return self.run_code('Evaluate infrastructure response', {'body': body, 'statusCode': status},
                             request[0]['json'])

    def evaluate(self, body, deadline=9999999999999, http_status=None):
        context = {'deadline': deadline, 'stepStartedAt': 0, 'commandId': 'test-command',
                   'step': {'component': 'backend', 'instanceId': 'i-' + 'b' * 17}}
        if http_status is None:
            http_status = 400 if '__type' in body else 200
        return self.run_code('Evaluate command result',
                             {'body': body, 'statusCode': http_status}, context)

    def test_inputs_package_current_sources_and_accept_utf8_bom(self):
        for prefix in ['', '\ufeff']:
            files = self.input_files()
            files['application.local.json'] = prefix + files['application.local.json']
            result = self.run_code('Load deployment inputs', files=files)
            self.assertNotIn('error', result, result)
            state = result[0]['json']
            bundle = base64.b64decode(state['packageBase64'])
            self.assertEqual(hashlib.sha256(bundle).hexdigest(), state['packageSha256'])
            sources = json.loads(gzip.decompress(bundle))
            self.assertEqual(sources['remote_application.py'], files['remote_application.py'])
            self.assertEqual(sources['schema.sql'], files['script-noctua.sql'])
            self.assertNotIn('profile', state['config'])

    def test_inputs_reject_missing_files_bad_configuration_and_base_stack_names(self):
        for name in self.input_files():
            files = self.input_files()
            del files[name]
            self.assertIn('error', self.run_code('Load deployment inputs', files=files))
        for document in ['{broken', 'null', '[]']:
            files = self.input_files()
            files['application.local.json'] = document
            self.assertIn('error', self.run_code('Load deployment inputs', files=files))
        for field, value in [('region', 'us-west-2'), ('stack_name', ''),
                             ('stack_name', 'compute-stack'), ('stack_name', 'network-stack'),
                             ('stack_name', 'storage-stack'), ('athena_enabled', 'false'),
                             ('frontend_ingress_cidr', '999.1.2.3/32'),
                             ('backend_image', 'docker.io/noctua/backend:latest')]:
            with self.subTest(field=field, value=value):
                config = configuration()
                config[field] = value
                files = self.input_files()
                files['application.local.json'] = json.dumps(config)
                self.assertIn('error', self.run_code('Load deployment inputs', files=files))

    def test_network_export_pagination_and_missing_dependencies(self):
        state = self.initial()
        exports = [{'Name': name, 'Value': name + '-value',
                    'ExportingStackId': 'arn:aws:cloudformation:us-east-1:123:stack/network-stack/id'}
                   for name in ['VPC-ID', 'PUBLIC-SUBNET', 'PRIVATE-BACKEND', 'PRIVATE-DB']]
        state = self.infra(state, {'ListExportsResult': {'Exports': {'member': exports[0]}, 'NextToken': 'page2'}})[0]['json']
        self.assertEqual(state['phase'], 'exports')
        self.assertIn('NextToken=page2', self.run_code('Prepare infrastructure request', state)[0]['json']['api']['body'])
        result = self.infra(state, {'ListExportsResult': {'Exports': {'member': exports[1:]}}})[0]['json']
        self.assertEqual(result['phase'], 'secrets')
        self.assertEqual(len(result['exports']), 4)
        self.assertIn('exports missing', self.infra(self.initial(), {'ListExportsResult': {}})['error'])

    def test_analytics_and_secret_checks_use_existing_services(self):
        state = self.initial()
        state['phase'] = 'secrets'
        self.assertIn('Create the SecureString', self.infra(state, {'Parameters': []})['error'])
        name = state['config']['db_password_parameter']
        self.assertIn('SecureString', self.infra(state, {'Parameters': [{'Name': name, 'Type': 'String'}]})['error'])
        state = self.infra(state, {'Parameters': [{'Name': name, 'Type': 'SecureString'}]})[0]['json']
        self.assertEqual(state['phase'], 'analytics')
        request = self.run_code('Prepare infrastructure request', state)[0]['json']['api']
        self.assertEqual(parse_qs(request['body'])['StackName'], ['compute-stack'])
        self.assertIn('must provide', self.infra(state, {'Stacks': {'member': {'StackStatus': 'CREATE_COMPLETE'}}})['error'])
        state = self.infra(state, {'Stacks': {'member': {'StackStatus': 'CREATE_COMPLETE', 'Outputs': {'member': [
            {'OutputKey': 'GlueDatabaseName', 'OutputValue': 'existing-database'},
            {'OutputKey': 'AthenaWorkGroupName', 'OutputValue': 'existing-workgroup'}]}}}})[0]['json']
        self.assertEqual(state['analytics']['GlueDatabaseName'], 'existing-database')
        self.assertEqual(state['phase'], 'validate')

    def test_create_and_update_preserve_parameters_and_only_target_application_stack(self):
        for exists in [False, True]:
            state = self.initial()
            state['phase'] = 'inspect'
            if exists:
                result = self.infra(state, {'Stacks': {'member': self.app_stack()}})
            else:
                result = self.infra(state, {'Error': {'Code': 'ValidationError',
                    'Message': 'Stack with id noctua-application does not exist'}}, 400)
            state = result[0]['json']
            self.assertEqual(state['phase'], 'plan')
            request = self.run_code('Prepare infrastructure request', state)[0]['json']['api']
            query = parse_qs(request['body'])
            self.assertEqual(query['StackName'], ['noctua-application'])
            self.assertEqual(query['ChangeSetType'], ['UPDATE' if exists else 'CREATE'])
            self.assertEqual(query['ClientToken'], [state['runToken']])
            self.assertEqual(query['TemplateBody'], [self.input_files()['application.yaml']])
            if exists:
                self.assertEqual(query['Parameters.member.6.ParameterKey'], ['DatabaseVolumeSize'])
                self.assertEqual(query['Parameters.member.6.UsePreviousValue'], ['true'])
                self.assertEqual(query['Parameters.member.7.ParameterKey'], ['UbuntuAmi'])
            else:
                self.assertNotIn('Parameters.member.6.ParameterKey', query)
            state = self.infra(state, {'Id': 'changeset-id', 'StackId': 'stack-id'})[0]['json']
            self.assertEqual(state['phase'], 'changeset')
            self.assertEqual(state['waitSeconds'], 10)

    def test_secret_metadata_follows_empty_pages_and_clears_token(self):
        state = self.initial()
        state.update(phase='secrets', parameterNames=['/noctua/password', '/noctua/dockerhub'])
        state = self.infra(state, {'Parameters': [], 'NextToken': 'page-two'})[0]['json']
        self.assertEqual(state['phase'], 'secrets')
        request = self.run_code('Prepare infrastructure request', state)[0]['json']['api']
        self.assertEqual(json.loads(request['body'])['NextToken'], 'page-two')
        state = self.infra(state, {'Parameters': [{'Name': '/noctua/password', 'Type': 'SecureString'}]})[0]['json']
        self.assertEqual(state['parameterIndex'], 1)
        request = self.run_code('Prepare infrastructure request', state)[0]['json']['api']
        self.assertNotIn('NextToken', json.loads(request['body']))

    def test_no_changes_cleans_only_changeset_then_reuses_instances(self):
        state = self.initial()
        state.update(phase='changeset', stackExists=True, changeSetId='change-id')
        state = self.infra(state, {'Status': 'FAILED', 'StatusReason': "The submitted information didn't contain changes."})[0]['json']
        self.assertEqual(state['infrastructureAction'], 'UNCHANGED')
        request = self.run_code('Prepare infrastructure request', state)[0]['json']['api']
        self.assertEqual(parse_qs(request['body'])['Action'], ['DeleteChangeSet'])
        state = self.infra(state, {})[0]['json']
        self.assertEqual(state['phase'], 'collect')
        state = self.infra(state, {'Stacks': {'member': self.app_stack()}})[0]['json']
        self.assertEqual(state['phase'], 'online')

    def test_changeset_and_stack_polling_do_not_accept_old_complete_status(self):
        state = self.initial()
        state.update(phase='changeset', changeSetId='change-id')
        state = self.infra(state, {'Status': 'CREATE_IN_PROGRESS'})[0]['json']
        self.assertEqual(state['phase'], 'changeset')
        state = self.infra(state, {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE'})[0]['json']
        self.assertEqual(state['phase'], 'execute')
        state = self.infra(state, {})[0]['json']
        self.assertEqual(state['phase'], 'stack')
        state = self.infra(state, {'Stacks': {'member': self.app_stack()}})[0]['json']
        self.assertEqual(state['phase'], 'execution')
        state = self.infra(state, {'ExecutionStatus': 'AVAILABLE'})[0]['json']
        self.assertEqual(state['phase'], 'stack')
        self.assertFalse(state['ready'])
        state = self.infra(state, {'Stacks': {'member': self.app_stack()}})[0]['json']
        state = self.infra(state, {'ExecutionStatus': 'EXECUTE_COMPLETE'})[0]['json']
        self.assertEqual(state['phase'], 'collect')

    def test_stack_failures_access_denial_and_timeouts_do_not_provision(self):
        state = self.initial()
        state['phase'] = 'inspect'
        for status in ['ROLLBACK_COMPLETE', 'UPDATE_IN_PROGRESS', 'DELETE_COMPLETE']:
            self.assertIn('error', self.infra(state, {'Stacks': {'member': self.app_stack(status)}}))
        self.assertIn('AccessDenied', self.infra(state, {'Error': {'Code': 'AccessDenied', 'Message': 'denied'}}, 403)['error'])
        state['phase'] = 'stack'
        self.assertIn('failed', self.infra(state, {'Stacks': {'member': self.app_stack('UPDATE_ROLLBACK_COMPLETE')}})['error'])
        state['deadline'] = 0
        self.assertIn('timeout', self.run_code('Prepare infrastructure request', state)['error'])

    def test_ssm_online_requires_all_instances_in_current_paginated_sweep(self):
        state = self.initial()
        state['phase'] = 'collect'
        state = self.infra(state, {'Stacks': {'member': self.app_stack()}})[0]['json']
        ids = state['instanceIds']
        state = self.infra(state, {'InstanceInformationList': [{'InstanceId': ids[0], 'PingStatus': 'Online'}], 'NextToken': 'next'})[0]['json']
        self.assertFalse(state['ready'])
        state = self.infra(state, {'InstanceInformationList': [{'InstanceId': ids[1], 'PingStatus': 'Online'}]})[0]['json']
        self.assertEqual(state['onlineIds'], [])
        self.assertEqual(state['waitSeconds'], 10)
        state = self.infra(state, {'InstanceInformationList': [{'InstanceId': value, 'PingStatus': 'Online'} for value in ids]})[0]['json']
        self.assertTrue(state['ready'])

    def test_builds_deployment_from_live_stack_outputs_and_current_sources(self):
        ready = self.ready_state()
        state = self.run_code('Build deployment request', ready)[0]['json']
        self.assertEqual(state['frontendUrl'], 'http://203.0.113.10')
        self.assertEqual([step['component'] for step in state['steps']], ['database', 'backend', 'frontend'])
        commands = state['steps'][0]['commands']
        context = json.loads(base64.b64decode(commands[7].split("'")[3]))
        self.assertEqual(context['database_private_ip'], '10.0.3.10')
        self.assertEqual(context['athena_database'], 'noctua_analytics')
        self.assertEqual(context['backup_bucket'], 'noctua-backups-test')
        self.assertNotIn('profile', context)
        self.assertIn(ready['packageSha256'], commands[5])
        self.assertIn('gzip.decompress', commands[6])
        self.assertLess(len(json.dumps({'commands': commands}).encode()), 64000)

    def test_generated_unpack_command_preserves_source_bytes(self):
        files = self.input_files()
        files['script-noctua.sql'] = "-- UTF-8: aplicação\r\nSELECT 'quoted';\r\n"
        state = self.run_code('Load deployment inputs', files=files)[0]['json']
        ready = self.ready_state()
        ready.update(packageBase64=state['packageBase64'], packageSha256=state['packageSha256'])
        request = self.run_code('Build deployment request', ready)[0]['json']
        unpack = shlex.split(request['steps'][0]['commands'][6])
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'package.json.gz').write_bytes(base64.b64decode(state['packageBase64']))
            subprocess.run([sys.executable, *unpack[1:-1], directory], check=True, capture_output=True)
            self.assertEqual((root / 'schema.sql').read_bytes(), files['script-noctua.sql'].encode('utf-8'))
            self.assertEqual((root / 'remote_application.py').read_bytes(),
                             files['remote_application.py'].encode('utf-8'))

    def test_cloudformation_transient_http_body_is_safe_for_xml_parser(self):
        for status in [429, 500, 503]:
            result = self.run_code('Prepare XML response', {'statusCode': status, 'body': '<html>Unavailable'})
            self.assertEqual(result[0]['json']['body'], '<Response/>')
        xml = '<ErrorResponse><Error><Code>AccessDenied</Code></Error></ErrorResponse>'
        result = self.run_code('Prepare XML response', {'statusCode': 403, 'body': xml})
        self.assertEqual(result[0]['json']['body'], xml)

    def test_polling_handles_eventual_consistency_pending_and_success(self):
        for body in [{'__type': 'com.amazonaws.ssm#InvocationDoesNotExist'},
                     *[{'Status': status} for status in ['Pending', 'InProgress', 'Delayed', 'Cancelling']]]:
            self.assertFalse(self.evaluate(body)[0]['json']['done'])
        self.assertTrue(self.evaluate({'Status': 'Success', 'ResponseCode': 0})[0]['json']['done'])

    def test_polling_rejects_expired_credentials_failed_commands_and_timeouts(self):
        for body in [{'__type': 'ExpiredTokenException'}, {'__type': 'AccessDeniedException'},
                     *[{'Status': status, 'ResponseCode': 1} for status in ['Failed', 'TimedOut', 'Cancelled']],
                     {'Status': 'Success', 'ResponseCode': 1}]:
            self.assertIn('error', self.evaluate(body))
        self.assertIn('timeout', self.evaluate({'Status': 'Pending'}, deadline=0)['error'])

    def test_polling_retries_transient_http_errors_within_deadline(self):
        for status, body in [(429, {}), (503, {}), (500, {'__type': 'InternalServerError'}),
                             (400, {'__type': 'ThrottlingException'})]:
            self.assertFalse(self.evaluate(body, http_status=status)[0]['json']['done'])
            self.assertIn('timeout', self.evaluate(body, deadline=0, http_status=status)['error'])
        for status in [401, 403, 404]:
            self.assertIn('error', self.evaluate({}, http_status=status))

    def test_polling_reports_remote_error_and_rejects_wrong_invocation(self):
        result = self.evaluate({'Status': 'Failed', 'ResponseCode': 1,
                                'StandardErrorContent': 'Athena TABLE_NOT_FOUND'})
        self.assertIn('test-command', result['error'])
        self.assertIn('TABLE_NOT_FOUND', result['error'])
        for key in ['CommandId', 'InstanceId']:
            self.assertIn('error', self.evaluate({'Status': 'Success', 'ResponseCode': 0, key: 'wrong'}))
        self.assertIn('error', self.evaluate({}))

    def test_send_rejects_aws_errors_and_missing_command_id(self):
        context = {'step': {'component': 'database'}}
        for response in [{'statusCode': 400, 'body': {'__type': 'ExpiredTokenException'}},
                         {'statusCode': 503, 'body': {}}, {'statusCode': 200, 'body': {}}]:
            result = self.run_code('Track SSM command', response, context)
            self.assertIn('Inspect SSM command history', result['error'])
        self.assertFalse(self.nodes['Send SSM command']['retryOnFail'])

    def test_three_component_deploy_preserves_results_across_polling_and_step_loops(self):
        context = self.run_code('Build deployment request', self.ready_state())[0]['json']
        for index, component in enumerate(['database', 'backend', 'frontend']):
            context = self.run_code('Select step', context)[0]['json']
            self.assertEqual(context['step']['component'], component)
            self.assertFalse(context['done'])
            self.assertNotIn('commandId', context)
            self.assertNotIn('commandResult', context)
            command_id = f'{index:08x}-1234-1234-1234-123456789abc'
            context = self.run_code('Track SSM command',
                                    {'statusCode': 200, 'body': {'Command': {'CommandId': command_id}}},
                                    context)[0]['json']
            for status in ['Pending', 'InProgress', 'Success']:
                response = {'Status': status, 'ResponseCode': 0 if status == 'Success' else -1,
                            'CommandId': command_id, 'InstanceId': context['step']['instanceId'],
                            'StandardOutputContent': component + ' validated'}
                context = self.run_code('Evaluate command result',
                                        {'statusCode': 200, 'body': response}, context)[0]['json']
                if status != 'Success':
                    self.assertIn('error', self.run_code('Advance step', context))
            context = self.run_code('Advance step', context)[0]['json']
            self.assertEqual(context['stepIndex'], index + 1)
            self.assertEqual(len(context['results']), index + 1)
            if index < 2:
                self.assertIn('error', self.run_code('Deployment result', context))
        result = self.run_code('Deployment result', context)[0]['json']
        self.assertEqual(result['status'], 'DEPLOY_VALIDATED')
        self.assertEqual(result['athenaValidated'], configuration()['athena_enabled'])
        self.assertNotIn('steps', result)
        self.assertEqual([item['component'] for item in result['components']], ['database', 'backend', 'frontend'])
        for item in result['components']:
            self.assertEqual(item['standardOutput'], item['component'] + ' validated')
            self.assertEqual(item['pollCount'], 3)


if __name__ == '__main__':
    unittest.main()

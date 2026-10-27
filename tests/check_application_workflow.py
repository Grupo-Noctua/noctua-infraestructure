"""Execute the real n8n graph offline with synthetic AWS responses.

Requires Docker and a local n8n image. Uses a disposable, network-disabled container
and synthetic configuration; does not access the running n8n database or AWS.
With --http, keep the real HTTP nodes and serve fixtures over container loopback.
AWS signing uses dummy credentials imported only into the disposable container.
"""

import argparse
import json
from pathlib import Path
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from test_application import ROOT, WorkflowTests


def xml_response(action, data, error=False):
    root = ET.Element('ErrorResponse' if error else action + 'Response')
    parent = root if error else ET.SubElement(root, action + 'Result')

    def append(parent, key, value):
        if isinstance(value, list):
            for entry in value:
                append(parent, key, entry)
            return
        child = ET.SubElement(parent, key)
        if isinstance(value, dict):
            for name, entry in value.items():
                append(child, name, entry)
        else:
            child.text = str(value)

    for key, value in data.items():
        append(parent, key, value)
    ET.SubElement(root, 'ResponseMetadata').text = 'offline-check'
    return ET.tostring(root, encoding='unicode')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', default='noctua-infraestructure-n8n')
    parser.add_argument('--temp-dir', type=Path)
    parser.add_argument('--scenario', choices=['create', 'update', 'unchanged'], default='create')
    parser.add_argument('--http', action='store_true', help='Exercise real HTTP transport against local fixtures')
    args = parser.parse_args()
    fixture = WorkflowTests()
    workflow = json.loads((ROOT / 'application-n8n-noctua.json').read_text(encoding='utf-8'))
    workflow['id'] = 'noctua-offline-smoke'
    exports = [{'Name': name, 'Value': name + '-existing',
                'ExportingStackId': 'arn:aws:cloudformation:us-east-1:123:stack/network-stack/id'}
               for name in ['VPC-ID', 'PUBLIC-SUBNET', 'PRIVATE-BACKEND', 'PRIVATE-DB']]
    responses = {
        'exports': xml_response('ListExports', {'Exports': {'member': exports}}),
        'analytics': xml_response('DescribeStacks', {'Stacks': {'member': {
            'StackStatus': 'CREATE_COMPLETE', 'Outputs': {'member': [
                {'OutputKey': 'GlueDatabaseName', 'OutputValue': 'noctua_analytics'},
                {'OutputKey': 'AthenaWorkGroupName', 'OutputValue': 'existing-workgroup'}]}}}}),
        'validate': xml_response('ValidateTemplate', {}),
        'inspect': xml_response('DescribeStacks', {'Error': {
            'Code': 'ValidationError', 'Message': 'Stack with id noctua-application does not exist'}}, error=True),
        'plan': xml_response('CreateChangeSet', {'Id': 'change-id', 'StackId': 'stack-id'}),
        'changeset': xml_response('DescribeChangeSet', {'Status': 'CREATE_COMPLETE', 'ExecutionStatus': 'AVAILABLE'}),
        'execute': xml_response('ExecuteChangeSet', {}),
        'stack': xml_response('DescribeStacks', {'Stacks': {'member': fixture.app_stack()}}),
        'execution': xml_response('DescribeChangeSet', {'ExecutionStatus': 'EXECUTE_COMPLETE'}),
        'collect': xml_response('DescribeStacks', {'Stacks': {'member': fixture.app_stack()}}),
    }
    if args.scenario != 'create':
        responses['inspect'] = xml_response('DescribeStacks', {'Stacks': {'member': fixture.app_stack()}})
    if args.scenario == 'unchanged':
        responses['changeset'] = xml_response('DescribeChangeSet', {
            'Status': 'FAILED', 'StatusReason': "The submitted information didn't contain changes."})
        responses['cleanup'] = xml_response('DeleteChangeSet', {})
    inspect_status = 400 if args.scenario == 'create' else 200
    mocks = {
        'CloudFormation API': 'const responses = ' + json.dumps(responses) + '; const inspectStatus = ' + str(inspect_status) + """;
if (!responses[$json.phase]) throw new Error('Unexpected CloudFormation phase: ' + $json.phase);
return [{json: {statusCode: $json.phase === 'inspect' ? inspectStatus : 200, body: responses[$json.phase]}}];
""",
        'SSM infrastructure API': """
if ($json.phase === 'secrets') return [{json: {statusCode: 200, body: {
  Parameters: [{Name: $json.parameterNames[$json.parameterIndex], Type: 'SecureString'}]}}}];
if ($json.phase !== 'online') throw new Error('Unexpected SSM phase');
const state = $getWorkflowStaticData('global');
const ids = state.onlineChecked ? $json.instanceIds : [];
state.onlineChecked = true;
return [{json: {statusCode: 200, body: {InstanceInformationList:
  ids.map(InstanceId => ({InstanceId, PingStatus: 'Online'}))}}}];
""",
        'Send SSM command': """
const id = String($json.stepIndex).padStart(8, '0') + '-1234-1234-1234-123456789abc';
return [{json: {statusCode: 200, body: {Command: {CommandId: id}}}}];
""",
        'Get SSM status': """
return [{json: {statusCode: 200, body: {CommandId: $json.commandId,
  InstanceId: $json.step.instanceId, Status: $json.pollCount ? 'Success' : 'Pending',
  ResponseCode: $json.pollCount ? 0 : -1, StandardOutputContent: $json.step.component + ' checked'}}}];
""",
    }
    for node in workflow['nodes']:
        if node['name'] in mocks:
            if args.http:
                parameters = node['parameters']
                service = 'cloudformation' if node['id'] == 'application-cfn' else 'ssm'
                parameters['url'] = f'http://{service}.us-east-1.amazonaws.com:8765/' + node['id']
                node['credentials'] = {'aws': {'id': 'offline-aws', 'name': 'Offline dummy AWS'}}
                parameters['sendHeaders'] = True
                parameters.setdefault('headerParameters', {'parameters': []})['parameters'].append({
                    'name': 'X-Noctua-Fixture',
                    'value': '={{ JSON.stringify({phase: $json.phase, parameterNames: $json.parameterNames, '
                             'parameterIndex: $json.parameterIndex, instanceIds: $json.instanceIds, '
                             'stepIndex: $json.stepIndex, commandId: $json.commandId, pollCount: $json.pollCount, '
                             'step: {component: $json.step?.component, instanceId: $json.step?.instanceId} }) }}'})
            else:
                node.update(type='n8n-nodes-base.code', typeVersion=2,
                            parameters={'jsCode': mocks[node['name']]})
        if node['type'] == 'n8n-nodes-base.wait':
            node['parameters'] = {'amount': 0, 'unit': 'seconds'}
    workflow['nodes'].append({
        'id': 'assert-offline-smoke', 'name': 'Assert offline result',
        'type': 'n8n-nodes-base.code', 'typeVersion': 2, 'position': [2400, 820],
        'parameters': {'jsCode': 'const action = ' + json.dumps(args.scenario.upper()) + """;
if ($json.status !== 'DEPLOY_VALIDATED' || $json.infrastructure.action !== action ||
    $json.frontendUrl !== 'http://203.0.113.10' || $json.components.length !== 3 ||
    $json.components.some(item => item.pollCount !== 2 || item.status !== 'Success')) {
  throw new Error('Offline workflow result is incorrect');
}
return [{json: {smokeCheck: 'PASSED', components: $json.components.map(item => item.component)}}];
"""}})
    workflow['connections']['Deployment result'] = {
        'main': [[{'node': 'Assert offline result', 'type': 'main', 'index': 0}]]}

    with tempfile.TemporaryDirectory(prefix='noctua-n8n-check-', dir=args.temp_dir) as directory:
        root = Path(directory)
        paths = {'application.local.json': root / 'application.local.json',
                 'application.yaml': root / 'application.yaml',
                 'remote_application.py': root / 'scripts/remote_application.py',
                 'script-noctua.sql': root / 'database/script-noctua.sql'}
        for name, content in fixture.input_files().items():
            paths[name].parent.mkdir(parents=True, exist_ok=True)
            paths[name].write_text(content, encoding='utf-8')
        (root / 'workflow.json').write_text(json.dumps(workflow), encoding='utf-8')
        launch = 'n8n import:workflow --input=/files/workflow.json && n8n execute --id=noctua-offline-smoke'
        if args.http:
            (root / 'credentials.json').write_text(json.dumps([{
                'id': 'offline-aws', 'name': 'Offline dummy AWS', 'type': 'aws',
                'data': {'region': 'us-east-1', 'accessKeyId': 'OFFLINE_TEST_KEY',
                         'secretAccessKey': 'offline-test-secret', 'temporaryCredentials': True,
                         'sessionToken': 'offline-test-session'}}]), encoding='utf-8')
            handlers = {node['id']: mocks[node['name']] for node in workflow['nodes'] if node['name'] in mocks}
            server = 'const mocks = ' + json.dumps(handlers) + ';\n' + r"""
const http = require('http');
const assert = require('assert/strict');
const state = {};
const handlers = Object.fromEntries(Object.entries(mocks).map(([id, code]) =>
  [id, new Function('$json', '$getWorkflowStaticData', code)]));
http.createServer(async (req, res) => {
  try {
    const chunks = [];
    for await (const chunk of req) chunks.push(chunk);
    const text = Buffer.concat(chunks).toString('utf8');
    const id = req.url.slice(1);
    const context = JSON.parse(req.headers['x-noctua-fixture']);
    assert.equal(req.method, 'POST');
    const cloudformation = id === 'application-cfn';
    const service = cloudformation ? 'cloudformation' : 'ssm';
    assert.ok(req.headers.authorization.includes('/us-east-1/' + service + '/aws4_request'));
    assert.equal(req.headers['x-amz-security-token'], 'offline-test-session');
    if (cloudformation) {
      // n8n's default Accept prefers JSON even when Response Format is Text.
      assert.equal(req.headers.accept, 'application/xml');
      assert.match(req.headers['content-type'], /^application\/x-www-form-urlencoded/);
      assert.ok(new URLSearchParams(text).get('Action'));
    } else {
      assert.match(req.headers['content-type'], /^application\/x-amz-json-1\.1/);
      assert.match(req.headers['x-amz-target'], /^AmazonSSM\./);
      const body = JSON.parse(text);
      assert.equal(typeof body, 'object');
      assert.ok(body && !Array.isArray(body));
      if (id === 'application-send') assert.ok(body.Parameters.commands.length);
      if (id === 'application-get') assert.equal(body.CommandId, context.commandId);
    }
    const result = handlers[id](context, () => state)[0].json;
    // A real transient non-XML response must survive the HTTP and XML nodes.
    if (cloudformation && !state.httpTransientChecked) {
      state.httpTransientChecked = true;
      res.writeHead(503, {'Content-Type': 'text/html'});
      res.end('<html>Service unavailable');
      return;
    }
    res.writeHead(result.statusCode, {'Content-Type': cloudformation
      ? 'text/xml; charset=utf-8' : 'application/x-amz-json-1.1'});
    res.end(cloudformation ? result.body : JSON.stringify(result.body));
  } catch (error) {
    console.error(error);
    process.exit(1);
  }
}).listen(8765, '127.0.0.1');
"""
            (root / 'server.js').write_text(server, encoding='utf-8')
            launch = ('node /files/server.js & server=$!; trap "kill $server" EXIT; '
                      'n8n import:credentials --input=/files/credentials.json && ' + launch)
        command = ['docker', 'run', '--rm', '--network', 'none',
                   '--add-host', 'cloudformation.us-east-1.amazonaws.com:127.0.0.1',
                   '--add-host', 'ssm.us-east-1.amazonaws.com:127.0.0.1',
                   '--mount', f'type=bind,source={root},target=/files,readonly',
                   '-e', 'N8N_RESTRICT_FILE_ACCESS_TO=/files',
                   '-e', 'NODE_FUNCTION_ALLOW_BUILTIN=crypto,zlib',
                   '-e', 'N8N_DIAGNOSTICS_ENABLED=false', '-e', 'N8N_VERSION_NOTIFICATIONS_ENABLED=false',
                   '-e', 'N8N_LOG_LEVEL=info', '--entrypoint', 'sh', args.image, '-c',
                   launch]
        result = subprocess.run(command, text=True, encoding='utf-8', errors='replace',
                                capture_output=True, timeout=240)
        if result.returncode or 'Execution was successful:' not in result.stdout:
            print(result.stdout)
            print(result.stderr)
            raise SystemExit('Offline n8n execution failed')
        print('PASS (' + args.scenario + '): n8n import, mounted input files, crypto/zlib, CloudFormation XML,')
        print('      infrastructure loop, item linking and database/backend/frontend polling.')
        if args.http:
            print('      Real HTTP nodes: form/JSON requests, XML/JSON responses and status 400/503 handling.')
            print('      AWS signing with dummy credentials against loopback only.')


if __name__ == '__main__':
    main()

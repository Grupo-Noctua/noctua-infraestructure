"""Build/test and publish both applications to Docker Hub using an existing docker login."""

import argparse
import json
from pathlib import Path
import re
import subprocess
import sys


def command(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--release', required=True)
    parser.add_argument('--backend', type=Path, default=Path(__file__).resolve().parents[2] / 'noctua-backend')
    parser.add_argument('--frontend', type=Path, default=Path(__file__).resolve().parents[2] / 'noctua-frontend')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_-]+', args.namespace) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', args.release):
        raise ValueError('Invalid Docker Hub namespace or release tag')
    if args.release == 'latest':
        raise ValueError('Use a release identifier rather than latest')
    # Test/build both before publishing either. EC2 AMIs in application.yaml are amd64.
    images = {}
    for component in ['backend', 'frontend']:
        image = f'docker.io/{args.namespace}/noctua-{component}:{args.release}'
        source = getattr(args, component).resolve()
        command('docker', 'build', '--platform', 'linux/amd64', '-t', image, str(source))
        if component == 'backend':
            command(sys.executable, str(source / 'scripts/verify_image.py'), image)
        images[component] = image
    references = {}
    for component, image in images.items():
        command('docker', 'push', image)
        metadata = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
        repository = image.split(':')[0].removeprefix('docker.io/')
        matches = [digest for digest in metadata['RepoDigests']
                   if digest.removeprefix('docker.io/').split('@')[0] == repository]
        if len(matches) != 1:
            raise RuntimeError(f'Could not identify published digest for {component}')
        references[f'{component}_image'] = 'docker.io/' + matches[0].removeprefix('docker.io/')
    print('\nCopy these immutable references into application.local.json:')
    print(json.dumps(references, indent=2))


if __name__ == '__main__':
    main()

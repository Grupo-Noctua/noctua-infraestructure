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
    parser.add_argument('--frontend-variants', action='store_true',
                        help='Build frontend A (blue) and B (orange) for the load balancer')
    parser.add_argument('--build-only', action='store_true', help='Build and verify without pushing to Docker Hub')
    parser.add_argument('--backend', type=Path, default=Path(__file__).resolve().parents[2] / 'noctua-backend')
    parser.add_argument('--frontend', type=Path, default=Path(__file__).resolve().parents[2] / 'noctua-frontend')
    args = parser.parse_args()
    if not re.fullmatch(r'[a-z0-9_-]+', args.namespace) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}', args.release):
        raise ValueError('Invalid Docker Hub namespace or release tag')
    if args.release == 'latest':
        raise ValueError('Use a release identifier rather than latest')
    if args.frontend_variants and len(args.release) > 123:
        raise ValueError('Release tag must allow the -base and -b suffixes')
    # Test/build both before publishing either. EC2 AMIs in application.yaml are amd64.
    images = {}
    for component in ['backend', 'frontend']:
        image = f'docker.io/{args.namespace}/noctua-{component}:{args.release}'
        source = getattr(args, component).resolve()
        base = image + '-base' if component == 'frontend' and args.frontend_variants else image
        command('docker', 'build', '--platform', 'linux/amd64', '-t', base, str(source))
        if component == 'backend':
            command(sys.executable, str(source / 'scripts/verify_image.py'), image)
        images[component] = image
        if component == 'frontend':
            if args.frontend_variants:
                images['frontend_b'] = image + '-b'
                for variant, target in [('A', image), ('B', images['frontend_b'])]:
                    command('docker', 'build', '--platform', 'linux/amd64',
                            '--build-arg', f'FRONTEND_BASE={base}', '--build-arg', f'FRONTEND_VARIANT={variant}',
                            '-t', target, str(Path(__file__).resolve().parents[1] / 'files/frontend-variant'))
            for key in ['frontend', *(['frontend_b'] if args.frontend_variants else [])]:
                command(sys.executable, str(Path(__file__).resolve().parents[1] / 'tests/check_frontend_image.py'),
                        images[key], *(['--variant', 'B' if key == 'frontend_b' else 'A'] if args.frontend_variants else []))
    if args.build_only:
        print(json.dumps(images, indent=2))
        return
    references = {}
    for component, image in images.items():
        command('docker', 'push', image)
        metadata = json.loads(subprocess.check_output(['docker', 'image', 'inspect', image], text=True))[0]
        repository = image.split(':')[0].removeprefix('docker.io/')
        matches = [digest for digest in metadata['RepoDigests']
                   if digest.removeprefix('docker.io/').split('@')[0] == repository]
        if len(matches) != 1:
            raise RuntimeError(f'Could not identify published digest for {component}')
        key = 'frontend_image_b' if component == 'frontend_b' else f'{component}_image'
        references[key] = 'docker.io/' + matches[0].removeprefix('docker.io/')
    print('\nCopy these immutable references into application.local.json:')
    print(json.dumps(references, indent=2))


if __name__ == '__main__':
    main()

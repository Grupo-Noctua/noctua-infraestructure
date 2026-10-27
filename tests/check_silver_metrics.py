"""Compare the four live Athena endpoints with independently aggregated source CSV."""

import argparse
from collections import Counter, defaultdict
import csv
from decimal import Decimal
import json
from pathlib import Path
import re
import unicodedata
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
LANGUAGES = {
    'sql': 'sql', 'r': 'r', 'python': 'python', 'c/c++/c#': 'c_c_c',
    'net': 'net', 'java': 'java', 'julia': 'julia', 'sas/stata': 'sas_stata',
    'visual_basic/vba': 'visual_basic_vba', 'scala': 'scala', 'matlab': 'matlab',
    'php': 'php', 'javascript': 'javascript',
}


def normalize(value):
    value = unicodedata.normalize('NFKD', value.strip().lower()).encode('ascii', 'ignore').decode()
    value = value.replace(' ', '_').replace('.', '')
    return re.sub('_+', '_', re.sub('[^a-z0-9_]', '_', value)).strip('_') or 'coluna'


def expected_metrics(source):
    total = 0
    technologies = Counter({name: 0 for name in LANGUAGES})
    seniorities = Counter()
    areas = defaultdict(set)
    with source.open(encoding='iso-8859-1', newline='') as stream:
        reader = csv.reader(stream, delimiter=';', quotechar='"', doublequote=True)
        # Doubled quotes represent a literal quote, matching the Spark reader.
        raw_header = next(reader)
        if raw_header and raw_header[0].lower().startswith('column'):
            raw_header = next(reader)
        seen = Counter()
        header = []
        for name in raw_header:
            name = normalize(name)
            header.append(name if not seen[name] else f'{name}_{seen[name]}')
            seen[name] += 1
        required = set(LANGUAGES.values()) | {'id', 'nivel', 'atuacao'}
        if not required.issubset(header):
            raise ValueError(f'Missing source columns: {sorted(required - set(header))}')
        for values in reader:
            if not values:
                continue
            row = dict(zip(header, values))
            total += 1
            for label, column in LANGUAGES.items():
                value = row.get(column, '').strip()
                if value and Decimal(value) == 1:
                    technologies[label] += 1
            level = row.get('nivel', '').strip()
            if level in {'Sênior', 'Pleno', 'Júnior'}:
                seniorities[level] += 1
            area, identity = row.get('atuacao', '').strip(), row.get('id', '')
            if area and identity:
                areas[area].add(identity)
    return {
        'total': total,
        'tecnologia': dict(technologies) if total else {},
        'senioridade': dict(seniorities),
        'area': {area: len(identities) for area, identities in areas.items()},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'files/base_externa_bronze_pi.csv')
    parser.add_argument('--base-url', help='Public frontend URL; omit to print expected aggregates only')
    args = parser.parse_args()
    expected = expected_metrics(args.source)
    if not args.base_url:
        print(json.dumps(expected, ensure_ascii=True, indent=2))
        return
    dimensions = {'tecnologia': 'tecnologia', 'senioridade': 'senioridade', 'area': 'area'}
    for route, wanted in expected.items():
        url = args.base_url.rstrip('/') + '/api/dashboard/funcionarios/' + route
        with urlopen(url, timeout=60) as response:
            body = json.load(response)
        actual = body['total'] if route == 'total' else {
            item[dimensions[route]]: item['quantidade'] for item in body}
        if actual != wanted:
            raise AssertionError(f'{route}: expected {wanted!r}, received {actual!r}')
        print(f'OK funcionarios/{route}: matches source CSV')
    print(f'Validated {expected["total"]} source rows against the live API')


if __name__ == '__main__':
    main()

import ast
import csv
import io
from pathlib import Path
import re
import unicodedata
import unittest


# Exercise the actual pure parser functions without starting a Glue/Spark job.
source = Path(__file__).resolve().parents[1] / 'files/silver.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
names = {'normalize_colname', 'deduplicate_columns', 'source_document', 'source_width', 'source_rows'}
helpers = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef)
                          and node.name in names], type_ignores=[])
namespace = {'csv': csv, 'io': io, 're': re, 'unicodedata': unicodedata}
exec(compile(helpers, str(source), 'exec'), namespace)


class SilverSourceTests(unittest.TestCase):
    def test_multiline_quotes_and_delimiters_preserve_records(self):
        content = ('id;nível;resposta\r\n'
                   '1;Pleno;"texto; com vírgula, e\nquebra com ""aspas"""\r\n'
                   '2;Júnior;normal\r\n'
                   '3;Sênior;\r\n').encode('iso-8859-1')
        columns, _ = namespace['source_document'](content)
        rows = list(namespace['source_rows'](content, columns))
        self.assertEqual(columns, ('id', 'nivel', 'resposta'))
        self.assertEqual(rows, [
            ('1', 'Pleno', 'texto; com vírgula, e\nquebra com "aspas"'),
            ('2', 'Júnior', 'normal'), ('3', 'Sênior', None),
        ])

    def test_short_and_extra_fields_preserve_named_column_positions(self):
        content = b'id;area\n1;Dados;extra\n2\n'
        columns, _ = namespace['source_document'](content)
        self.assertEqual(namespace['source_width'](content), 3)
        rows = list(namespace['source_rows'](content, (*columns, 'coluna_extra_2')))
        self.assertEqual(rows, [('1', 'Dados', 'extra'), ('2', None, None)])

    def test_rejects_mismatched_headers(self):
        with self.assertRaises(ValueError):
            list(namespace['source_rows'](b'id;area\n1;Dados\n', ['id', 'nivel']))

    def test_source_matches_independent_csv_aggregates(self):
        from check_silver_metrics import expected_metrics
        original = source.with_name('base_externa_bronze_pi.csv')
        content = original.read_bytes()
        columns, _ = namespace['source_document'](content)
        width = namespace['source_width'](content)
        columns = list(columns) + [f'coluna_extra_{i}' for i in range(len(columns), width)]
        records = list(namespace['source_rows'](content, columns))
        self.assertEqual(len(records), expected_metrics(original)['total'])
        self.assertGreater(len(records), 0)


if __name__ == '__main__':
    unittest.main()

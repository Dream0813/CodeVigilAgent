"""`model --list [--json]`：给桌面端下拉框提供机器可读模型清单。

覆盖：JSON 可解析、厂商数与 CATALOG 一致、default_model 在 models 内、
绝不出现 api_key、--list 与写入参数互斥（退出码 2）、current 标记正确。
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts.model_catalog import CATALOG

ROOT = Path(__file__).resolve().parent.parent
CLI = ROOT / 'ascend_cli.py'


class ModelListJsonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)

    def run_cli(self, *args):
        env = dict(os.environ)
        env['REVIEWAGENT_HOME'] = str(self.home)
        env.pop('REVIEWAGENT_CONFIG', None)
        # 清掉可能覆盖文件配置的环境变量，保证 current 只看配置文件
        for key in ('AI_PROVIDER', 'AI_MODEL', 'AI_BASE_URL'):
            env.pop(key, None)
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONDONTWRITEBYTECODE'] = '1'
        return subprocess.run(
            [sys.executable, str(CLI), 'model'] + list(args),
            cwd=str(ROOT), env=env, capture_output=True, timeout=120,
        )

    def write_config(self, **values):
        (self.home / 'ai_config.json').write_text(
            json.dumps(values, ensure_ascii=False), encoding='utf-8')

    def test_json_output_is_parseable_and_matches_catalog(self):
        result = self.run_cli('--list', '--json')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        payload = json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(len(payload['catalog']), len(CATALOG))
        self.assertEqual([entry['label'] for entry in payload['catalog']],
                         [entry['label'] for entry in CATALOG])
        for entry in payload['catalog']:
            self.assertIn(entry['default_model'], entry['models'])
            self.assertTrue(entry['models'])
            self.assertTrue(entry['file_provider'])
            self.assertIsInstance(entry['base_url'], str)
            self.assertIsInstance(entry['current'], bool)
        self.assertEqual(set(payload['active']), {'provider', 'model', 'base_url'})

    def test_output_is_pure_json_without_ansi_or_hint_text(self):
        result = self.run_cli('--list', '--json')
        raw = result.stdout
        self.assertNotIn(b'\x1b[', raw)
        # 行尾必须是 LF：Windows 上 print() 会变 CRLF，三平台字节就不一致了
        self.assertNotIn(b'\r', raw)
        decoded = raw.decode('utf-8')
        self.assertEqual(decoded.lstrip()[:1], '{')
        json.loads(decoded)  # 全文就是一个 JSON 文档，没有前后夹带提示行
        self.assertEqual(result.stderr.strip(), b'')

    def test_output_never_contains_api_key(self):
        secret = 'sk-test-secret-should-never-leak-1234'
        self.write_config(provider='glm', model='glm-4-flash', base_url='',
                          api_key=secret)
        result = self.run_cli('--list', '--json')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        text = result.stdout.decode('utf-8')
        self.assertNotIn(secret, text)
        self.assertNotIn(secret[:4], text)
        self.assertNotIn('api_key', text)
        self.assertNotIn('api_key', text.replace('-', '_'))

    def test_list_is_exclusive_with_write_flags(self):
        for extra in (['--provider', 'deepseek'], ['--name', 'glm-4'], ['--base-url', 'http://x']):
            result = self.run_cli('--list', *extra)
            self.assertEqual(result.returncode, 2, (extra, result.stdout, result.stderr))
            self.assertIn('--list', result.stderr.decode('utf-8', 'replace'))
        # 互斥时不能偷偷写配置
        self.assertFalse((self.home / 'ai_config.json').exists())

    def test_json_without_list_is_a_usage_error(self):
        result = self.run_cli('--json')
        self.assertEqual(result.returncode, 2)
        self.assertIn('--list', result.stderr.decode('utf-8', 'replace'))

    def test_current_flag_follows_configured_provider(self):
        self.write_config(provider='deepseek', model='deepseek-reasoner', base_url='')
        payload = json.loads(self.run_cli('--list', '--json').stdout.decode('utf-8'))
        current = [entry['label'] for entry in payload['catalog'] if entry['current']]
        self.assertEqual(current, ['deepseek'])
        # 模型不在清单里也必须原样回显，不能改写成 default_model
        self.assertEqual(payload['active']['model'], 'deepseek-reasoner')

    def test_current_flag_tracks_base_url_for_shared_provider(self):
        self.write_config(provider='openai', model='MiniMax-Text-01',
                          base_url='https://api.minimax.chat/v1')
        payload = json.loads(self.run_cli('--list', '--json').stdout.decode('utf-8'))
        current = [entry['label'] for entry in payload['catalog'] if entry['current']]
        self.assertEqual(current, ['minimax'])

    def test_text_list_still_works_without_json(self):
        result = self.run_cli('--list')
        self.assertEqual(result.returncode, 0)
        text = result.stdout.decode('utf-8')
        for entry in CATALOG:
            self.assertIn(entry['label'], text)
            self.assertIn(entry['default_model'], text)

    def test_broken_config_still_lists_catalog(self):
        (self.home / 'ai_config.json').write_text('{not json', encoding='utf-8')
        result = self.run_cli('--list', '--json')
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        payload = json.loads(result.stdout.decode('utf-8'))
        self.assertEqual(len(payload['catalog']), len(CATALOG))
        self.assertFalse(any(entry['current'] for entry in payload['catalog']))
        self.assertEqual(payload['active'], {'provider': '', 'model': '', 'base_url': ''})

    def test_list_does_not_create_home_or_config(self):
        home = self.home / 'never-created'
        env = dict(os.environ, REVIEWAGENT_HOME=str(home))
        env.pop('REVIEWAGENT_CONFIG', None)
        result = subprocess.run(
            [sys.executable, str(CLI), 'model', '--list', '--json'],
            cwd=str(ROOT), env=env, capture_output=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        json.loads(result.stdout.decode('utf-8'))
        self.assertFalse(home.exists(), '只读命令不应该创建 REVIEWAGENT_HOME')

    def test_alias_and_trailing_slash_still_mark_current(self):
        cases = [
            ({'provider': 'zhipu', 'model': 'glm-4-flash', 'base_url': ''}, 'glm'),
            ({'provider': 'Anthropic', 'model': 'claude-3-5-sonnet-20241022', 'base_url': ''}, 'claude'),
            ({'provider': 'openai', 'model': 'MiniMax-Text-01',
              'base_url': 'https://api.minimax.chat/v1/'}, 'minimax'),
            ({'provider': 'openai', 'model': 'gpt-4o', 'base_url': ''}, 'openai'),
        ]
        for config, expected in cases:
            self.write_config(**config)
            payload = json.loads(self.run_cli('--list', '--json').stdout.decode('utf-8'))
            current = [entry['label'] for entry in payload['catalog'] if entry['current']]
            self.assertEqual(current, [expected], config)

    def test_exactly_one_current_for_every_catalog_entry(self):
        # 纯逻辑，直接在进程内跑，避免 36 次子进程拖慢全量测试
        from scripts.model_catalog import catalog_payload

        for entry in CATALOG:
            for base in {entry['base_url'], '', entry['base_url'].rstrip('/') + '/'}:
                payload = catalog_payload({
                    'provider': entry['file_provider'],
                    'model': entry['default_model'],
                    'base_url': base,
                })
                current = [item['label'] for item in payload['catalog'] if item['current']]
                self.assertEqual(len(current), 1, (entry['label'], base, current))

    def test_weird_config_types_do_not_crash_list(self):
        cases = ['[1, 2, 3]', '"hello"',
                 '{"provider": 123, "model": 456, "base_url": null}', '{}']
        for text in cases:
            (self.home / 'ai_config.json').write_text(text, encoding='utf-8')
            result = self.run_cli('--list', '--json')
            self.assertEqual(result.returncode, 0, (text, result.stderr))
            payload = json.loads(result.stdout.decode('utf-8'))
            self.assertEqual(len(payload['catalog']), len(CATALOG))
            self.assertIsInstance(payload['active']['provider'], str)
        # 非法 UTF-8 字节
        (self.home / 'ai_config.json').write_bytes(b'{"provider": "\xff\xfe"}')
        result = self.run_cli('--list', '--json')
        self.assertEqual(result.returncode, 0, result.stderr)
        json.loads(result.stdout.decode('utf-8'))

    def test_write_path_refuses_broken_config_without_overwriting(self):
        broken = b'{"provider": "\xff\xfe"}'
        (self.home / 'ai_config.json').write_bytes(broken)
        result = self.run_cli('--provider', 'glm')
        self.assertEqual(result.returncode, 1)
        self.assertIn('未做任何修改', result.stderr.decode('utf-8', 'replace'))
        self.assertEqual((self.home / 'ai_config.json').read_bytes(), broken)


if __name__ == '__main__':
    unittest.main()

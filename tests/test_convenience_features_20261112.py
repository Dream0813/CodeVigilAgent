# -*- coding: utf-8 -*-
"""2026-11-12：便利功能（与审查逻辑无关，纯为省事）。

    1. open 命令：用系统默认程序打开配置/会话/备份/仓库目录
    2. config --backup / --backups / --restore：配置备份与回滚
    3. /copy：把上一条回答复制到剪贴板
    4. 命令拼错时给出「你是不是想输入 /review」
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ascend_cli
from scripts.clipboard import copy_text
from scripts.config_backup import create_backup, list_backups, restore_backup
from scripts.system_open import open_path


class SystemOpenTests(unittest.TestCase):
    def test_missing_path_is_reported(self):
        ok, detail = open_path('/definitely/not/here-20261112')
        self.assertFalse(ok)
        self.assertIn('路径不存在', detail)

    def test_empty_target(self):
        ok, detail = open_path('')
        self.assertFalse(ok)
        self.assertIn('没有指定', detail)

    def test_injected_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            ok, detail = open_path(tmp, launcher=lambda p: (True, '已打开'))
        self.assertTrue(ok)
        self.assertIn('已打开', detail)

    def test_launcher_exception_does_not_raise(self):
        with tempfile.TemporaryDirectory() as tmp:
            def boom(_path):
                raise RuntimeError('没有图形界面')
            ok, detail = open_path(tmp, launcher=boom)
        self.assertFalse(ok)
        self.assertIn('没有图形界面', detail)


class ClipboardTests(unittest.TestCase):
    def test_success(self):
        seen = []
        ok, detail = copy_text('你好', backend=seen.append)
        self.assertTrue(ok)
        self.assertEqual(seen, ['你好'])
        self.assertIn('剪贴板', detail)

    def test_empty(self):
        ok, detail = copy_text('')
        self.assertFalse(ok)
        self.assertIn('没有可复制', detail)

    def test_backend_failure(self):
        def boom(_text):
            raise OSError('剪贴板被占用')
        ok, detail = copy_text('x', backend=boom)
        self.assertFalse(ok)
        self.assertIn('剪贴板被占用', detail)
        self.assertIn('手动', detail)


class ConfigBackupTests(unittest.TestCase):
    def _config(self, tmp: Path, text: str) -> Path:
        path = tmp / 'ai_config.json'
        path.write_text(text, encoding='utf-8')
        return path

    def test_missing_config_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(create_backup(Path(tmp) / 'nope.json', directory=Path(tmp) / 'b'))

    def test_backup_list_order_and_prune(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._config(root, '{"v": 1}')
            store = root / 'backups'
            for index in range(4):
                cfg.write_text(json.dumps({'v': index}), encoding='utf-8')
                create_backup(cfg, tag=f't{index}', directory=store, keep=2)
            rows = list_backups(store)
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(p.is_file() for p in rows))

    def test_restore_latest_and_keep_safety_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._config(root, '{"model": "old"}')
            store = root / 'backups'
            create_backup(cfg, tag='manual', directory=store)
            cfg.write_text('{"model": "broken"}', encoding='utf-8')

            source, safety = restore_backup(cfg, directory=store)

            self.assertEqual(json.loads(cfg.read_text(encoding='utf-8'))['model'], 'old')
            self.assertTrue(source.exists())
            self.assertIsNotNone(safety)
            self.assertIn('before-restore', safety.name)

    def test_restore_by_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = self._config(root, '{"model": "v1"}')
            store = root / 'backups'
            first = create_backup(cfg, tag='manual', directory=store)
            cfg.write_text('{"model": "v2"}', encoding='utf-8')

            restore_backup(cfg, name=first.name[:20], directory=store)
            self.assertEqual(json.loads(cfg.read_text(encoding='utf-8'))['model'], 'v1')

    def test_restore_without_backup_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                restore_backup(Path(tmp) / 'cfg.json', directory=Path(tmp) / 'empty')


class SlashConvenienceTests(unittest.TestCase):
    class Agent:
        work_root = Path.cwd()
        last_reply = '上一条回答'

    def _run(self, text, agent=None):
        agent = agent or self.Agent()
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = ascend_cli.handle_chat_slash(text, agent)
        return result, out.getvalue()

    def test_copy_success(self):
        with patch('scripts.cli_commands.convenience.copy_text', return_value=(True, '已复制 5 个字符到剪贴板')):
            result, out = self._run('/copy')
        self.assertEqual(result, 'handled')
        self.assertIn('已复制', out)

    def test_copy_without_reply(self):
        class Agent(self.Agent):
            last_reply = None
        _, out = self._run('/copy', Agent())
        self.assertIn('没有可复制的回答', out)

    def test_copy_failure_suggests_manual(self):
        with patch('scripts.cli_commands.convenience.copy_text', return_value=(False, '复制失败：无后端（可以手动选中复制）')):
            _, out = self._run('/copy')
        self.assertIn('手动', out)

    def test_dir_opens_selected_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            class Agent(self.Agent):
                desktop_repository = tmp

            captured = {}

            def fake_open(path):
                captured['path'] = str(path)
                return True, '已打开'

            with patch('scripts.cli_commands.convenience.open_path', side_effect=fake_open):
                _, out = self._run('/dir repo', Agent())
            self.assertEqual(Path(captured['path']), Path(tmp))
            self.assertIn('已打开', out)

    def test_dir_unknown_target_shows_usage(self):
        _, out = self._run('/dir 什么')
        self.assertIn('用法', out)

    def test_typo_suggests_closest_command(self):
        _, out = self._run('/revew')
        self.assertIn('未知命令', out)
        self.assertIn('你是不是想输入 /review', out)

    def test_typo_between_custom_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / '.reviewagent/commands').mkdir(parents=True)
            (root / '.reviewagent/commands/并发.md').write_text('检查并发', encoding='utf-8')

            class Agent(self.Agent):
                work_root = root

            with patch.dict(os.environ, {'HOME': str(root), 'USERPROFILE': str(root)}):
                _, out = self._run('/并法', Agent())
            self.assertIn('你是不是想输入 /并发', out)


class CliOpenAndConfigTests(unittest.TestCase):
    def test_open_cmd_success_and_failure(self):
        with patch('ascend_cli.open_path', return_value=(True, '已打开：x')):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ascend_cli.open_cmd(argparse.Namespace(target='repo')), 0)
        with patch('ascend_cli.open_path', return_value=(False, '路径不存在：x')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ascend_cli.open_cmd(argparse.Namespace(target='repo'))
            self.assertEqual(code, 1)
            self.assertIn('ERROR', out.getvalue())

    def _config_args(self, **overrides):
        base = dict(config=None, init=False, wizard=False, show=False, set=None,
                    backup=False, backups=False, restore=None)
        base.update(overrides)
        return argparse.Namespace(**base)

    def test_config_backup_restore_and_auto_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = root / 'ai_config.json'
            cfg.write_text('{"model": "v1"}', encoding='utf-8')
            env = {'REVIEWAGENT_HOME': str(root), 'REVIEWAGENT_BACKUP_DIR': str(root / 'backups')}

            with patch.dict(os.environ, env):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    code = ascend_cli.config_cmd(self._config_args(config=str(cfg), backup=True))
                self.assertEqual(code, 0)
                self.assertIn('已备份', out.getvalue())
                self.assertEqual(len(list_backups()), 1)

                # --set 会自动再备份一份
                with contextlib.redirect_stdout(io.StringIO()):
                    ascend_cli.config_cmd(self._config_args(config=str(cfg), set=['model=v2']))
                self.assertEqual(json.loads(cfg.read_text(encoding='utf-8'))['model'], 'v2')
                self.assertEqual(len(list_backups()), 2)

                # 恢复最近一份（v1）
                with contextlib.redirect_stdout(io.StringIO()):
                    code = ascend_cli.config_cmd(self._config_args(config=str(cfg), restore='latest'))
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(cfg.read_text(encoding='utf-8'))['model'], 'v1')

                # 恢复前的 v2 也留了安全备份
                self.assertTrue(any('before-restore' in p.name for p in list_backups()))


if __name__ == '__main__':
    unittest.main()

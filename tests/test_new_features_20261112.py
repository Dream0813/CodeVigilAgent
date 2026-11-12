# -*- coding: utf-8 -*-
"""2026-11-12 新增功能回归测试。

覆盖四件事（参考同类 Agent 后补齐的能力）：

    1. 自定义斜杠命令   .reviewagent/commands/*.md（Claude Code 风格）
    2. @文件引用        @path 附带仓库文件内容（Cursor / aider /read 风格）
    3. 提交门禁         review --fail-on + install-hook（CodeRabbit 风格）
    4. 会话用量估算     /cost（Claude Code /cost、aider /tokens 风格）
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import ascend_cli
from scripts.custom_commands import (
    CustomCommand,
    expand_command,
    find_command,
    format_commands,
    load_commands,
)
from scripts.file_mentions import expand as expand_mentions
from scripts.git_hooks import (
    HookError,
    MARKER_START,
    build_hook,
    install,
    is_installed,
    remove,
)
from scripts.usage_meter import UsageMeter, estimate_tokens


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding='utf-8')


def _silence_home(tmp: Path):
    """让 ~ 指向临时目录，避免读到开发机上真实的用户级命令。"""
    return patch.dict(os.environ, {'HOME': str(tmp), 'USERPROFILE': str(tmp)})


class CustomCommandsTests(unittest.TestCase):
    def test_reads_frontmatter_and_namespacing(self):
        with tempfile.TemporaryDirectory() as tmp, _silence_home(Path(tmp)):
            root = Path(tmp)
            _write(root / '.reviewagent/commands/并发.md',
                   '---\ndescription: 查并发\nargument-hint: <文件>\n---\n检查 @$ARGUMENTS 的锁\n')
            _write(root / '.reviewagent/commands/db/slow.md', '分析慢查询：$ARGUMENTS\n')

            commands, warnings = load_commands(str(root))

            self.assertEqual(warnings, [])
            self.assertEqual(sorted(commands), ['db:slow', '并发'])
            self.assertEqual(commands['并发'].description, '查并发')
            self.assertEqual(commands['并发'].argument_hint, '<文件>')
            self.assertEqual(commands['并发'].source, 'project')

    def test_expand_arguments_placeholder_and_append(self):
        with_placeholder = CustomCommand(name='a', body='检查 $ARGUMENTS 的锁')
        self.assertEqual(expand_command(with_placeholder, 'src/a.py'), '检查 src/a.py 的锁')

        no_placeholder = CustomCommand(name='b', body='总结这个仓库')
        self.assertEqual(expand_command(no_placeholder, '只看 tests'),
                         '总结这个仓库\n\n补充参数：只看 tests')
        self.assertEqual(expand_command(no_placeholder, ''), '总结这个仓库')

    def test_braced_placeholder_supported(self):
        cmd = CustomCommand(name='x', body='审查 ${ARGUMENTS}')
        self.assertEqual(expand_command(cmd, 'a.py'), '审查 a.py')

    def test_project_overrides_user(self):
        with tempfile.TemporaryDirectory() as tmp, _silence_home(Path(tmp)):
            home = Path(tmp)
            repo = home / 'repo'
            repo.mkdir()
            _write(home / '.reviewagent/commands/same.md', '用户级正文')
            _write(repo / '.reviewagent/commands/same.md', '项目级正文')

            commands, _ = load_commands(str(repo))

            self.assertEqual(commands['same'].body, '项目级正文')
            self.assertEqual(commands['same'].source, 'project')

    def test_invalid_and_empty_files_are_skipped_with_warnings(self):
        with tempfile.TemporaryDirectory() as tmp, _silence_home(Path(tmp)):
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            _write(repo / '.reviewagent/commands/bad name.md', '正文')
            _write(repo / '.reviewagent/commands/empty.md', '---\ndescription: 只有元数据\n---\n')
            commands, warnings = load_commands(str(repo))
            self.assertEqual(commands, {})
            self.assertEqual(len(warnings), 2)

    def test_find_command(self):
        commands = {'并发': CustomCommand(name='并发', body='x')}
        found, args = find_command('/并发 @src/a.py', commands)
        self.assertIsNotNone(found)
        self.assertEqual(args, '@src/a.py')
        self.assertEqual(find_command('/不存在', commands), (None, ''))

    def test_format_commands_lists_or_hint(self):
        self.assertIn('还没有自定义命令', format_commands([]))
        text = format_commands([CustomCommand(name='x', description='描述', source='project')])
        self.assertIn('/x', text)
        self.assertIn('project', text)


class FileMentionTests(unittest.TestCase):
    def test_no_at_returns_original(self):
        text, notes, warnings = expand_mentions('普通消息', os.getcwd())
        self.assertEqual(text, '普通消息')
        self.assertEqual((notes, warnings), ([], []))

    def test_file_is_attached(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / 'src/a.py', 'print(1)\n')
            text, notes, warnings = expand_mentions('看下 @src/a.py', str(root))
            self.assertIn('<file path="src/a.py">', text)
            self.assertIn('print(1)', text)
            self.assertEqual(len(notes), 1)
            self.assertEqual(warnings, [])

    def test_trailing_punctuation_trimmed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / 'a.py', 'x = 1\n')
            text, notes, _ = expand_mentions('看看 @a.py，是不是有问题', str(root))
            self.assertEqual(len(notes), 1)
            self.assertIn('a.py', text)

    def test_directory_listing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'pkg').mkdir()
            _write(root / 'pkg/m.py', '')
            text, notes, _ = expand_mentions('@pkg/', str(root))
            self.assertIn('<dir path="pkg">', text)
            self.assertIn('m.py', text)
            self.assertIn('已附带目录', notes[0])

    def test_outside_repo_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'repo'
            root.mkdir()
            _write(Path(tmp) / 'secret.txt', 'top secret')
            _, notes, warnings = expand_mentions('@../secret.txt', str(root))
            self.assertEqual(notes, [])
            self.assertTrue(any('不在当前仓库内' in w for w in warnings))

    def test_binary_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'b.bin').write_bytes(b'\x00\x01\x02')
            _, notes, warnings = expand_mentions('@b.bin', str(root))
            self.assertEqual(notes, [])
            self.assertTrue(any('二进制' in w for w in warnings))

    def test_oversized_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / 'big.txt', 'x' * 200)
            _, notes, warnings = expand_mentions('@big.txt', str(root), max_bytes=100)
            self.assertEqual(notes, [])
            self.assertTrue(any('超过' in w for w in warnings))

    def test_duplicate_mention_only_attached_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _write(root / 'a.py', 'x = 1\n')
            text, notes, _ = expand_mentions('@a.py 和 @a.py', str(root))
            self.assertEqual(len(notes), 1)
            self.assertEqual(text.count('<file path="a.py">'), 1)

    def test_missing_file_warns_but_keeps_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            text, notes, warnings = expand_mentions('@nope.py 在吗', str(tmp))
            self.assertEqual(notes, [])
            self.assertIn('找不到', warnings[0])
            self.assertIn('@nope.py', text)


class GitHookTests(unittest.TestCase):
    def _repo(self, tmp: str) -> Path:
        repo = Path(tmp) / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True,
                       capture_output=True)
        return repo

    def test_build_hook_contains_paths_and_gate(self):
        script = build_hook(r'D:\python\python.exe', r'D:\tool\ascend_cli.py', 'high')
        self.assertTrue(script.startswith('#!/bin/sh'))
        self.assertIn(MARKER_START, script)
        self.assertIn('--fail-on high', script)
        self.assertIn('--staged', script)
        self.assertIn('--offline', script)
        self.assertNotIn('\r\n', script)

    def test_invalid_severity_rejected(self):
        with self.assertRaises(HookError):
            build_hook('python', 'cli.py', 'fatal')

    def test_install_update_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            path, action = install(str(repo), 'python', 'C:/tool/ascend_cli.py', 'high')
            self.assertEqual(action, 'created')
            self.assertTrue(path.exists())
            self.assertTrue(is_installed(str(repo)))

            _, action2 = install(str(repo), 'python', 'C:/tool/ascend_cli.py', 'medium')
            self.assertEqual(action2, 'updated')
            self.assertIn('--fail-on medium', path.read_text(encoding='utf-8'))

            _, action3 = remove(str(repo))
            self.assertEqual(action3, '已删除')
            self.assertFalse(path.exists())

    def test_foreign_hook_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            hook = Path(repo) / '.git/hooks/pre-commit'
            hook.parent.mkdir(parents=True, exist_ok=True)
            _write(hook, '#!/bin/sh\necho foreign\n')

            with self.assertRaises(HookError):
                install(str(repo), 'python', 'cli.py')
            with self.assertRaises(HookError):
                remove(str(repo))
            self.assertIn('foreign', hook.read_text(encoding='utf-8'))

    def test_force_backs_up_foreign_hook(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = self._repo(tmp)
            hook = Path(repo) / '.git/hooks/pre-commit'
            hook.parent.mkdir(parents=True, exist_ok=True)
            _write(hook, '#!/bin/sh\necho foreign\n')

            path, action = install(str(repo), 'python', 'cli.py', force=True)
            self.assertIn('备份', action)
            self.assertTrue(is_installed(str(repo)))
            backups = list(path.parent.glob('pre-commit.bak.*'))
            self.assertEqual(len(backups), 1)
            self.assertIn('foreign', backups[0].read_text(encoding='utf-8'))

    def test_not_a_git_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(HookError):
                install(tmp, 'python', 'cli.py')


class UsageMeterTests(unittest.TestCase):
    def test_estimate(self):
        self.assertEqual(estimate_tokens(''), 0)
        self.assertEqual(estimate_tokens('中文四个'), 4)
        self.assertEqual(estimate_tokens('abcdefgh'), 2)

    def test_accumulate_and_report(self):
        meter = UsageMeter()
        meter.record('你好', '世界')
        meter.record('abc', 'defg')
        self.assertEqual(meter.calls, 2)
        self.assertEqual(meter.total_tokens, meter.prompt_tokens + meter.reply_tokens)
        report = meter.report('deepseek-flash')
        self.assertIn('deepseek-flash', report)
        self.assertIn('调用次数：2', report)

    def test_empty_report_and_reset(self):
        meter = UsageMeter()
        self.assertIn('还没有调用模型', meter.report())
        meter.record('a', 'b')
        meter.reset()
        self.assertEqual(meter.calls, 0)


class AscendCliIntegrationTests(unittest.TestCase):
    def test_gate_exit_code(self):
        report = {'review_result': {'issues': [
            {'severity': 'high'}, {'severity': 'low'},
        ]}}
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ascend_cli._gate_exit_code(report, 'none'), 0)
            self.assertEqual(ascend_cli._gate_exit_code(report, 'medium'), 1)
            self.assertEqual(ascend_cli._gate_exit_code(report, 'critical'), 0)
            self.assertEqual(ascend_cli._gate_exit_code({}, 'high'), 0)
            self.assertEqual(ascend_cli._gate_exit_code({'review_result': {}}, 'high'), 0)

    def test_repo_root_prefers_desktop_selection(self):
        selected = str(Path.cwd() / 'demo-repo')

        class Agent:
            desktop_repository = selected
            work_root = Path.cwd()

        self.assertEqual(ascend_cli._agent_repo_root(Agent()), selected)

    def test_cost_command(self):
        class Agent:
            model_config = {'model': 'demo-model'}

        ascend_cli._USAGE.reset()
        ascend_cli._USAGE.record('问题', '回答')
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = ascend_cli.handle_chat_slash('/cost', Agent())
        self.assertEqual(result, 'handled')
        self.assertIn('demo-model', out.getvalue())
        self.assertIn('调用次数：1', out.getvalue())
        ascend_cli._USAGE.reset()

    def test_commands_command(self):
        class Agent:
            work_root = Path.cwd()

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = ascend_cli.handle_chat_slash('/commands', Agent())
        self.assertEqual(result, 'handled')
        self.assertIn('自定义命令', out.getvalue())

    def test_custom_command_runs_and_expands_file_mention(self):
        with tempfile.TemporaryDirectory() as tmp, _silence_home(Path(tmp)):
            root = Path(tmp)
            _write(root / '.reviewagent/commands/并发.md',
                   '请检查 @$ARGUMENTS 的并发安全\n')
            _write(root / 'src/a.py', 'shared = {}\n')

            class Agent:
                work_root = root

                def __init__(self):
                    self.prompts = []

                def answer(self, prompt):
                    self.prompts.append(prompt)
                    return '已检查'

            agent = Agent()
            out = io.StringIO()
            with contextlib.redirect_stdout(out), \
                    patch('ascend_cli.begin_think'), patch('ascend_cli.end_think'), \
                    patch('ascend_cli._print_agent_reply') as printed:
                result = ascend_cli.handle_chat_slash('/并发 src/a.py', agent)

            self.assertEqual(result, 'handled')
            self.assertEqual(len(agent.prompts), 1)
            self.assertIn('<file path="src/a.py">', agent.prompts[0])
            self.assertIn('并发安全', agent.prompts[0])
            printed.assert_called_once_with('已检查')

    def test_builtin_command_not_shadowed_by_custom(self):
        with tempfile.TemporaryDirectory() as tmp, _silence_home(Path(tmp)):
            root = Path(tmp)
            _write(root / '.reviewagent/commands/help.md', '我不应该抢 /help\n')

            class Agent:
                work_root = root

                def __init__(self):
                    self.calls = 0

                def answer(self, prompt):
                    self.calls += 1
                    return ''

            agent = Agent()
            with contextlib.redirect_stdout(io.StringIO()):
                ascend_cli.handle_chat_slash('/help', agent)
            self.assertEqual(agent.calls, 0, '内置 /help 被自定义命令抢占了')

    def test_install_hook_cmd(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True,
                           capture_output=True)
            args = argparse.Namespace(repo=str(repo), severity='high',
                                      force=False, remove=False)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ascend_cli.install_hook_cmd(args)
            self.assertEqual(code, 0)
            self.assertTrue(is_installed(str(repo)))

            args.remove = True
            with contextlib.redirect_stdout(io.StringIO()):
                code = ascend_cli.install_hook_cmd(args)
            self.assertEqual(code, 0)
            self.assertFalse(is_installed(str(repo)))


if __name__ == '__main__':
    unittest.main()

# -*- coding: utf-8 -*-
"""2026-11-12：审查前仓库概览 + Markdown 报告导出。

覆盖：
    · 概览三行（分支 / 改动数 / 未跟踪数）+ 未跟踪提示
    · --json 模式不打印概览
    · --report 生成 Markdown：总体结论、问题明细、知识库提示、无问题文案
    · --output 与 --report 同时使用，JSON 行为不变
    · 写入失败明确报错（退出码 1）
    · 中文 / 空格路径
    · 真实 Git 仓库端到端（离线，不联网）
    · 非 Git 目录仍按原逻辑报错、不崩
"""
from __future__ import annotations

import argparse
import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

import ascend_cli
from scripts.report_markdown import render_markdown, write_markdown

TOOL_DIR = Path(__file__).resolve().parents[1]
CLI = TOOL_DIR / 'ascend_cli.py'


def _report(issues=None, **overrides):
    data = {
        'status': 'complete',
        'task_identification': {'type': 'pr_review', 'subtypes': ['feature'], 'confidence': 0.92},
        'applied_standards': {'name': 'pr_review_feature', 'checklist': ['a']},
        'review_result': {
            'issues': issues if issues is not None else [{
                'severity': 'high',
                'type': 'bare except',
                'title': '裸 except 吞掉异常',
                'location': 'demo.py:5',
                'description': '发现 bare except',
                'suggestion': '使用 except Exception 代替',
            }],
            'overall_assessment': '发现 1 个高风险问题。',
            'recommendation': 'request_changes',
            'coverage': 'full',
        },
        'knowledge_retrieval': {
            'references': [{'title': '示例案例', 'url': 'https://example.com/1'}],
            'warnings': ['知识库数据缺失：demo.json'],
        },
        'metadata': {'repository': {'changed_files': ['demo.py']}},
    }
    data['review_result'].update(overrides.pop('review_result', {}))
    data.update(overrides)
    return data


def _context(tmp: Path, diff: str = '+x = 1\n', untracked=None):
    return {
        'root': str(tmp / 'demo-repo'),
        'branch': 'feature/x',
        'staged': False,
        'status': ' M demo.py',
        'changed_files': ['demo.py'],
        'diff': diff,
        'diff_truncated': False,
        'diff_total_chars': len(diff),
        'untracked_files': untracked if untracked is not None else ['new.txt'],
    }


def _args(**overrides):
    base = dict(
        staged=False, config=None, offline=True, output=None, report=None,
        json=False, max_diff=12000, require_full=False, scenario=None,
        require_scenario=False, fail_on='none',
    )
    base.update(overrides)
    return argparse.Namespace(**base)


class FakeSpecialist:
    status = 'skipped'
    reason = '无明确证据'
    question = ''
    text = ''

    def as_dict(self):
        return {'status': 'skipped', 'scenario': None, 'reason': self.reason, 'files': []}


class FakeReviewer:
    report: dict = _report()

    def __init__(self, *args, **kwargs):
        pass

    def review(self, *args, **kwargs):
        return copy.deepcopy(self.report)

    def print_report(self, report):
        pass


def _run_review(args, context, report=None):
    """在打桩环境里跑 review()，返回 (退出码, stdout, stderr)。"""
    fake = type('R', (FakeReviewer,), {'report': report or _report()})
    out, err = io.StringIO(), io.StringIO()
    with patch('ascend_cli.collect_repo_context', return_value=context), \
            patch('ascend_cli.resolve_specialist', return_value=FakeSpecialist()), \
            patch('ascend_cli.SmartReviewer', fake), \
            redirect_stdout(out), redirect_stderr(err):
        code = ascend_cli.review(args)
    return code, out.getvalue(), err.getvalue()


class RenderMarkdownTests(unittest.TestCase):
    def test_contains_required_sections(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = render_markdown(_report(), _context(Path(tmp)))
        for needle in ('# CodeVigil Agent 审查报告', 'demo-repo', 'feature/x',
                       '审查时间', '总体结论', '覆盖范围', '审查结论',
                       '问题（1）', '裸 except 吞掉异常', 'demo.py:5',
                       '发现 bare except', '使用 except Exception 代替',
                       '知识库提示', '知识库数据缺失：demo.json',
                       '参考案例', '示例案例'):
            self.assertIn(needle, text, needle)

    def test_no_issues_writes_explicit_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            text = render_markdown(_report(issues=[]), _context(Path(tmp)))
        self.assertIn('问题（0）', text)
        self.assertIn('未发现问题。', text)

    def test_partial_coverage_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(review_result={'coverage': 'partial',
                                            'coverage_note': 'diff 被截断'})
            text = render_markdown(report, _context(Path(tmp)))
        self.assertIn('部分（partial）', text)
        self.assertIn('diff 被截断', text)

    def test_error_report_is_not_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = _report(status='error', review_result={'error': '模型返回非 JSON'})
            text = render_markdown(report, _context(Path(tmp)))
        self.assertIn('审查失败', text)
        self.assertIn('模型返回非 JSON', text)

    def test_write_markdown_utf8_and_chinese_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / '中文 目录' / '报告 文件.md'
            written = write_markdown(target, '# 标题\n\n正文：中文\n')
            self.assertEqual(written, target)
            self.assertEqual(target.read_text(encoding='utf-8'), '# 标题\n\n正文：中文\n')

    def test_write_markdown_rejects_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(OSError):
                write_markdown(Path(tmp), 'x')


class ReviewOverviewTests(unittest.TestCase):
    def test_prints_three_lines_and_untracked_note(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = _run_review(_args(), _context(Path(tmp)))
        self.assertEqual(code, 0)
        self.assertIn('[REPO] 当前分支: feature/x', out)
        self.assertIn('[REPO] 改动文件: 1 个', out)
        self.assertIn('[REPO] 未跟踪文件: 1 个', out)
        self.assertIn('未跟踪文件不参与审查。', out)

    def test_no_untracked_note_when_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out, _ = _run_review(_args(), _context(Path(tmp), untracked=[]))
        self.assertIn('[REPO] 未跟踪文件: 0 个', out)
        self.assertNotIn('未跟踪文件不参与审查。', out)

    def test_json_mode_suppresses_overview(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out, _ = _run_review(_args(json=True), _context(Path(tmp)))
        self.assertEqual(code, 0)
        self.assertNotIn('[REPO]', out)
        json.loads(out)  # 仍是合法 JSON

    def test_overview_before_diff_short_circuit(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, out, _ = _run_review(_args(), _context(Path(tmp), diff=''))
        self.assertIn('[REPO] 当前分支: feature/x', out)
        self.assertIn('没有可审查的已跟踪文件 diff', out)


class ReportOptionTests(unittest.TestCase):
    def test_report_written_with_conclusion(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'report.md'
            code, out, err = _run_review(_args(report=str(target)), _context(Path(tmp)))
            self.assertEqual(code, 0)
            self.assertTrue(target.exists())
            text = target.read_text(encoding='utf-8')
        self.assertIn('总体结论', text)
        self.assertIn('发现 1 个高风险问题。', text)
        self.assertIn('裸 except 吞掉异常', text)
        self.assertIn('Markdown 报告已保存', err)
        self.assertIn('[REPO] 当前分支', out)

    def test_report_without_issues(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'clean.md'
            code, _, _ = _run_review(_args(report=str(target)),
                                     _context(Path(tmp)), report=_report(issues=[]))
            self.assertEqual(code, 0)
            self.assertIn('未发现问题。', target.read_text(encoding='utf-8'))

    def test_output_and_report_together(self):
        with tempfile.TemporaryDirectory() as tmp:
            json_path = Path(tmp) / 'report.json'
            md_path = Path(tmp) / 'report.md'
            code, _, _ = _run_review(
                _args(output=str(json_path), report=str(md_path)), _context(Path(tmp)))
            self.assertEqual(code, 0)
            payload = json.loads(json_path.read_text(encoding='utf-8'))
            self.assertEqual(payload['status'], 'complete')
            self.assertIn('总体结论', md_path.read_text(encoding='utf-8'))
            self.assertEqual(payload['review_result']['issues'][0]['severity'], 'high')

    def test_write_failure_is_explicit(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocker = Path(tmp) / 'blocker'
            blocker.write_text('not a directory', encoding='utf-8')
            code, _, err = _run_review(
                _args(report=str(blocker / 'report.md')), _context(Path(tmp)))
        self.assertEqual(code, 1)
        self.assertIn('无法写入 Markdown 报告', err)

    def test_no_diff_does_not_write_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'report.md'
            code, out, _ = _run_review(
                _args(report=str(target)), _context(Path(tmp), diff=''))
            self.assertEqual(code, 0)
            self.assertFalse(target.exists())
            self.assertIn('未生成 Markdown 报告', out)


class RealRepoEndToEndTests(unittest.TestCase):
    """真实仓库跑一次（离线，不联网），验证验收场景。"""

    def _git(self, repo: Path, *args):
        return subprocess.run(['git', '-C', str(repo), *args],
                              capture_output=True, text=True, encoding='utf-8',
                              errors='replace')

    def test_offline_review_with_report_in_chinese_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / '仓库 带空格'
            repo.mkdir()
            self._git(repo, 'init', '-q')
            self._git(repo, 'config', 'user.email', 'demo@example.com')
            self._git(repo, 'config', 'user.name', 'Demo')

            source = repo / 'demo.py'
            source.write_text('def add(a, b):\n    return a + b\n', encoding='utf-8')
            self._git(repo, 'add', 'demo.py')
            self._git(repo, 'commit', '-q', '-m', 'init')

            source.write_text(
                'def add(a, b):\n    return a + b\n\n\ndef load():\n'
                '    try:\n        return open("x")\n    except:\n        return None\n',
                encoding='utf-8')

            env = dict(os.environ, PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
            proc = subprocess.run(
                [sys.executable, str(CLI), 'review', '--offline',
                 '--report', 'report.md'],
                cwd=str(repo), capture_output=True, text=True,
                encoding='utf-8', errors='replace', env=env, timeout=180,
            )
            output = (proc.stdout or '') + (proc.stderr or '')

            self.assertEqual(proc.returncode, 0, output[-1500:])
            self.assertIn('[REPO] 当前分支:', output)
            self.assertIn('[REPO] 改动文件: 1 个', output)

            report = repo / 'report.md'
            self.assertTrue(report.exists())
            text = report.read_text(encoding='utf-8')
            self.assertIn('总体结论', text)
            self.assertIn('仓库 带空格', text)

    def test_non_git_directory_still_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            proc = subprocess.run(
                [sys.executable, str(CLI), 'review', '--offline'],
                cwd=tmp, capture_output=True, text=True,
                encoding='utf-8', errors='replace', timeout=60,
            )
            output = (proc.stdout or '') + (proc.stderr or '')
            self.assertEqual(proc.returncode, 1, output[-800:])
            self.assertIn('不是 Git 仓库', output)
            self.assertNotIn('Traceback', output)


if __name__ == '__main__':
    unittest.main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三个崩溃点的回归测试（2026-11-10）。

修的是：
1. bin/ui-colors.js 在没有 chalk 的环境里 c.brand 变成字符串，调用即崩；
2. chat_v2.py 的 intent == 'fetch_url' 分支用了不存在的变量 entities；
3. 同上分支调用的 handle_fetch_and_review 方法根本不存在。

这里只做静态 + 单元级验证，不联网、不启动交互界面。
"""
import ast
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / 'chat_v2.py'


def _cls_methods(path, cls_name):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            return {f.name for f in node.body if isinstance(f, ast.FunctionDef)}
    return set()


class TestUiColorsFallback(unittest.TestCase):
    """chalk 缺失时必须降级成恒等函数，而不是崩。"""

    def setUp(self):
        if not shutil.which('node'):
            self.skipTest('没有 node，跳过')

    def _run_node(self, script):
        return subprocess.run(
            ['node', '-e', script],
            cwd=str(ROOT), capture_output=True, text=True, timeout=60,
        )

    def test_all_colors_callable_on_real_chalk(self):
        script = r'''
        const {c} = require('./bin/ui-colors');
        let bad = [];
        for (const k of Object.keys(c)) {
          if (typeof c[k] !== 'function') { bad.push(k + ':not-a-function'); continue; }
          if (c[k]('x') !== 'x' && !c[k]('x').includes('x')) bad.push(k + ':bad-output');
        }
        console.log(bad.length ? 'BAD:' + bad.join(',') : 'OK');
        '''
        r = self._run_node(script)
        self.assertIn('OK', r.stdout, r.stdout + r.stderr)

    def test_all_colors_callable_without_chalk(self):
        """把 require('chalk') 强制变成抛错，模拟 ESM-only 的情况。"""
        script = r'''
        const Module = require('module');
        const orig = Module._load;
        Module._load = function (req) {
          if (req === 'chalk') { const e = new Error('ERR_REQUIRE_ESM'); e.code = 'ERR_REQUIRE_ESM'; throw e; }
          return orig.apply(this, arguments);
        };
        const {c} = require('./bin/ui-colors');
        let bad = [];
        for (const k of Object.keys(c)) {
          if (typeof c[k] !== 'function') { bad.push(k + ':not-a-function'); continue; }
          if (c[k]('降级') !== '降级') bad.push(k + ':changed-text');
        }
        console.log(bad.length ? 'BAD:' + bad.join(',') : 'OK');
        '''
        r = self._run_node(script)
        self.assertIn('OK', r.stdout, r.stdout + r.stderr)


class TestFetchUrlBranch(unittest.TestCase):
    """fetch_url 分支不能再引用未定义变量 / 未定义方法。"""

    def test_no_undefined_entities_variable(self):
        """用 AST 找真正被引用的变量名 entities（注释里提到不算）。"""
        tree = ast.parse(CHAT.read_text(encoding='utf-8'))
        used = [n for n in ast.walk(tree)
                if isinstance(n, ast.Name) and n.id == 'entities']
        self.assertEqual(used, [], f'仍有 {len(used)} 处引用了未定义的 entities 变量')

    def test_handler_method_exists(self):
        methods = _cls_methods(CHAT, 'ReviewAgentChat')
        self.assertIn('handle_fetch_and_review', methods)

    def test_dispatch_passes_urls_from_intent_result(self):
        src = CHAT.read_text(encoding='utf-8')
        self.assertRegex(
            src,
            r"handle_fetch_and_review\(\s*intent_result\.get\('urls'\)",
            '分发处应把 intent_result 里的 urls 传给 handler',
        )

    def test_fetcher_uses_universal_fetcher(self):
        src = CHAT.read_text(encoding='utf-8')
        self.assertNotIn('GitHubFetcher(', src,
                         'GitHubFetcher 类不存在，会 NameError')
        self.assertIn('UniversalFetcher(github_token=', src)

    def test_understand_intent_returns_urls_key(self):
        """确认 handler 取的 key 和 understand_intent 给的 key 对得上。"""
        src = CHAT.read_text(encoding='utf-8')
        self.assertIn("'intent': 'fetch_url', 'urls':", src)

    def test_no_syntax_errors(self):
        ast.parse(CHAT.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

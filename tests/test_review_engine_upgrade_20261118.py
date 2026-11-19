"""2026-11-18 自审计后的审查引擎升级回归测试。

对应审计报告优化清单（03_产出/2026-11-18-CodeVigilAgent自我审计与能力升级评估.md）：
1. #3 规则引擎全量命中（旧版 first_match 每规则只报首个命中）
2. #4 字符串字面量防误报（子进程命令串里的 print 不再命中）
3. #2/#12 review_with_ai 自适应 max_tokens + 截断后有界重试一次
4. #5 /fix from-review 数据桥（本地审查报告 → 补丁 payload）
5. #6 /undo 回滚（apply → undo 逐字节还原、冲突拒绝、create 撤销）
"""
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.patch_fix import (  # noqa: E402
    FileEdit,
    ProposedFix,
    apply_fix,
    apply_undo_bundle,
    capture_undo_bundle,
    finalize_undo_bundle,
)
from scripts.smart_reviewer import SmartReviewer  # noqa: E402
from scripts.rule_engine import _in_string_literal  # noqa: E402


def _rules_reviewer():
    """review_with_rules 不依赖实例状态；绕过 __init__ 避免读配置/知识库。"""
    return SmartReviewer.__new__(SmartReviewer)


class RuleAllMatchesTests(unittest.TestCase):
    """#3：每条规则报全部命中（上限 10），逐处给 location。"""

    def test_three_bare_excepts_reported(self):
        reviewer = _rules_reviewer()
        added = [
            ('a.py', 1, 'try:'),
            ('a.py', 2, '    run()'),
            ('a.py', 3, 'except:'),
            ('a.py', 10, 'except:'),
            ('b.py', 7, 'except:'),
        ]
        result = reviewer.review_with_rules('\n'.join(t for _, _, t in added),
                                            {'type': 'pr_review', 'subtypes': []},
                                            {'checklist': [], 'critical_points': []},
                                            added=added)
        bare = [i for i in result['issues'] if i['type'] == 'bare except']
        self.assertEqual(len(bare), 3)
        self.assertEqual({i['location'] for i in bare},
                         {'a.py:3', 'a.py:10', 'b.py:7'})

    def test_matches_capped_per_rule(self):
        reviewer = _rules_reviewer()
        added = [('a.py', i, f'print({i})') for i in range(1, 16)]
        result = reviewer.review_with_rules('\n'.join(t for _, _, t in added),
                                            {'type': 'pr_review', 'subtypes': []},
                                            {'checklist': [], 'critical_points': []},
                                            added=added)
        prints = [i for i in result['issues'] if i['type'] == 'debug print']
        self.assertEqual(len(prints), 10)   # 每规则上限 10，防输出爆炸

    def test_deleted_lines_not_reported(self):
        """规则只看新增行：旧版语义保持不变。"""
        reviewer = _rules_reviewer()
        result = reviewer.review_with_rules('-except:\n+value = 1\n',
                                            {'type': 'pr_review', 'subtypes': []},
                                            {'checklist': [], 'critical_points': []},
                                            added=[('a.py', 5, '+value = 1')])
        self.assertEqual(result['issues'], [])


class StringLiteralMaskTests(unittest.TestCase):
    """#4：字符串字面量里的代码不再被规则命中。"""

    def test_in_string_literal_unit(self):
        self.assertTrue(_in_string_literal("PARENT = (\"print('hi')\")", 16))
        self.assertFalse(_in_string_literal('print("hello")', 0))
        self.assertFalse(_in_string_literal('value = "a" + f(b)', 12))
        # 引号已闭合，后面的命中不算字面量
        self.assertFalse(_in_string_literal('x = "y" ; print(1)', 11))

    def test_subprocess_code_string_not_flagged(self):
        """2026-11-18 自审计实测的误报场景：子进程命令串里的 print。"""
        reviewer = _rules_reviewer()
        added = [('tests/test_x.py', 25,
                  '         "print(\'started\',flush=True); threading.Event().wait(30)")')]
        result = reviewer.review_with_rules('\n'.join(t for _, _, t in added),
                                            {'type': 'pr_review', 'subtypes': []},
                                            {'checklist': [], 'critical_points': []},
                                            added=added)
        self.assertEqual([i for i in result['issues'] if i['type'] == 'debug print'], [])

    def test_real_print_still_flagged(self):
        reviewer = _rules_reviewer()
        added = [('a.py', 3, 'print("real debug")')]
        result = reviewer.review_with_rules('\n'.join(t for _, _, t in added),
                                            {'type': 'pr_review', 'subtypes': []},
                                            {'checklist': [], 'critical_points': []},
                                            added=added)
        self.assertEqual(len([i for i in result['issues'] if i['type'] == 'debug print']), 1)


class FakeAI:
    """假 AI client：按序吐预设回复，记录每次调用参数。"""

    def __init__(self, responses, hint=''):
        self.responses = list(responses)
        self.calls = []
        self._hint = hint

    def chat(self, prompt, system_prompt=None, **kwargs):
        self.calls.append(kwargs)
        return self.responses.pop(0)

    def truncation_hint(self):
        return self._hint


VALID_REVIEW_JSON = json.dumps({
    'issues': [], 'overall_assessment': 'no issues', 'recommendation': 'comment',
})
EMPTY_BODY_NOTE = '（正文为空：max_tokens 被推理过程用掉了 16000 tokens。把 max_tokens 调大。）'


class AdaptiveTokensTests(unittest.TestCase):
    """#2：max_tokens 随内容长度自适应。"""

    def _reviewer_with(self, ai):
        reviewer = SmartReviewer.__new__(SmartReviewer)
        reviewer.ai_client = ai
        reviewer.has_ai = True
        return reviewer

    def test_tokens_scale_with_content(self):
        ai = FakeAI([VALID_REVIEW_JSON])
        self._reviewer_with(ai).review_with_ai(
            'x' * 40000,
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[])
        self.assertEqual(ai.calls[0]['max_tokens'], 16000 + 40000 // 4)   # 26000

    def test_tokens_capped_at_32000(self):
        ai = FakeAI([VALID_REVIEW_JSON])
        self._reviewer_with(ai).review_with_ai(
            'x' * 200000,
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[])
        self.assertEqual(ai.calls[0]['max_tokens'], 32000)

    def test_small_content_keeps_floor(self):
        ai = FakeAI([VALID_REVIEW_JSON])
        self._reviewer_with(ai).review_with_ai(
            'diff --git a/x b/x\n+1\n',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[])
        self.assertGreaterEqual(ai.calls[0]['max_tokens'], 16000)   # 下限不低于旧值
        self.assertLess(ai.calls[0]['max_tokens'], 16100)           # 小 diff 不放卫星


class BoundedRetryTests(unittest.TestCase):
    """#12：截断类失败有界重试一次；非截断失败立即返回。"""

    def _reviewer_with(self, ai):
        reviewer = SmartReviewer.__new__(SmartReviewer)
        reviewer.ai_client = ai
        reviewer.has_ai = True
        return reviewer

    def test_retry_once_on_empty_body_then_success(self):
        ai = FakeAI([EMPTY_BODY_NOTE, VALID_REVIEW_JSON])
        result = self._reviewer_with(ai).review_with_ai(
            'diff --git a/x b/x\n+1\n',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[{'title': 'case', 'url': 'https://example.test/1'}])
        self.assertNotIn('error', result)
        self.assertEqual(len(ai.calls), 2)
        self.assertGreater(ai.calls[1]['max_tokens'], ai.calls[0]['max_tokens'])
        self.assertIn('第 2 次', result.get('note', ''))
        # 第二次重试不再携带历史案例（精简输入）
        self.assertIsNone(result.get('references'))

    def test_two_failures_return_truncation_error(self):
        ai = FakeAI([EMPTY_BODY_NOTE, EMPTY_BODY_NOTE])
        result = self._reviewer_with(ai).review_with_ai(
            'diff --git a/x b/x\n+1\n',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[])
        self.assertIn('error', result)
        self.assertTrue(result.get('truncated'))
        self.assertEqual(len(ai.calls), 2)   # 有界：绝不第三次

    def test_http_error_no_retry(self):
        ai = FakeAI(['Error: HTTP 401 Unauthorized — Incorrect API key'])
        result = self._reviewer_with(ai).review_with_ai(
            'diff --git a/x b/x\n+1\n',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[])
        self.assertIn('AI 调用失败', result['error'])
        self.assertEqual(len(ai.calls), 1)   # 鉴权失败不值得重试

    def test_half_json_with_hint_retries(self):
        ai = FakeAI(['{"issues": [{"id": "1"', VALID_REVIEW_JSON],
                     hint='（回复被 max_tokens 截断，请调大 max_tokens。）')
        result = self._reviewer_with(ai).review_with_ai(
            'diff --git a/x b/x\n+1\n',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[])
        self.assertNotIn('error', result)
        self.assertEqual(len(ai.calls), 2)


class FixFromReviewTests(unittest.TestCase):
    """#5：/fix from-review 数据桥。"""

    class FixClient:
        def __init__(self, reply=None):
            self.payloads = []
            self.reply = reply or json.dumps({
                'scenario': 'general', 'summary': 'fix from review',
                'files': [{'path': 'demo.py', 'action': 'replace',
                           'search': 'old', 'replace': 'new'}],
            })

        def chat(self, prompt, system_prompt=None, **kwargs):
            self.payloads.append(json.loads(prompt))
            return self.reply

    class FakeKnowledge:
        warnings = []

        def search(self, query, limit=3):
            return []

    class FakeFetcher:
        def fetch_url(self, url):
            return {}

    def _agent(self, client):
        from scripts.conversation_agent import ConversationAgent
        agent = ConversationAgent(client, self.FakeKnowledge(), self.FakeFetcher())
        agent.work_root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, agent.work_root, ignore_errors=True)
        return agent

    def _report(self):
        return {
            'review_result': {
                'issues': [{
                    'severity': 'low', 'type': 'style', 'title': '用 old 常量',
                    'description': 'old 应换成 new', 'location': 'demo.py:1',
                    'suggestion': '把 old 替换为 new',
                }],
                'overall_assessment': '一个小问题', 'recommendation': 'comment',
            },
            'metadata': {'source': 'chat-/review', 'repository': {
                'root': '/tmp/repo', 'branch': 'main',
                'diff': 'diff --git a/demo.py b/demo.py\n+old\n',
                'changed_files': ['demo.py'],
            }},
        }

    def test_no_report_fails_cleanly(self):
        agent = self._agent(self.FixClient())
        reply = agent.propose_fix(from_review=True)
        self.assertIn('没有可用的本地审查结果', reply)
        self.assertFalse(agent.last_ok)

    def test_bridge_builds_payload_from_report(self):
        client = self.FixClient()
        agent = self._agent(client)
        agent.last_review_report = self._report()
        (agent.work_root / 'demo.py').write_text('value = old\n', encoding='utf-8')
        reply = agent.propose_fix(from_review=True)
        self.assertTrue(agent.last_ok, reply)
        self.assertIn('demo.py', reply)
        self.assertEqual(len(client.payloads), 1)
        payload = client.payloads[0]
        self.assertIn('review_issues', payload)
        self.assertNotIn('active_pr_issues', payload)
        self.assertEqual(payload['review_issues'][0]['location'], 'demo.py:1')
        self.assertEqual(payload['changed_files'], ['demo.py'])
        self.assertEqual(payload['scenario'], 'general')
        self.assertTrue(agent.pending_fix and agent.pending_fix.files)

    def test_report_without_issues_fails_cleanly(self):
        agent = self._agent(self.FixClient())
        report = self._report()
        report['review_result']['issues'] = []
        agent.last_review_report = report
        reply = agent.propose_fix(from_review=True)
        self.assertIn('没有可用的本地审查结果', reply)

    def test_web_context_path_unchanged(self):
        """不带 from_review 时维持旧行为：要求网页 PR/Issue 上下文。"""
        agent = self._agent(self.FixClient())
        reply = agent.propose_fix(from_review=False)
        self.assertIn('PR/Issue', reply)
        self.assertFalse(agent.last_ok)


class UndoBundleTests(unittest.TestCase):
    """#6：/undo 回滚（内存快照方案）。"""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        (self.root / 'demo.py').write_text('value = old\n', encoding='utf-8')

    def _apply(self, search='old', replace='new'):
        fix = ProposedFix(files=[FileEdit('demo.py', 'replace', search, replace)])
        bundle = capture_undo_bundle(fix, self.root)
        result = apply_fix(fix, root=self.root)
        self.assertTrue(result['ok'], result)
        return finalize_undo_bundle(bundle, fix, self.root)

    def test_roundtrip_restores_bytes(self):
        bundle = self._apply()
        self.assertEqual((self.root / 'demo.py').read_text(encoding='utf-8'),
                         'value = new\n')
        result = apply_undo_bundle(bundle, root=self.root)
        self.assertTrue(result['ok'], result)
        self.assertEqual((self.root / 'demo.py').read_text(encoding='utf-8'),
                         'value = old\n')
        self.assertEqual(result['results'][0]['status'], 'replaced')

    def test_conflict_when_file_changed_after_apply(self):
        bundle = self._apply()
        (self.root / 'demo.py').write_text('value = newer\n', encoding='utf-8')
        result = apply_undo_bundle(bundle, root=self.root)
        self.assertFalse(result['ok'])
        self.assertIn('回滚验证失败', result['error'])
        self.assertIn('拒绝回滚', result['results'][0]['error'])
        self.assertEqual(result['results'][0]['status'], 'rejected')
        self.assertEqual((self.root / 'demo.py').read_text(encoding='utf-8'),
                         'value = newer\n')   # 不碰被再次修改的文件

    def test_create_action_undone_by_delete(self):
        fix = ProposedFix(files=[FileEdit('made.py', 'create', '', 'x = 1\n')])
        bundle = capture_undo_bundle(fix, self.root)
        result = apply_fix(fix, root=self.root)
        self.assertTrue(result['ok'], result)
        bundle = finalize_undo_bundle(bundle, fix, self.root)
        self.assertTrue((self.root / 'made.py').exists())
        undo = apply_undo_bundle(bundle, root=self.root)
        self.assertTrue(undo['ok'], undo)
        self.assertFalse((self.root / 'made.py').exists())
        self.assertEqual(undo['results'][0]['status'], 'deleted')

    def test_empty_bundle_reports_error(self):
        result = apply_undo_bundle(None, root=self.root)
        self.assertFalse(result['ok'])
        self.assertIn('没有可回滚', result['error'])


if __name__ == '__main__':
    unittest.main()

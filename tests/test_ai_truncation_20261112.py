"""覆盖「AI 回复被 max_tokens 截断」这条链路。

背景（2026-11-12 实测）：deepseek-flash 是推理模型，一次审查光思考就吃掉
3000~6000 tokens。max_tokens 给 3000 时正文是空字符串，给 8000 时 JSON 写到
一半就断，界面只报「无法作为有效审查结果: Unterminated string」——用户完全
看不出真正原因。这里锁住"能识别截断并给出可操作建议"。
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts import ai_adapter  # noqa: E402


def make_result(content, finish_reason, reasoning_tokens=0):
    usage = {'completion_tokens': 100}
    if reasoning_tokens:
        usage['completion_tokens_details'] = {'reasoning_tokens': reasoning_tokens}
    return {
        'choices': [{'message': {'content': content}, 'finish_reason': finish_reason}],
        'usage': usage,
    }


class ExtractContentTest(unittest.TestCase):
    def setUp(self):
        ai_adapter._LAST_FINISH['reason'] = None
        ai_adapter._LAST_FINISH['reasoning_tokens'] = 0

    def test_normal_reply_is_returned_as_is(self):
        text = ai_adapter._extract_content(make_result('{"issues": []}', 'stop'))
        self.assertEqual(text, '{"issues": []}')
        self.assertEqual(ai_adapter._LAST_FINISH['reason'], 'stop')

    def test_truncated_reply_still_returns_partial_text(self):
        """正文非空但被截断：内容照旧返回（上层要拿它做判断），状态里留下 length。"""
        partial = '{"issues": [{"id": "1", "title": "没写完'
        text = ai_adapter._extract_content(make_result(partial, 'length'))
        self.assertEqual(text, partial)
        self.assertEqual(ai_adapter._LAST_FINISH['reason'], 'length')

    def test_empty_body_with_reasoning_reports_tokens(self):
        text = ai_adapter._extract_content(make_result('', 'length', reasoning_tokens=3000))
        self.assertIn('3000', text)
        self.assertIn('max_tokens', text)

    def test_empty_body_without_reasoning_reports_plain_truncation(self):
        text = ai_adapter._extract_content(make_result('', 'length'))
        self.assertIn('截断', text)


class TruncationHintTest(unittest.TestCase):
    def setUp(self):
        ai_adapter._LAST_FINISH['reason'] = None
        ai_adapter._LAST_FINISH['reasoning_tokens'] = 0
        self.client = ai_adapter.AIClient('deepseek', 'fake-key-for-test', 'fake-model')

    def test_no_hint_when_finished_normally(self):
        self.client._sync_finish_state()
        self.assertEqual(self.client.truncation_hint(), '')

    def test_hint_mentions_reasoning_tokens(self):
        ai_adapter._LAST_FINISH['reason'] = 'length'
        ai_adapter._LAST_FINISH['reasoning_tokens'] = 3503
        self.client._sync_finish_state()
        hint = self.client.truncation_hint()
        self.assertIn('3503', hint)
        self.assertIn('推理', hint)

    def test_hint_without_reasoning_tokens(self):
        ai_adapter._LAST_FINISH['reason'] = 'length'
        ai_adapter._LAST_FINISH['reasoning_tokens'] = 0
        self.client._sync_finish_state()
        hint = self.client.truncation_hint()
        self.assertIn('max_tokens', hint)
        self.assertNotIn('推理过程', hint)

    def test_chat_syncs_finish_state(self):
        """chat() 结束后状态要自动同步，调用方不用手动 _sync。"""
        self.client.provider.chat = mock.Mock(
            side_effect=lambda messages, **kw: self._reply())
        self.client.chat('hi')
        self.assertEqual(self.client.last_finish_reason, 'length')
        self.assertEqual(self.client.last_reasoning_tokens, 4000)
        self.assertTrue(self.client.truncation_hint())

    @staticmethod
    def _reply():
        # 模拟 provider：先让 _extract_content 记录状态，再返回正文
        ai_adapter._extract_content(make_result('cut...', 'length', reasoning_tokens=4000))
        return 'cut...'


class ReviewerErrorTest(unittest.TestCase):
    """截断导致的 JSON 解析失败，错误信息里要带上建议。"""

    def test_error_message_includes_truncation_hint(self):
        from scripts.smart_reviewer import SmartReviewer

        reviewer = SmartReviewer.__new__(SmartReviewer)   # 不走 __init__，避免读配置
        reviewer.ai_client = ai_adapter.AIClient('deepseek', 'fake-key-for-test', 'fake-model')
        reviewer.ai_client.provider.chat = mock.Mock(
            side_effect=lambda messages, **kw: '{"issues": [{"id": "1"')
        reviewer.has_ai = True

        result = reviewer.review_with_ai(
            'diff --git a/x b/x',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[],
            specialist_text='',
        )
        self.assertIn('error', result)
        self.assertIn('无法作为有效审查结果', result['error'])
        self.assertIn('max_tokens', result['error'])
        self.assertTrue(result.get('truncated'))


class NonJsonReplyTest(unittest.TestCase):
    """适配层的说明文字不能被当成 JSON 解析。"""

    def test_empty_reply(self):
        from scripts.ai_adapter import non_json_reply
        self.assertIn('空内容', non_json_reply(''))

    def test_http_error_reply(self):
        from scripts.ai_adapter import non_json_reply
        msg = non_json_reply('Error: HTTP 401 Unauthorized — Incorrect API key')
        self.assertIn('AI 调用失败', msg)
        self.assertIn('401', msg)

    def test_empty_body_hint_reply(self):
        from scripts.ai_adapter import non_json_reply
        msg = non_json_reply('（正文为空：max_tokens 被推理过程用掉了 16000 tokens。把 max_tokens 调大。）')
        self.assertIn('没有返回可解析的内容', msg)

    def test_real_json_is_not_flagged(self):
        from scripts.ai_adapter import non_json_reply
        self.assertEqual(non_json_reply('{"issues": []}'), '')
        self.assertEqual(non_json_reply('```json\n{"issues": []}\n```'), '')

    def test_reviewer_reports_readable_reason(self):
        """整条链路：AI 返回中文说明 → 错误信息要带上这句说明。"""
        from scripts.smart_reviewer import SmartReviewer

        reviewer = SmartReviewer.__new__(SmartReviewer)
        reviewer.ai_client = ai_adapter.AIClient('deepseek', 'fake-key-for-test', 'fake-model')
        reviewer.ai_client.provider.chat = mock.Mock(
            side_effect=lambda messages, **kw: '（正文为空：max_tokens 被推理过程用掉了 16000 tokens。）')
        reviewer.has_ai = True

        result = reviewer.review_with_ai(
            'diff --git a/x b/x',
            {'type': 'pr_review', 'subtypes': []},
            {'checklist': [], 'critical_points': []},
            references=[],
            specialist_text='',
        )
        self.assertIn('正文为空', result['error'])
        self.assertNotIn('Expecting value', result['error'])
        self.assertTrue(result['truncated'])


if __name__ == '__main__':
    unittest.main()

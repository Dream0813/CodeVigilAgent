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
from scripts.repo_context import RepoContextError


class FakeKnowledge:
    warnings = []
    documents = []

    def search(self, query, limit=3):
        return []


class FakeModel:
    def __init__(self):
        self.calls = []

    def chat_with_history(self, messages, **kwargs):
        self.calls.append(messages)
        return f"fake reply {len(self.calls)}"


class DesktopChatTests(unittest.TestCase):
    def test_named_session_keeps_fake_model_history_and_new_session_isolated(self):
        with tempfile.TemporaryDirectory() as home:
            model = FakeModel()
            sessions = Path(home) / 'sessions'
            sessions.mkdir()
            latest = sessions / 'latest.json'
            latest.write_text('preserve existing latest session', encoding='utf-8')

            def send(session, message):
                output = io.StringIO()
                argv = ['ascend_cli.py', 'chat', '--message', message, '--session', session,
                        '--network', 'off', '--json']
                with patch.dict(os.environ, {'REVIEWAGENT_HOME': home}), \
                        patch('scripts.conversation_agent.KnowledgeSearch', return_value=FakeKnowledge()), \
                        patch.object(ascend_cli, 'get_ai_client', return_value=model), \
                        patch('sys.argv', argv), contextlib.redirect_stdout(output):
                    status = ascend_cli.main()
                return status, json.loads(output.getvalue())

            self.assertEqual(send('desktop-test', 'first question')[0], 0)
            self.assertEqual(latest.read_text(encoding='utf-8'), 'preserve existing latest session')
            self.assertEqual(send('desktop-test', 'follow up')[0], 0)
            second_messages = model.calls[1]
            self.assertTrue(any(m['role'] == 'user' and 'first question' in m['content']
                                for m in second_messages))
            self.assertTrue(any(m['role'] == 'assistant' and m['content'] == 'fake reply 1'
                                for m in second_messages))

            self.assertEqual(send('desktop-new', 'fresh question')[0], 0)
            fresh_messages = model.calls[2]
            self.assertFalse(any('first question' in m.get('content', '') for m in fresh_messages))

    def test_json_chat_failure_is_nonzero_and_never_prints_api_key(self):
        class FailedModel:
            provider = type('Provider', (), {'api_key': 'secret-test-key'})()

            def chat_with_history(self, messages, **kwargs):
                return 'Error: secret-test-key rejected'

        with tempfile.TemporaryDirectory() as home:
            output = io.StringIO()
            argv = ['ascend_cli.py', 'chat', '--message', 'hello', '--json']
            with patch.dict(os.environ, {'REVIEWAGENT_HOME': home}), \
                    patch('scripts.conversation_agent.KnowledgeSearch', return_value=FakeKnowledge()), \
                    patch.object(ascend_cli, 'get_ai_client', return_value=FailedModel()), \
                    patch('sys.argv', argv), contextlib.redirect_stdout(output):
                status = ascend_cli.main()
            payload = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertFalse(payload['ok'])
        self.assertNotIn('secret-test-key', output.getvalue())


class DesktopReviewTests(unittest.TestCase):
    def run_review(self, context=None, error=None):
        args = argparse.Namespace(staged=False, max_diff=12000, json=True, require_full=False,
                                  scenario=None, require_scenario=False, config=None, output=None,
                                  offline=True)
        output = io.StringIO()
        patcher = (patch.object(ascend_cli, 'collect_repo_context', side_effect=error) if error else
                   patch.object(ascend_cli, 'collect_repo_context', return_value=context))
        with patcher, contextlib.redirect_stdout(output):
            status = ascend_cli.review(args)
        return status, json.loads(output.getvalue())

    def test_empty_diff_is_structured_and_does_not_claim_review_passed(self):
        status, payload = self.run_review({'diff': '  ', 'diff_truncated': False,
                                           'changed_files': [], 'diff_total_chars': 0})
        self.assertEqual(status, 0)
        self.assertEqual(payload['status'], 'no_changes')
        self.assertEqual(payload['review_result']['issues'], [])
        self.assertIn('没有可审查', payload['message'])

    def test_repository_error_is_json_and_nonzero(self):
        status, payload = self.run_review(error=RepoContextError('not a git repository'))
        self.assertEqual(status, 1)
        self.assertEqual(payload['status'], 'error')
        self.assertIn('not a git repository', payload['error'])

    def test_invalid_model_report_is_tagged_error_and_nonzero(self):
        class BrokenReviewer:
            def __init__(self, *args, **kwargs):
                pass

            def review(self, *args, **kwargs):
                return {'review_result': {'error': 'AI returned invalid JSON'}}

        args = argparse.Namespace(staged=False, max_diff=12000, json=True, require_full=False,
                                  scenario=None, require_scenario=False, config=None, output=None,
                                  offline=True)
        context = {'diff': 'diff --git a/a b/a\n+bad', 'diff_truncated': False,
                   'changed_files': ['a'], 'diff_total_chars': 20, 'root': '.',
                   'branch': 'test', 'status': '', 'staged': False}
        output = io.StringIO()
        with patch.object(ascend_cli, 'collect_repo_context', return_value=context), \
                patch.object(ascend_cli, 'SmartReviewer', BrokenReviewer), \
                contextlib.redirect_stdout(output):
            status = ascend_cli.review(args)
        self.assertEqual(status, 1)
        self.assertEqual(json.loads(output.getvalue())['status'], 'error')

    def test_incomplete_report_is_error_and_nonzero(self):
        class IncompleteReviewer:
            def __init__(self, *args, **kwargs):
                pass

            def review(self, *args, **kwargs):
                return {'review_result': {'issues': [], 'overall_assessment': 'incomplete',
                                          'recommendation': 'comment', 'coverage': 'full'}}

        args = argparse.Namespace(staged=False, max_diff=12000, json=True, require_full=False,
                                  scenario=None, require_scenario=False, config=None, output=None,
                                  offline=True)
        context = {'diff': 'diff --git a/a b/a\n+bad', 'diff_truncated': False,
                   'changed_files': ['a'], 'diff_total_chars': 20, 'root': '.',
                   'branch': 'test', 'status': '', 'staged': False}
        output = io.StringIO()
        with patch.object(ascend_cli, 'collect_repo_context', return_value=context), \
                patch.object(ascend_cli, 'SmartReviewer', IncompleteReviewer), \
                contextlib.redirect_stdout(output):
            status = ascend_cli.review(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(payload['status'], 'error')
        self.assertIn('knowledge_retrieval', payload['error'])


if __name__ == '__main__':
    unittest.main()

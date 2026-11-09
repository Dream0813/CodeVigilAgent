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
    provider = type('Provider', (), {'api_key': 'fake-secret-value-123456789'})()

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

    def test_history_crud_search_export_and_secret_redaction(self):
        from scripts.session_store import delete_session, list_sessions, load_session, rename_session, session_markdown
        from scripts.conversation_agent import ConversationAgent

        with tempfile.TemporaryDirectory() as home:
            model = FakeModel()
            latest = Path(home) / 'sessions' / 'latest.json'
            latest.parent.mkdir(parents=True)
            latest.write_text('legacy alias remains untouched', encoding='utf-8')
            argv = ['ascend_cli.py', 'chat', '--message',
                    'Discuss fake-secret-value-123456789 and history search', '--session', 'desktop-history',
                    '--network', 'off', '--json']
            with patch.dict(os.environ, {'REVIEWAGENT_HOME': home}), \
                    patch('scripts.conversation_agent.KnowledgeSearch', return_value=FakeKnowledge()), \
                    patch.object(ascend_cli, 'get_ai_client', return_value=model), \
                    patch('sys.argv', argv), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(ascend_cli.main(), 0)

            path = Path(home) / 'sessions' / 'desktop-history.json'
            with patch.dict(os.environ, {'REVIEWAGENT_HOME': home}):
                stored = path.read_text(encoding='utf-8')
                self.assertNotIn('fake-secret-value-123456789', stored)
                self.assertNotIn('fake-secret-value-123456789', session_markdown('desktop-history'))
                matches = list_sessions(limit=None, query='history search')
                self.assertEqual(len(matches), 1)
                self.assertEqual(matches[0]['summary'], 'fake reply 1')
                renamed = rename_session('desktop-history', 'Renamed history')
                self.assertEqual(renamed['title'], 'Renamed history')
                self.assertEqual(load_session('desktop-history')['desktop_title'], 'Renamed history')
                self.assertEqual(latest.read_text(encoding='utf-8'), 'legacy alias remains untouched')
                self.assertTrue(delete_session('desktop-history'))
                self.assertFalse(path.exists())
                self.assertFalse(list_sessions(limit=None, query='Renamed history'))

            agent = ConversationAgent(model, knowledge=FakeKnowledge(), fetcher=object())
            agent.history = [{'role': 'user', 'content': 'fake-secret-value-123456789'}]
            exported = Path(home) / 'safe-export.md'
            agent.export_session(str(exported))
            self.assertNotIn('fake-secret-value-123456789', exported.read_text(encoding='utf-8'))

    def test_running_message_recovers_as_interrupted(self):
        from scripts.session_store import list_sessions

        with tempfile.TemporaryDirectory() as home:
            session_dir = Path(home) / 'sessions'
            session_dir.mkdir()
            session_path = session_dir / 'desktop-running.json'
            session_path.write_text(json.dumps({
                'version': 1, 'saved_at': '2026-11-09T00:00:00-08:00',
                'history': [], 'contexts': [], 'work_root': home,
                'desktop_title': 'Interrupted request', 'desktop_repository': home,
                'desktop_messages': [{'role': 'user', 'content': 'resume this', 'status': 'running'}],
            }), encoding='utf-8')
            with patch.dict(os.environ, {'REVIEWAGENT_HOME': home}):
                rows = list_sessions(limit=None)
                restored = json.loads(session_path.read_text(encoding='utf-8'))
            self.assertEqual(rows[0]['status'], 'interrupted')
            self.assertEqual(restored['desktop_messages'][0]['status'], 'interrupted')
            self.assertEqual(restored['history'], [{'role': 'user', 'content': 'resume this'}])

    def test_cli_history_commands_and_failed_turn_state(self):
        class FailedModel:
            provider = type('Provider', (), {'api_key': 'secret-test-key-123456'})()

            def chat_with_history(self, messages, **kwargs):
                return 'Error: secret-test-key-123456 rejected'

        with tempfile.TemporaryDirectory() as home:
            def cli(argv, client=None):
                output = io.StringIO()
                with patch.dict(os.environ, {'REVIEWAGENT_HOME': home}), \
                        patch('scripts.conversation_agent.KnowledgeSearch', return_value=FakeKnowledge()), \
                        patch.object(ascend_cli, 'get_ai_client', return_value=client or FailedModel()), \
                        patch('sys.argv', ['ascend_cli.py'] + argv), contextlib.redirect_stdout(output):
                    status = ascend_cli.main()
                return status, output.getvalue()

            status, output = cli(['chat', '--message', 'broken request', '--session', 'desktop-failed',
                                  '--network', 'off', '--json'])
            self.assertEqual(status, 1)
            self.assertNotIn('secret-test-key-123456', output)
            session_path = Path(home) / 'sessions' / 'desktop-failed.json'
            session = json.loads(session_path.read_text(encoding='utf-8'))
            self.assertEqual(session['desktop_messages'][-1]['status'], 'failed')
            self.assertFalse(any(row['role'] == 'assistant' for row in session['desktop_messages']))
            self.assertNotIn('secret-test-key-123456', session_path.read_text(encoding='utf-8'))

            status, output = cli(['sessions', 'list', '--query', 'broken request'])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)['sessions'][0]['status'], 'failed')
            status, output = cli(['sessions', 'show', 'desktop-failed'])
            self.assertEqual(status, 0)
            self.assertEqual(json.loads(output)['session']['title'], 'broken request')
            self.assertEqual(cli(['sessions', 'rename', 'desktop-failed', 'Changed title'])[0], 0)
            export = Path(home) / 'export.md'
            self.assertEqual(cli(['sessions', 'export', 'desktop-failed', '--output', str(export)])[0], 0)
            self.assertIn('Changed title', export.read_text(encoding='utf-8'))
            self.assertNotIn('secret-test-key-123456', export.read_text(encoding='utf-8'))
            self.assertEqual(cli(['sessions', 'delete', 'desktop-failed'])[0], 0)
            self.assertFalse(session_path.exists())

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

    def test_incomplete_issue_is_error_instead_of_a_completed_review(self):
        class IncompleteIssueReviewer:
            def __init__(self, *args, **kwargs):
                pass

            def review(self, *args, **kwargs):
                return {
                    'review_result': {
                        'issues': [{'severity': 'high', 'title': 'Missing details',
                                    'description': 'No location or fix'}],
                        'overall_assessment': 'Found an issue', 'recommendation': 'request_changes',
                        'coverage': 'full',
                    },
                    'knowledge_retrieval': {'references': [], 'warnings': []},
                    'metadata': {'repository': {'changed_files': ['a.py']}},
                }

        args = argparse.Namespace(staged=False, max_diff=12000, json=True, require_full=False,
                                  scenario=None, require_scenario=False, config=None, output=None,
                                  offline=True)
        context = {'diff': 'diff --git a/a.py b/a.py\n+bad', 'diff_truncated': False,
                   'changed_files': ['a.py'], 'diff_total_chars': 20, 'root': '.',
                   'branch': 'test', 'status': '', 'staged': False}
        output = io.StringIO()
        with patch.object(ascend_cli, 'collect_repo_context', return_value=context), \
                patch.object(ascend_cli, 'SmartReviewer', IncompleteIssueReviewer), \
                contextlib.redirect_stdout(output):
            status = ascend_cli.review(args)
        payload = json.loads(output.getvalue())
        self.assertEqual(status, 1)
        self.assertEqual(payload['status'], 'error')
        self.assertIn('review_result.issues[1].location', payload['error'])
        self.assertIn('review_result.issues[1].suggestion', payload['error'])

    def test_review_error_redacts_api_key_before_output_and_file_write(self):
        secret = 'fake-review-key-123456789'

        class FailedReviewer:
            def __init__(self, *args, **kwargs):
                pass

            def review(self, *args, **kwargs):
                return {'status': 'error', 'review_result': {'error': f'proxy echoed {secret}'}}

        context = {'diff': 'diff --git a/a.py b/a.py\n+bad', 'diff_truncated': False,
                   'changed_files': ['a.py'], 'diff_total_chars': 20, 'root': '.',
                   'branch': 'test', 'status': '', 'staged': False}
        with tempfile.TemporaryDirectory() as tmp:
            report_path = Path(tmp) / 'review.json'
            args = argparse.Namespace(staged=False, max_diff=12000, json=True, require_full=False,
                                      scenario=None, require_scenario=False, config=None,
                                      output=str(report_path), offline=True)
            output = io.StringIO()
            with patch.object(ascend_cli, 'collect_repo_context', return_value=context), \
                    patch.object(ascend_cli, 'SmartReviewer', FailedReviewer), \
                    patch('scripts.session_store._api_keys', return_value=[secret]), \
                    contextlib.redirect_stdout(output):
                status = ascend_cli.review(args)
            self.assertEqual(status, 1)
            self.assertNotIn(secret, output.getvalue())
            self.assertIn('[API Key 已隐藏]', output.getvalue())
            self.assertNotIn(secret, report_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()

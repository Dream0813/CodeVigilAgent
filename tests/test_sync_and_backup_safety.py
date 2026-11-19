"""Offline regressions for upstream writes, config recovery and commit gates."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts import config_backup, git_hooks, sync_upstream


class UpstreamSyncSafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.outer = Path(self.tmp.name).resolve()
        self.root = self.outer / 'repo'
        self.root.mkdir()
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        self.addCleanup(patch.stopall)
        patch.object(sync_upstream, 'REPO_DIR', str(self.root)).start()
        self.remote = {}
        patch.object(sync_upstream, 'fetch_file', side_effect=lambda sha, path: self.remote.get((sha, path))).start()

    def plan(self, files):
        return sync_upstream.plan(files, 'base', 'head')

    def rename(self):
        (self.root / 'old.py').write_bytes(b'old\n')
        self.remote.update({('base', 'old.py'): b'old\n', ('head', 'new.py'): b'new\n'})
        return [{'path': 'new.py', 'status': 'renamed', 'previous_path': 'old.py'}]

    def test_compare_preserves_rename_source(self):
        data = {'files': [{'filename': 'new.py', 'status': 'renamed', 'previous_filename': 'old.py'}]}
        with patch.object(sync_upstream, 'api', return_value=data):
            _, files = sync_upstream.diff_files('base', 'head')
        self.assertEqual(files[0]['previous_path'], 'old.py')

    def test_rename_writes_destination_and_removes_source(self):
        plan = self.plan(self.rename())
        sync_upstream.apply_plan(plan, False, 'base', 'head')
        self.assertFalse((self.root / 'old.py').exists())
        self.assertEqual((self.root / 'new.py').read_bytes(), b'new\n')
        again = self.plan([{'path': 'new.py', 'status': 'renamed', 'previous_path': 'old.py'}])
        self.assertEqual(again['safe'], [])
        self.assertEqual(again['conflicted'], [])

    def test_rename_preserves_both_paths_when_either_has_local_edits(self):
        for edited in ('old.py', 'new.py'):
            with self.subTest(edited=edited):
                files = self.rename()
                (self.root / edited).write_bytes(b'local edit\n')
                plan = self.plan(files)
                self.assertEqual(plan['safe'], [])
                self.assertEqual(set(plan['conflicted']), {'new.py', 'old.py'})
                self.assertEqual(sync_upstream.apply_plan(plan, False, 'base', 'head'), [])
                self.assertEqual((self.root / edited).read_bytes(), b'local edit\n')
                (self.root / edited).unlink()

    def test_force_can_resolve_rename_conflicts(self):
        files = self.rename()
        (self.root / 'old.py').write_bytes(b'local edit\n')
        plan = self.plan(files)
        sync_upstream.apply_plan(plan, True, 'base', 'head')
        self.assertFalse((self.root / 'old.py').exists())
        self.assertEqual((self.root / 'new.py').read_bytes(), b'new\n')

    def test_normal_add_modify_delete_and_local_conflict(self):
        (self.root / 'modify.py').write_bytes(b'base')
        (self.root / 'delete.py').write_bytes(b'base')
        (self.root / 'conflict.py').write_bytes(b'local')
        self.remote.update({('base', 'modify.py'): b'base', ('head', 'modify.py'): b'new',
                            ('base', 'delete.py'): b'base', ('head', 'add.py'): b'new',
                            ('base', 'conflict.py'): b'base', ('head', 'conflict.py'): b'new'})
        plan = self.plan([{'path': path, 'status': status} for path, status in
                          [('modify.py', 'modified'), ('delete.py', 'removed'),
                           ('add.py', 'added'), ('conflict.py', 'modified')]])
        sync_upstream.apply_plan(plan, False, 'base', 'head')
        self.assertEqual((self.root / 'modify.py').read_bytes(), b'new')
        self.assertEqual((self.root / 'add.py').read_bytes(), b'new')
        self.assertFalse((self.root / 'delete.py').exists())
        self.assertEqual((self.root / 'conflict.py').read_bytes(), b'local')

    def test_missing_remote_file_does_not_become_delete(self):
        (self.root / 'a.py').write_bytes(b'base')
        self.remote[('base', 'a.py')] = b'base'
        with self.assertRaises(FileNotFoundError):
            self.plan([{'path': 'a.py', 'status': 'modified'}])
        self.assertEqual((self.root / 'a.py').read_bytes(), b'base')

    def test_unsafe_paths_are_rejected_including_rename_source(self):
        for path in ('../outside', str(self.outer / 'outside'), 'C:/outside', 'C:outside',
                     '.git/config', 'nested/.GIT/config'):
            with self.subTest(path=path):
                with self.assertRaises(ValueError):
                    self.plan([{'path': path, 'status': 'added'}])
                with self.assertRaises(ValueError):
                    self.plan([{'path': 'new.py', 'status': 'renamed', 'previous_path': path}])

    def test_separate_git_directory_is_rejected(self):
        nested = self.root / 'nested'
        metadata = self.root / 'metadata'
        subprocess.run(['git', 'init', '-q', '--separate-git-dir', str(metadata), str(nested)], check=True)
        with self.assertRaises(ValueError):
            self.plan([{'path': 'metadata/config', 'status': 'modified'}])

    def symlink(self, target, link):
        try:
            link.symlink_to(target, target_is_directory=target.is_dir())
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f'Symbolic links unavailable: {exc}')

    def test_external_file_and_directory_symlinks_are_rejected(self):
        outside = self.outer / 'outside'
        outside.write_bytes(b'base')
        self.symlink(outside, self.root / 'alias')
        self.remote.update({('base', 'alias'): b'base', ('head', 'alias'): b'new'})
        with self.assertRaises(ValueError):
            self.plan([{'path': 'alias', 'status': 'modified'}])
        self.symlink(self.outer, self.root / 'directory')
        with self.assertRaises(ValueError):
            self.plan([{'path': 'directory/outside', 'status': 'modified'}])
        self.assertEqual(outside.read_bytes(), b'base')

    def test_rechecks_symlink_before_apply_even_with_force(self):
        outside = self.outer / 'outside'
        outside.write_bytes(b'outside')
        self.remote[('head', 'a.py')] = b'new'
        plan = self.plan([{'path': 'a.py', 'status': 'added'}])
        self.symlink(outside, self.root / 'a.py')
        with self.assertRaises(ValueError):
            sync_upstream.apply_plan(plan, True, 'base', 'head')
        self.assertEqual(outside.read_bytes(), b'outside')


class ConfigRestoreSafetyTests(unittest.TestCase):
    def test_oldest_of_twenty_backups_is_restored_before_pruning(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backups = root / 'backups'
            backups.mkdir()
            for i in range(20):
                file = backups / f'ai_config.20260101-{i:02d}.manual.json'
                file.write_text(f'{{"model":"old-{i}"}}')
                os.utime(file, (i + 1, i + 1))
            config = root / 'ai_config.json'
            config.write_text('{"model":"current"}')
            config.chmod(0o600)
            os.utime(config, (0, 0))
            selected = config_backup.list_backups(backups)[-1]
            expected = selected.read_bytes()
            _, safety = config_backup.restore_backup(config, selected.name, directory=backups)
            self.assertEqual(config.read_bytes(), expected)
            self.assertEqual(safety.read_text(), '{"model":"current"}')
            self.assertEqual(len(config_backup.list_backups(backups)), 20)

    def test_failed_restore_keeps_source_and_safety_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backups = root / 'backups'
            backups.mkdir()
            source = backups / 'ai_config.old.manual.json'
            source.write_text('{"model":"old"}')
            config = root / 'ai_config.json'
            config.write_text('{"model":"current"}')
            copy = shutil.copy2

            def fail_restore(src, dst):
                if Path(src) == source:
                    raise OSError('synthetic copy failure')
                return copy(src, dst)

            with patch.object(config_backup.shutil, 'copy2', side_effect=fail_restore):
                with self.assertRaises(OSError):
                    config_backup.restore_backup(config, source.name, directory=backups)
            self.assertTrue(source.exists())
            self.assertEqual(config.read_text(), '{"model":"current"}')
            self.assertEqual(len(config_backup.list_backups(backups)), 2)

    def test_same_source_and_target_rejected_before_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'ai_config.old.manual.json'
            source.write_text('{"model":"old"}')
            with self.assertRaises(ValueError):
                config_backup.restore_backup(source, source.name, directory=Path(tmp))
            self.assertEqual(len(config_backup.list_backups(Path(tmp))), 1)


@unittest.skipIf(os.name == 'nt', 'POSIX file permission checks')
class ConfigBackupPermissionTests(unittest.TestCase):
    def mode(self, path):
        return stat.S_IMODE(path.stat().st_mode)

    def test_legacy_config_and_backup_are_private_without_changing_shared_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'ai_config.json'
            config.write_bytes(b'{"api_key":"fake-only"}\n')
            config.chmod(0o644)
            shared = root / 'shared'
            shared.mkdir()
            shared.chmod(0o755)
            copy = shutil.copy2

            def checked_copy(source, target):
                self.assertEqual(self.mode(Path(source)), 0o600)
                self.assertEqual(self.mode(Path(target)), 0o600)
                return copy(source, target)

            with patch.object(config_backup.shutil, 'copy2', side_effect=checked_copy):
                backup = config_backup.create_backup(config, directory=shared)
            self.assertEqual(config.read_bytes(), backup.read_bytes())
            self.assertEqual(self.mode(config), 0o600)
            self.assertEqual(self.mode(backup), 0o600)
            self.assertEqual(self.mode(shared), 0o755)

    def test_restore_legacy_backup_keeps_existing_and_new_config_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            backups = root / 'shared-backups'
            backups.mkdir()
            backups.chmod(0o755)
            source = backups / 'ai_config.old.manual.json'
            source.write_bytes(b'{"api_key":"fake-old-only"}\n')
            for exists in (True, False):
                with self.subTest(existing_config=exists):
                    source.chmod(0o644)
                    config = root / ('existing.json' if exists else 'new.json')
                    if exists:
                        config.write_bytes(b'{"api_key":"fake-current-only"}')
                        config.chmod(0o644)
                    _, safety = config_backup.restore_backup(config, source.name, directory=backups)
                    self.assertEqual(config.read_bytes(), source.read_bytes())
                    self.assertEqual(self.mode(config), 0o600)
                    self.assertEqual(self.mode(source), 0o600)
                    if safety:
                        self.assertEqual(self.mode(safety), 0o600)
                    self.assertEqual(self.mode(backups), 0o755)

    def test_default_backup_directory_is_private(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / 'ai_config.json'
            config.write_bytes(b'{}')
            backups = root / 'default-backups'
            backups.mkdir()
            backups.chmod(0o755)
            with patch.dict(os.environ, {'REVIEWAGENT_BACKUP_DIR': ''}), \
                    patch.object(config_backup, 'backup_dir', return_value=backups):
                config_backup.create_backup(config)
            self.assertEqual(self.mode(backups), 0o700)

    def test_directory_target_is_rejected_without_chmod(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'ai_config.old.manual.json'
            source.write_bytes(b'{}')
            directory = root / 'config-directory'
            directory.mkdir()
            directory.chmod(0o755)
            with self.assertRaisesRegex(ValueError, '目录'):
                config_backup.restore_backup(directory, source.name, directory=root)
            self.assertEqual(self.mode(directory), 0o755)
            self.assertEqual(len(config_backup.list_backups(root)), 1)


@unittest.skipUnless(shutil.which('sh'), 'Generated Git hook requires sh')
class CommitHookCoverageTests(unittest.TestCase):
    def test_generated_hook_blocks_truncated_staged_review(self):
        cli = Path(__file__).resolve().parents[1] / 'ascend_cli.py'
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / 'repo'
            repo.mkdir()
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            # 2026-11-19：--max-diff 默认已提到 60000（旧 12000 会拦下中等提交），
            # 截断场景的 fixture 相应放大到 ~90k 字符。
            (repo / 'npu.py').write_text('# npu\n' + '# padding line\n' * 6200 + 'x.cuda()\n')
            subprocess.run(['git', '-C', str(repo), 'add', 'npu.py'], check=True)
            hook, _ = git_hooks.install(str(repo), sys.executable, str(cli))
            env = dict(os.environ, REVIEWAGENT_HOME=str(root / 'home'))
            proc = subprocess.run(['sh', str(hook)], cwd=repo, env=env,
                                  capture_output=True, text=True, timeout=60)
            self.assertNotEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            self.assertIn('--max-diff', proc.stderr)


if __name__ == '__main__':
    unittest.main()

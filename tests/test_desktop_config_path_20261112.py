"""Windows 桌面版的配置路径必须和 CLI 一致。

不一致的后果：桌面版改完设置，终端版读的是另一份文件，看起来"保存了没生效"。
"""
import os
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIN = ROOT / 'desktop-app' / 'win'
CODE = 'import sys; sys.path.insert(0, r"{}"); from cvapp import config; print(config.CONFIG_PATH)'.format(WIN)


class DesktopConfigPathTests(unittest.TestCase):
    def config_path(self, **env_extra):
        env = dict(os.environ)
        env.pop('REVIEWAGENT_CONFIG', None)
        env.pop('REVIEWAGENT_HOME', None)
        env.update(env_extra)
        result = subprocess.run([sys.executable, '-c', CODE], env=env,
                                capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', 'replace'))
        return result.stdout.decode('utf-8').strip()

    def test_default_under_home(self):
        path = Path(self.config_path())
        self.assertEqual(path.name, 'ai_config.json')
        self.assertEqual(path.parent.name, '.reviewagent')
        self.assertEqual(path.parent.parent, Path.home())

    def test_reviewagent_home_is_honoured(self):
        path = Path(self.config_path(REVIEWAGENT_HOME=r'D:\tmp\ra_test_home'))
        self.assertEqual(path, Path(r'D:\tmp\ra_test_home\ai_config.json'))

    def test_reviewagent_config_wins(self):
        path = Path(self.config_path(REVIEWAGENT_CONFIG=r'D:\tmp\custom.json',
                                     REVIEWAGENT_HOME=r'D:\tmp\ignored'))
        self.assertEqual(path, Path(r'D:\tmp\custom.json'))


if __name__ == '__main__':
    unittest.main()

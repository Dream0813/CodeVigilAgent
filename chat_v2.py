#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ReviewAgent - 专业对话式代码审查助手
参考 Claude Code 的交互设计
"""
import sys
import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional
import textwrap
import unicodedata
from datetime import datetime

# Windows 编码设置放在函数里执行（见 _configure_console）。
# 原来写在模块级：任何 import chat_v2 的代码都会在导入瞬间被换掉 sys.stdout，
# 调用方此前尚未 flush 的输出会整段丢失 —— frame_doctor 因此只显示得到 1 个盒子。
def _configure_console() -> None:
    """Windows 控制台编码：尽量切 UTF-8，切不动就退回「编码不了就替换」。"""
    if sys.platform == 'win32':
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, 'reconfigure', None)
            if reconfigure is None:
                continue
            try:
                reconfigure(encoding='utf-8', errors='replace', line_buffering=True)
            except Exception:
                pass
    try:
        from scripts.console_safe import harden_console
        harden_console()
    except Exception:
        pass

# 项目路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

try:
    from scripts.smart_reviewer import SmartReviewer
    from scripts.ai_adapter import get_ai_client
    from scripts.github_fetcher import UniversalFetcher, WebSearcher
    from scripts import term_frame as tf
except ImportError as e:
    print(f"[ERROR] 导入失败: {e}")
    sys.exit(1)


# ============================================================================
# 颜色和样式（跨平台）
# ============================================================================

class Style:
    """终端样式"""

    # ANSI 颜色代码
    RESET = '\033[0m'
    BOLD = '\033[1m'
    DIM = '\033[2m'

    # 前景色
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'

    # 品牌色（与启动画面的青 #00C2A8 / 粉 #FF8FAB 对齐）
    # 用 256 色而不是 24-bit，兼容旧版 Windows conhost
    BRAND = '\033[38;5;37m'    # 主色 青绿
    ACCENT = '\033[38;5;212m'  # 强调 粉
    GLOW = '\033[38;5;80m'     # 高亮 浅青
    FAINT = '\033[38;5;240m'   # 极弱 灰

    # 亮色版本
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'

    @staticmethod
    def strip(text: str) -> str:
        """移除样式代码"""
        return re.sub(r'\033\[[0-9;]+m', '', text)

    @staticmethod
    def enabled() -> bool:
        """检测是否支持颜色"""
        if sys.platform == 'win32':
            # Windows 10+ 支持 ANSI
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
                return True
            except:
                return False
        return True


# 全局样式开关
USE_COLORS = Style.enabled()


# ---------------------------------------------------------------------------
# 字形表：Windows 传统控制台（conhost）用的是宋体，不含 ❯ ✓ ✕ ✎ ✦ › 这些符号，
# 直接输出会显示成方块 □。这里按终端能力自动降级到 GBK 里一定有的字符，
# 也可以用环境变量 REVIEWAGENT_GLYPHS=fancy|safe 强制指定。
# ---------------------------------------------------------------------------
def _unicode_glyphs() -> bool:
    override = os.environ.get('REVIEWAGENT_GLYPHS', '').lower()
    if override == 'fancy':
        return True
    if override == 'safe':
        return False
    if sys.platform != 'win32':
        return True
    # Windows 一律保守：终端类型（conhost / Windows Terminal）判断不可靠，
    # 用户也可能给 WT 配了宋体。宁可朴素，也不要满屏方块。
    # 想用花哨符号：set REVIEWAGENT_GLYPHS=fancy
    return False


class G:
    """字形表。

    下面这些在 GBK 里本来就有，宋体也能渲染，两种终端都能用，故不做降级：
      圆角边框 ╭ ╮ ╰ ╯ 、竖色块 ▌ 、列表符号 ◆ 、箭头 ←
    只有 GBK 真的没收、字体也画不出来的才降级：
      ❯ ✕ ✎ ✦ › ✓ ✗ ⚠ ℹ ◐ • 盲文转轮
    """

    _f = _unicode_glyphs()

    TL = '╭'
    TR = '╮'
    BL = '╰'
    BR = '╯'
    BAR = '▌'
    BULLET = '◆'
    PROMPT = '❯' if _f else '>'
    OK = '✓' if _f else '√'
    BAD = '✗' if _f else '×'
    WARN = '⚠' if _f else '!'
    INFO = 'ℹ' if _f else 'i'
    WORKING = '◐' if _f else '●'


def colored(text: str, color: str) -> str:
    """添加颜色"""
    if not USE_COLORS:
        return text
    return f"{color}{text}{Style.RESET}"


def bold(text: str) -> str:
    """加粗"""
    if not USE_COLORS:
        return text
    return f"{Style.BOLD}{text}{Style.RESET}"


def dim(text: str) -> str:
    """变暗"""
    if not USE_COLORS:
        return text
    return f"{Style.DIM}{text}{Style.RESET}"


# ============================================================================
# UI 组件
# ============================================================================

class UI:
    """UI 工具类

    宽度只有一个出处：`scripts.term_frame`。以前这里自己实现了一套
    _w/_tokens/_wrap/_pad，把 EAW=A 的字符（· ◆ →）算成 1 列，而
    term_frame 算 2 列 —— 同一个程序两套算法，右边框必然对不上。
    """

    @staticmethod
    def _w(text: str) -> int:
        """按终端显示宽度计数：中文/全角算 2 列，ANSI 码不计"""
        return tf.display_width(text)

    @staticmethod
    def _tokens(text: str):
        return list(tf._tokens(text))

    @staticmethod
    def _wrap(text: str, width: int):
        """按终端显示宽度折行（保留颜色码，中文不会被劈坏）"""
        return tf.wrap_display(text, width)

    @staticmethod
    def _pad(text: str, target: int) -> str:
        """按显示宽度右侧补空格"""
        return tf.pad_display(text, target)

    @staticmethod
    def box(title: str = "", content: str = "", width: int = 0):
        """绘制圆角边框盒子（品牌色边线）。

        width=0 表示跟随 term_frame.total_width()，与输入框、思考面板
        用同一个宽度 —— 这样同一屏里所有竖线才落在同一列。

        走 tf.emit_box：终端支持定位时把右边框钉在固定列，换字体也不会歪；
        不支持时自动退回补空格。
        """
        import io as _io

        total = width or tf.total_width()
        bodies = []
        border = lambda s: colored(s, Style.BRAND)

        # 标题居中 + 分隔线
        if title:
            safe = tf.frame_safe(title)
            # 调用方已上色就不再包一层，避免嵌套 RESET 把颜色吃掉
            rendered = safe if '\033[' in safe else bold(colored(safe, Style.BRAND))
            tw = tf.display_width(rendered)
            left = max((total - 4 - tw) // 2, 0)
            bodies.append(' ' * left + rendered)
            bodies.append(tf.DIVIDER)

        # 内容
        if content:
            for line in content.split('\n'):
                for wrapped in tf.wrap_display(line, tf.content_width(total)):
                    bodies.append(wrapped)

        buf = _io.StringIO()
        tf.emit_box('', bodies, total=total, paint=border, stream=buf)
        return buf.getvalue().rstrip('\n')

    @staticmethod
    def section(title: str, width: int = 0):
        """章节标题：`▌ 标题 ──────`，横线补到与盒子同宽

        这一行没有右边框，所以就算 `▌` 的宽度判断和终端差 1 列也看不出来，
        保留 `▌` 的观感比换成 `|` 划算。
        """
        total = width or tf.total_width()
        safe = tf.frame_safe(title)
        bar = '─' * max(total - tf.display_width(safe) - 4, 3)
        return f"\n{colored(G.BAR, Style.ACCENT)} {bold(safe)} {colored(bar, Style.FAINT)}\n"

    @staticmethod
    def bullet(text: str, symbol: str = G.BULLET) -> str:
        """带符号的列表项"""
        return f"  {colored(symbol, Style.BRAND)} {text}"

    @staticmethod
    def status(text: str, status_type: str = "info") -> str:
        """状态消息（无方括号，图标直接带色）"""
        icons = {
            'success': (G.OK, Style.GREEN),
            'error': (G.BAD, Style.RED),
            'warning': (G.WARN, Style.YELLOW),
            'info': (G.INFO, Style.GLOW),
            'working': (G.WORKING, Style.BRAND),
        }

        icon, color = icons.get(status_type, ('·', Style.WHITE))
        return f"{colored(icon, color)} {text}"

    @staticmethod
    def spinner(text: str) -> str:
        """进度指示（盲文字符宋体没有，降级成 ASCII 转轮）"""
        frames = "⣾⣽⣻⢿⡿⣟⣯⣷" if G._f else "|/-\\"
        return colored(frames, Style.BRAND) + f" {text}"

    @staticmethod
    def code_block(code: str, language: str = "") -> str:
        """代码块"""
        lines = []
        lines.append(colored("```" + language, Style.DIM))
        for line in code.split('\n'):
            lines.append(colored("│", Style.DIM) + f" {line}")
        lines.append(colored("```", Style.DIM))
        return '\n'.join(lines)


# ============================================================================
# 核心对话引擎
# ============================================================================

class ReviewAgentChat:
    """ReviewAgent 专业对话系统"""

    def __init__(self):
        self.config_file = Path('config/ai_config.json')
        self.ai_client = None
        self.reviewer = None
        self.conversation_history = []
        self.session_start = datetime.now()

    def _init_github_fetcher(self):
        """初始化 GitHub fetcher"""
        # 尝试从环境变量读取 token
        import os
        github_token = os.getenv('GITHUB_TOKEN')

        # 或从配置文件读取
        github_config_file = Path('config/github_config.json')
        if github_config_file.exists():
            try:
                with open(github_config_file, 'r') as f:
                    config = json.load(f)
                github_token = config.get('token')
            except:
                pass

        # 原来写的是 GitHubFetcher，但 scripts/github_fetcher.py 里没有这个类，
        # 真正能用的是 UniversalFetcher（GitHub / Gitee / GitCode 通用）。
        self.github_fetcher = UniversalFetcher(github_token=github_token)

    def initialize(self):
        """初始化系统"""
        print(UI.status("初始化 ReviewAgent...", "working"), flush=True)

        # 检查配置
        if not self.config_file.exists():
            print(UI.status("首次使用，需要配置 AI 服务", "info"))
            self.setup_wizard()
        else:
            self.load_config()

    def switch_model(self):
        """切换 AI 模型"""
        if not self.config_file.exists():
            print(UI.status("尚未配置 AI，请先运行 /config", "error"))
            return

        # 读取当前配置
        with open(self.config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)

        current_provider = config.get('provider', 'unknown')
        current_model = config.get('model', 'unknown')

        print(f"\n当前配置: {bold(current_provider.upper())} - {current_model}")
        print()

        providers = [
            ("DeepSeek", "deepseek", "deepseek-chat", "性价比最高，代码能力强"),
            ("OpenAI", "openai", "gpt-4", "最强大的通用 AI"),
            ("Claude", "claude", "claude-3-opus-20240229", "长文本理解优秀"),
            ("GLM", "glm", "glm-4", "中文支持好"),
        ]

        print("可用的 AI 服务:\n")
        for i, (name, provider, model, desc) in enumerate(providers, 1):
            current = " " + colored("(当前)", Style.GREEN) if provider == current_provider else ""
            print(UI.bullet(f"{i}. {bold(name)} - {desc}{current}"))

        try:
            choice = input(f"\n{colored(G.PROMPT, Style.ACCENT)} 请选择 (1-{len(providers)}, 回车保持不变): ").strip()

            if not choice:
                print(UI.status("保持当前配置", "info"))
                return

            idx = int(choice) - 1
            if 0 <= idx < len(providers):
                name, provider, model, _ = providers[idx]

                # 如果切换服务商，需要新的 API Key
                if provider != current_provider:
                    print(f"\n{colored(G.PROMPT, Style.ACCENT)} 请输入你的 {name} API Key:")
                    api_key = input(f"{colored(G.PROMPT, Style.ACCENT)} ").strip()

                    if not api_key:
                        print(UI.status("API Key 不能为空", "error"))
                        return

                    config['api_key'] = api_key

                config['provider'] = provider
                config['model'] = model

                # 保存配置
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(config, f, indent=2)

                print(UI.status(f"已切换到: {name}", "success"))

                # 重新加载
                print(UI.status("重新加载配置...", "working"), flush=True)
                self.load_config()
                print(UI.status("配置已更新", "success"))

        except (ValueError, KeyboardInterrupt) as e:
            print(UI.status("操作取消", "info"))

    def setup_wizard(self):
        """配置向导"""
        print("\n" + UI.box("AI 配置向导", """
欢迎使用 ReviewAgent！

ReviewAgent 需要连接 AI 服务来提供智能审查。
请选择你要使用的 AI 服务商。
"""))

        providers = [
            ("DeepSeek", "deepseek", "deepseek-chat", "性价比最高，代码能力强"),
            ("OpenAI", "openai", "gpt-4", "最强大的通用 AI"),
            ("Claude", "claude", "claude-3-opus-20240229", "长文本理解优秀"),
            ("GLM", "glm", "glm-4", "中文支持好"),
        ]

        print("\n可用的 AI 服务:\n")
        for i, (name, _, _, desc) in enumerate(providers, 1):
            print(UI.bullet(f"{i}. {bold(name)} - {desc}"))

        while True:
            try:
                choice = input(f"\n{colored(G.PROMPT, Style.ACCENT)} 请选择 (1-{len(providers)}): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(providers):
                    name, provider, model, _ = providers[idx]
                    print(UI.status(f"已选择: {name}", "success"))
                    break
                else:
                    print(UI.status("无效选择", "error"))
            except (ValueError, KeyboardInterrupt):
                print(UI.status("无效输入", "error"))

        # 获取 API Key
        print(f"\n{colored(G.PROMPT, Style.ACCENT)} 请输入你的 {name} API Key:")
        print(dim("  (API Key 会保存在本地，不会上传)"))
        api_key = input(f"{colored(G.PROMPT, Style.ACCENT)} ").strip()

        if not api_key:
            print(UI.status("API Key 不能为空", "error"))
            return self.setup_wizard()

        # 保存配置
        config = {
            "provider": provider,
            "api_key": api_key,
            "model": model
        }

        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)

        print(UI.status("配置已保存", "success"))

        # 测试连接
        print(UI.status("测试 AI 连接...", "working"), flush=True)
        try:
            self.load_config()
            print(UI.status("连接成功！", "success"))
        except Exception as e:
            print(UI.status(f"连接失败: {e}", "error"))
            retry = input(f"\n{colored(G.PROMPT, Style.ACCENT)} 重新配置? (y/n): ").strip().lower()
            if retry == 'y':
                return self.setup_wizard()
            else:
                sys.exit(1)

    def load_config(self):
        """加载配置"""
        try:
            self.ai_client = get_ai_client(str(self.config_file))
            self.reviewer = SmartReviewer(str(self.config_file))
        except Exception as e:
            raise Exception(f"配置加载失败: {e}")

    def show_welcome(self):
        """显示欢迎信息"""
        head = (
            f"{bold(colored('ReviewAgent', Style.BRAND))}"
            f" {colored('智能代码审查助手', Style.ACCENT)}"
            f" {dim('v1.2')}"
        )
        body = '\n'.join([
            '',
            f"  {dim('昇腾 NPU 生态')} · 基于 {colored('733 issues', Style.BRAND)}"
            f" + {colored('745 PRs', Style.BRAND)} 实战经验",
            '',
            f"  {colored(G.BAR, Style.ACCENT)} {bold('能做什么')}",
            UI.bullet('粘贴代码 → 直接审查'),
            UI.bullet('发送 GitHub / Gitee 链接 → 分析 PR / Issue'),
            UI.bullet('提问昇腾 NPU 相关问题'),
            '',
            f"  {colored(G.BAR, Style.ACCENT)} {bold('命令')}",
            f"  {colored('/help', Style.BRAND)}    帮助        "
            f"{colored('/clear', Style.BRAND)}   清空对话",
            f"  {colored('/config', Style.BRAND)}  重配 AI     "
            f"{colored('/stats', Style.BRAND)}   统计信息",
            f"  {colored('/exit', Style.BRAND)}    退出",
            '',
            f"  {dim('提示：多行内容按两次回车提交 · Ctrl+C 中断当前请求')}",
            '',
        ])
        print()
        print(UI.box(head, body))
        print()

    def parse_command(self, user_input: str) -> Optional[str]:
        """解析命令"""
        if not user_input.startswith('/'):
            return None

        cmd = user_input[1:].strip().lower()

        if cmd in ['exit', 'quit', 'q']:
            return 'exit'
        elif cmd == 'help':
            return 'help'
        elif cmd == 'clear':
            return 'clear'
        elif cmd in ['config', 'setup', 'configure']:
            return 'config'
        elif cmd == 'stats':
            return 'stats'
        elif cmd in ['model', 'switch']:
            return 'switch_model'
        elif cmd.startswith('search '):
            return 'search'
        else:
            print(UI.status(f"未知命令: /{cmd}", "error"))
            print(dim("输入 /help 查看可用命令"))
            return 'unknown'

    def handle_fetch_and_review(self, urls):
        """抓取 GitHub / Gitee / GitCode 的 PR、Issue 或网页，然后出审查报告。

        原来这个分支调用的是 self.handle_fetch_and_review(...)，但类里没有这个方法，
        所以「发一个 GitHub 链接」必然报 AttributeError。这里补上。
        """
        if isinstance(urls, str):
            urls = [urls]
        urls = [u for u in (urls or []) if u]
        if not urls:
            print(UI.status("没识别到网址，请把链接一起发给我", "error"))
            return

        if not getattr(self, 'github_fetcher', None):
            self._init_github_fetcher()

        if not self.reviewer:
            print(UI.status("审查器还没初始化完成，请稍后再试", "error"))
            return

        for url in urls:
            print(UI.status(f"抓取 {url} ...", "working"), flush=True)
            try:
                data = self.github_fetcher.fetch_url(url)
            except Exception as e:
                print(UI.status(f"抓取失败: {e}", "error"))
                continue

            if not data:
                print(UI.status("这个链接没抓到内容（可能是私有仓库，或链接格式不支持）", "error"))
                continue

            try:
                text = self.github_fetcher.format_for_review(data)
            except Exception as e:
                print(UI.status(f"内容整理失败: {e}", "error"))
                continue

            print(UI.status("抓到了，开始审查...", "working"), flush=True)
            try:
                report = self.reviewer.review(text)
                print()
                self.reviewer.print_report(report)
            except Exception as e:
                print(UI.status(f"审查失败: {e}", "error"))

    def handle_help(self):
        """显示帮助"""
        help_text = """
╔══════════════════════════════════════════════════════════════════╗
║                       ReviewAgent 使用指南                        ║
╚══════════════════════════════════════════════════════════════════╝

【审查代码】
  直接粘贴代码，系统会自动识别并审查:

  > def allocate(size):
  >     return torch.zeros(size).cuda()

  多行代码会自动提示继续输入，按两次回车提交

【分析 PR/Issue】
  发送链接，系统会自动获取并分析:

  > https://github.com/user/repo/pull/123
  > 帮我看看这个 PR

【技术咨询】
  直接提问，像和专家聊天:

  > 昇腾 NPU 怎么迁移 CUDA 代码？
  > torch_npu 和 torch.cuda 的区别？
  > 模型精度对不齐怎么办？

【命令】
  /help    - 显示此帮助
  /clear   - 清除对话历史
  /config  - 重新配置 AI 服务
  /model   - 切换 AI 模型
  /search <关键词> - 手动搜索
  /stats   - 显示数据统计
  /exit    - 退出程序

【智能搜索】
  当你提问时，系统会自动判断是否需要搜索网络来回答。
  例如:
  > 昇腾 CANN 8.0 怎么安装？
  系统会自动搜索相关信息

  也可以手动搜索:
  > /search 昇腾 NPU 性能优化

【输入提示】
  · 单行输入: 直接输入后回车
  · 多行输入: 长文本或代码块会自动提示，按两次回车提交
  · 取消输入: Ctrl+C
"""
        print(help_text)

    def handle_stats(self):
        """显示统计"""
        stats = f"""
{UI.section('ReviewAgent 数据统计')}

{bold('训练数据库:')}
  · 仓库数量: {colored('18', Style.GREEN)} 个 (PyTorch + MindSpore)
  · Issues: {colored('733', Style.GREEN)} 个
  · PRs: {colored('745', Style.GREEN)} 个
  · 总数据量: {colored('25 MB', Style.GREEN)}

{bold('本次会话:')}
  · 开始时间: {self.session_start.strftime('%Y-%m-%d %H:%M:%S')}
  · 对话轮次: {len(self.conversation_history) // 2}
  · AI 服务: {colored(self._get_provider_name(), Style.CYAN)}
"""
        print(stats)

    def _get_provider_name(self) -> str:
        """获取 AI 服务商名称"""
        if not self.config_file.exists():
            return "未配置"

        try:
            with open(self.config_file, 'r') as f:
                config = json.load(f)
            return config.get('provider', 'Unknown').upper()
        except:
            return "Unknown"

    def understand_intent(self, user_input: str) -> Dict:
        """智能意图识别"""
        # 检测 URL
        url_pattern = r'https?://[^\s]+'
        urls = re.findall(url_pattern, user_input)

        # 检测代码
        has_code = bool(re.search(r'(```|def |class |import |from )', user_input))

        # 意图关键词
        review_keywords = ['审查', 'review', '检查', 'check', '看看', '分析']
        question_keywords = ['怎么', '如何', '为什么', '什么', '?', '？']
        search_keywords = ['搜索', 'search', '查找', '找', '教程', '文档', '官方']

        # 判断意图
        if urls:
            return {'intent': 'fetch_url', 'urls': urls, 'confidence': 0.9}
        elif has_code:
            return {'intent': 'review_code', 'code': user_input, 'confidence': 0.85}
        elif any(kw in user_input.lower() for kw in review_keywords):
            return {'intent': 'review_request', 'text': user_input, 'confidence': 0.8}
        elif any(kw in user_input.lower() for kw in search_keywords):
            return {'intent': 'need_search', 'text': user_input, 'confidence': 0.9}
        elif any(kw in user_input for kw in question_keywords):
            # 问题类：需要 AI 判断是否搜索
            return {'intent': 'question_maybe_search', 'text': user_input, 'confidence': 0.7}
        else:
            return {'intent': 'chat', 'text': user_input, 'confidence': 0.5}

    def handle_review_code(self, code: str):
        """处理代码审查"""
        # 立即显示状态
        print(UI.status("分析代码中...", "working"), flush=True)

        try:
            # 提取代码
            code_match = re.search(r'```(?:python|py)?\n(.*?)\n```', code, re.DOTALL)
            if code_match:
                code = code_match.group(1)

            # 审查
            report = self.reviewer.review(code)

            # 清除状态行
            print("\r" + " " * 50 + "\r", end='', flush=True)

            # 打印报告
            print()
            self.reviewer.print_report(report)

        except Exception as e:
            print(UI.status(f"审查失败: {e}", "error"))

    def should_search(self, user_input: str) -> Optional[str]:
        """
        使用 AI 判断是否需要搜索，以及搜索什么

        Returns:
            搜索关键词，如果不需要搜索则返回 None
        """
        if not self.ai_client:
            return None

        prompt = f"""用户问题: {user_input}

判断是否需要网络搜索来回答这个问题。

需要搜索的情况:
- 询问最新信息、版本、文档
- 需要查找官方资料
- 技术教程、安装步骤
- 错误码、已知问题

不需要搜索的情况:
- 代码审查、分析代码
- 通用编程概念
- 你已知的昇腾 NPU 知识
- 闲聊

如果需要搜索，返回搜索关键词；如果不需要，返回 "NO"

只返回关键词或 NO，不要解释。
"""

        try:
            response = self.ai_client.chat(prompt, temperature=0.3, max_tokens=50)
            response = response.strip()

            if response.upper() == 'NO' or not response:
                return None

            # 提取关键词
            return response
        except:
            return None

    def handle_chat(self, user_input: str, with_search: bool = True):
        """处理对话"""
        # 判断是否需要搜索
        search_context = ""

        if with_search:
            print(dim("[分析是否需要搜索...]"), flush=True)
            search_query = self.should_search(user_input)

            if search_query:
                print(UI.status(f"自动搜索: {search_query}", "working"), flush=True)

                # 执行搜索
                results = self.searcher.search(search_query, num_results=3)

                if results and 'error' not in results[0]:
                    print(UI.status("搜索完成，整合结果中...", "success"), flush=True)

                    # 构建搜索上下文
                    search_context = "\n\n[网络搜索结果]:\n"
                    for i, r in enumerate(results, 1):
                        search_context += f"{i}. {r['title']}\n"
                        search_context += f"   {r['url']}\n"
                        if r.get('snippet'):
                            search_context += f"   {r['snippet']}\n"
                        search_context += "\n"

        # 显示思考状态
        print(UI.status("思考中...", "working"), flush=True)

        try:
            # 构建消息
            messages = [{"role": "system", "content": """你是 ReviewAgent，一个专业的昇腾 NPU 代码审查助手。

你的专长:
- 代码审查和优化建议
- 昇腾 NPU / CANN / torch_npu 相关问题
- PyTorch 和 MindSpore 框架
- 性能优化和问题诊断

回答要求:
- 简洁专业，直击要点
- 给出具体可行的建议
- 必要时提供代码示例
"""}]

            # 添加历史（最近 3 轮）
            for msg in self.conversation_history[-6:]:
                messages.append(msg)

            # 当前消息（带搜索上下文）
            user_message = user_input
            if search_context:
                user_message += search_context

            messages.append({"role": "user", "content": user_message})

            # 调用 AI
            response = self.ai_client.chat_with_history(messages, temperature=0.7, max_tokens=800)

            # 清除思考状态
            print("\r" + " " * 50 + "\r", end='', flush=True)

            # 格式化输出
            print(
                f"\n{colored(G.BAR, Style.BRAND)} {bold(colored('ReviewAgent', Style.BRAND))}\n"
                f"{response}\n"
            )

            # 保存历史
            self.conversation_history.append({"role": "user", "content": user_input})
            self.conversation_history.append({"role": "assistant", "content": response})

        except Exception as e:
            print(UI.status(f"响应失败: {e}", "error"))

    def process_input(self, user_input: str):
        """处理用户输入"""
        user_input = user_input.strip()

        if not user_input:
            return

        # 检查命令
        cmd = self.parse_command(user_input)
        if cmd:
            if cmd == 'exit':
                print(UI.status("再见！", "info"))
                sys.exit(0)
            elif cmd == 'help':
                self.handle_help()
            elif cmd == 'clear':
                self.conversation_history = []
                print(UI.status("对话历史已清除", "success"))
            elif cmd == 'config':
                self.setup_wizard()
            elif cmd == 'switch_model':
                self.switch_model()
            elif cmd == 'stats':
                self.handle_stats()
            elif cmd == 'search':
                query = user_input[8:].strip()  # /search 之后的内容
                if query:
                    self.handle_search(query)
                else:
                    print(UI.status("请提供搜索关键词: /search <query>", "error"))
            return

        # 理解意图
        intent_result = self.understand_intent(user_input)
        intent = intent_result['intent']

        print(dim(f"[检测到: {intent}, 置信度: {intent_result['confidence']:.0%}]"), flush=True)

        # 执行操作
        try:
            if intent in ['review_code', 'review_request']:
                self.handle_review_code(user_input)
            elif intent == 'fetch_url':
                # 使用统一 fetcher。
                # 原来写的是 entities['urls']，但 entities 这个变量根本不存在
                # （understand_intent 把链接放在返回值的 'urls' 里），
                # 一旦走到这条分支就 NameError。改为从 intent_result 取。
                self.handle_fetch_and_review(intent_result.get('urls') or [])
            elif intent == 'need_search':
                # 明确的搜索请求
                query = user_input.replace('搜索', '').replace('search', '').strip()
                if query:
                    self.handle_search(query)
                else:
                    print(UI.status("请提供搜索关键词", "error"))
            elif intent == 'question_maybe_search':
                # 可能需要搜索的问题，让 AI 自动判断
                self.handle_chat(user_input, with_search=True)
            else:
                # 普通对话
                self.handle_chat(user_input, with_search=False)
        except Exception as e:
            print(UI.status(f"处理失败: {e}", "error"))

    def multiline_input(self, prompt: str) -> str:
        """支持多行输入"""
        print(prompt, end='', flush=True)
        lines = []

        try:
            while True:
                line = input()

                # 空行结束（两次回车）
                if not line and lines:
                    break

                lines.append(line)

        except EOFError:
            pass

        return '\n'.join(lines)

    def run(self, show_banner=True):
        """运行主循环"""
        # 初始化
        self.initialize()

        # 显示欢迎
        if show_banner:
            self.show_welcome()
        else:
            # 简化版欢迎
            print()
            print(f"  {colored(G.BAR, Style.ACCENT)} {bold('快速开始')}")
            print(UI.bullet('粘贴代码 → 直接审查'))
            print(UI.bullet('发送 GitHub / Gitee 链接 → 分析 PR / Issue'))
            print(UI.bullet('提问昇腾 NPU 相关问题'))
            print()
            print(f"  {colored(G.BAR, Style.ACCENT)} {bold('命令')}  "
                  + dim('/help /clear /config /stats /exit'))
            print()
            print(f"  {dim('提示：多行内容按两次回车提交')}")
            print()

        # 主循环
        while True:
            try:
                # 提示符
                prompt = f"  {colored(G.PROMPT, Style.ACCENT)} "

                # 读取第一行
                first_line = input(prompt).strip()

                if not first_line:
                    continue

                # 检查是否需要多行输入
                user_input = first_line

                # 如果包含代码开始标记，或者是长文本，支持多行
                if '```' in first_line or len(first_line) > 100:
                    print(dim("  (继续输入，按两次回车提交)"))
                    more_lines = []
                    try:
                        while True:
                            line = input(dim("  ... "))
                            if not line:  # 空行结束
                                break
                            more_lines.append(line)
                    except EOFError:
                        pass

                    if more_lines:
                        user_input = first_line + '\n' + '\n'.join(more_lines)

                print()  # 空行
                self.process_input(user_input)
                print()  # 空行

            except KeyboardInterrupt:
                print(f"\n\n{dim('提示: 使用 /exit 退出')}\n")
            except EOFError:
                print(UI.status("\n再见！", "info"))
                break

    def run_without_welcome(self):
        """运行主循环（不显示完整欢迎信息）"""
        self.run(show_banner=False)


# ============================================================================
# 主函数
# ============================================================================

def main():
    """主函数"""
    _configure_console()
    try:
        agent = ReviewAgentChat()
        agent.run()
    except Exception as e:
        print(UI.status(f"启动失败: {e}", "error"))
        sys.exit(1)


if __name__ == '__main__':
    main()

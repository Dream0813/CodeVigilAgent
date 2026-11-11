"""CodeVigil Agent — Windows 桌面版。

为什么不用 Electron / Web：
    这台机器的 Python 是精简版，没有 tkinter 的是 WorkBuddy 自带的那个；
    用户自己装的 D:\\python 有 tkinter。用标准库就能做出原生窗口，
    不下载任何依赖，双击即用。

为什么输出区字体用「新宋体」而不是 Consolas：
    宋体这类东亚字体里 ASCII 是半角、汉字是全角，宽度严格 1:2，
    CLI 那道「补空格对齐」的边框才能对齐。换成 Consolas，
    中文走系统回退字体，比例不是 2，框线就会歪。

为什么要把 REVIEWAGENT_RENDER 设成 pad：
    CLI 里那套「光标定位」是给真终端用的，ANSI 序列塞进 Text 组件
    只会显示成乱码。所以这里强制走补空格路径。
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)

import ansi_term  # noqa: E402

# ---------------------------------------------------------------- 主题
BG = '#0f1117'
PANEL = '#171a22'
PANEL_HI = '#1f232d'
BORDER = '#2a2f3a'
FG = '#e6e9ef'
FG_DIM = '#8b93a1'
ACCENT = '#5eead4'
ACCENT_DIM = '#2dd4bf'
DANGER = '#f87171'

MONO_CANDIDATES = ['新宋体', 'NSimSun', 'Sarasa Mono SC', 'Consolas']
CONFIG_PATH = os.path.join(os.path.expanduser('~'), '.reviewagent', 'ai_config.json')


def pick_mono_font(root: tk.Tk, size: int = 11) -> tuple:
    """挑一个「中文两格宽」的等宽字体，保证框线对齐。"""
    families = set(tkfont.families(root))
    for name in MONO_CANDIDATES:
        if name in families:
            return (name, size)
    return ('Courier New', size)


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.proc: subprocess.Popen | None = None
        self.q: queue.Queue = queue.Queue()
        self.repo = tk.StringVar(value=self._last_repo())
        self.status = tk.StringVar(value='就绪')
        self.font_ui = ('Microsoft YaHei UI', 11)
        self.font_mono = pick_mono_font(root, 12)

        root.title('CodeVigil Agent')
        root.geometry('1200x860')
        root.minsize(900, 600)
        root.configure(bg=BG)
        # 4K / 高 DPI 屏上，窗口高度会被系统压到逻辑 700 以内，
        # 底部输入行正好被裁掉一截。直接最大化，避免和 DPI 换算较劲。
        try:
            root.state('zoomed')
        except Exception:
            pass

        self._build()
        self._pump()
        self._welcome()

    # ------------------------------------------------------------ 布局
    def _build(self) -> None:
        outer = tk.Frame(self.root, bg=BG)
        outer.pack(fill='both', expand=True, padx=16, pady=14)
        # 用 grid 而不是 pack：pack 在高 DPI 屏上会把最后加入的控件
        # 挤出可视区域（输入行因此看不见）。grid 按行列分配，可靠得多。
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)      # 第 3 行（输出区）吃掉多余高度

        # ---- 顶部标题 ----
        head = tk.Frame(outer, bg=BG)
        head.grid(row=0, column=0, sticky='ew')
        tk.Label(head, text='CodeVigil Agent', bg=BG, fg=ACCENT,
                 font=('Microsoft YaHei UI', 20, 'bold')).pack(side='left')
        tk.Label(head, text='昇腾 AI Infra 代码审查与问题诊断', bg=BG, fg=FG_DIM,
                 font=('Microsoft YaHei UI', 10)).pack(side='left', padx=(14, 0), pady=(8, 0))
        tk.Label(head, textvariable=self.status, bg=BG, fg=FG_DIM,
                 font=('Microsoft YaHei UI', 9)).pack(side='right', pady=(10, 0))

        # ---- 仓库行 ----
        repo_row = tk.Frame(outer, bg=BG)
        repo_row.grid(row=1, column=0, sticky='ew', pady=(14, 0))
        tk.Label(repo_row, text='仓库', bg=BG, fg=FG_DIM,
                 font=self.font_ui).pack(side='left')
        self.repo_entry = tk.Entry(
            repo_row, textvariable=self.repo, bg=PANEL, fg=FG, insertbackground=FG,
            relief='flat', font=self.font_ui, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT_DIM,
        )
        self.repo_entry.pack(side='left', fill='x', expand=True, padx=10, ipady=6)
        self._button(repo_row, '选择目录', self.pick_repo, accent=True).pack(side='left')

        # ---- 操作行 ----
        act = tk.Frame(outer, bg=BG)
        act.grid(row=2, column=0, sticky='ew', pady=(10, 0))
        self.btn_review = self._button(act, '审查当前改动', self.review)
        self.btn_review.pack(side='left')
        self.btn_offline = self._button(act, '离线审查', self.offline_review)
        self.btn_offline.pack(side='left', padx=8)
        self._button(act, '模型设置', self.open_settings).pack(side='left')
        self.btn_cancel = self._button(act, '取消', self.cancel, danger=True)
        self.btn_cancel.pack(side='left', padx=8)
        self.btn_cancel.config(state='disabled')
        self._button(act, '清空输出', self.clear).pack(side='right')

        # ---- 输入行（先占底部，避免被输出区挤出去）----
        chat = tk.Frame(outer, bg=BG)
        chat.grid(row=4, column=0, sticky='ew', pady=(10, 0))
        self.entry = tk.Entry(
            chat, bg=PANEL, fg=FG, insertbackground=FG, relief='flat',
            font=self.font_ui, highlightthickness=1,
            highlightbackground=BORDER, highlightcolor=ACCENT_DIM,
        )
        self.entry.pack(side='left', fill='x', expand=True, ipady=7)
        self.entry.bind('<Return>', lambda _e: self.send())
        self._button(chat, '发送', self.send, accent=True).pack(side='left', padx=(8, 0))

        # ---- 输出区（占掉剩下的全部高度）----
        box = tk.Frame(outer, bg=BORDER)
        box.grid(row=3, column=0, sticky='nsew', pady=(10, 0))
        inner = tk.Frame(box, bg=PANEL)
        inner.pack(fill='both', expand=True, padx=1, pady=1)

        self.txt = tk.Text(
            inner, bg=PANEL, fg=FG, insertbackground=FG, relief='flat',
            font=self.font_mono, wrap='none', padx=12, pady=10,
            spacing1=1, spacing3=1, undo=False, state='normal',
        )
        vsb = ttk.Scrollbar(inner, orient='vertical', command=self.txt.yview)
        hsb = ttk.Scrollbar(inner, orient='horizontal', command=self.txt.xview)
        self.txt.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        vsb.pack(side='right', fill='y')
        hsb.pack(side='bottom', fill='x')
        self.txt.pack(side='left', fill='both', expand=True)

        self.txt.tag_config('dim', foreground=FG_DIM)
        self.txt.tag_config('accent', foreground=ACCENT)
        self.txt.tag_config('err', foreground=DANGER)
        self.txt.tag_config('bold', font=(self.font_mono[0], self.font_mono[1], 'bold'))

        self.entry.focus_set()

    def _button(self, parent, text, cmd, accent=False, danger=False):
        bg = PANEL_HI
        fg = ACCENT if accent else (DANGER if danger else FG)
        btn = tk.Button(
            parent, text=text, command=cmd, bg=bg, fg=fg, relief='flat',
            font=self.font_ui, padx=14, pady=6, cursor='hand2',
            activebackground=BG, activeforeground=fg, borderwidth=0,
        )
        btn.bind('<Enter>', lambda _e: btn.config(bg=BG))
        btn.bind('<Leave>', lambda _e: btn.config(bg=PANEL_HI if btn['state'] == 'normal' else PANEL))
        return btn

    # ------------------------------------------------------------ 输出
    def append(self, text: str, tag: str | None = None) -> None:
        if not text:
            return
        for seg, color, bold in ansi_term.parse(text):
            tags = []
            if color:
                name = 'c_' + color.replace('#', '')
                self.txt.tag_config(name, foreground=color)
                tags.append(name)
            if bold:
                tags.append('bold')
            if tag and not tags:
                tags.append(tag)
            self.txt.insert('end', seg, tuple(tags) if tags else ())
        self.txt.see('end')

    def _welcome(self) -> None:
        cfg = self.load_config()
        model = (cfg or {}).get('model') or '未配置'
        self.append('欢迎使用 CodeVigil Agent。\n', 'accent')
        self.append(f'当前模型：{model}\n', 'dim')
        self.append('选择 Git 仓库后点「审查当前改动」；或在底部输入问题直接对话。\n\n', 'dim')

    def clear(self) -> None:
        self.txt.delete('1.0', 'end')

    def set_status(self, text: str) -> None:
        self.status.set(text)

    # ------------------------------------------------------------ 交互
    def pick_repo(self) -> None:
        path = filedialog.askdirectory(title='选择要审查的 Git 仓库目录')
        if path:
            self.repo.set(os.path.normpath(path))
            self._save_last_repo(path)

    def review(self) -> None:
        self._run_review(offline=False)

    def offline_review(self) -> None:
        self._run_review(offline=True)

    def _run_review(self, offline: bool) -> None:
        repo = self.repo.get().strip()
        if not repo or not os.path.isdir(repo):
            messagebox.showwarning('仓库无效', '请先选择一个存在的目录。')
            return
        args = [self._python(), os.path.join(ROOT, 'ascend_cli.py'), 'review']
        if offline:
            args.append('--offline')
        self._start(args, cwd=repo, label='离线审查' if offline else '审查当前改动')

    def send(self) -> None:
        text = self.entry.get().strip()
        if not text:
            return
        self.entry.delete(0, 'end')
        repo = self.repo.get().strip()
        args = [self._python(), os.path.join(ROOT, 'ascend_cli.py'),
                'chat', '--message', text, '--network', 'auto']
        if repo and os.path.isdir(repo):
            args += ['--repository', repo]
        self._start(args, cwd=ROOT, label='提问')

    def cancel(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self.append('\n[已请求取消]\n', 'err')

    # ------------------------------------------------------------ 子进程
    def _python(self) -> str:
        """用当前解释器 —— 启动器保证它带 tkinter，子进程也用它。"""
        return sys.executable

    def _start(self, args: list, cwd: str, label: str) -> None:
        if self.proc and self.proc.poll() is None:
            messagebox.showinfo('正在运行', '上一个任务还没结束，先点「取消」。')
            return

        env = os.environ.copy()
        env['PYTHONIOENCODING'] = 'utf-8'
        env['PYTHONUTF8'] = '1'
        env['PYTHONPATH'] = ROOT + os.pathsep + env.get('PYTHONPATH', '')
        # 文本框里没有终端光标，定位序列只会变乱码，强制走补空格对齐
        env['REVIEWAGENT_RENDER'] = 'pad'
        creation = 0x08000000 if os.name == 'nt' else 0   # CREATE_NO_WINDOW

        self.append(f'\n── {label} ' + '─' * 40 + '\n', 'accent')
        try:
            self.proc = subprocess.Popen(
                args, cwd=cwd, env=env,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding='utf-8', errors='replace',
                bufsize=1, creationflags=creation,
            )
        except Exception as exc:                       # noqa: BLE001
            self.append(f'启动失败：{exc}\n', 'err')
            return

        threading.Thread(target=self._reader, args=(self.proc,), daemon=True).start()
        self.set_status(f'{label} 运行中…')
        self.btn_cancel.config(state='normal')

    def _reader(self, proc: subprocess.Popen) -> None:
        try:
            for line in proc.stdout:                    # type: ignore[union-attr]
                self.q.put(('out', line))
        except Exception as exc:                       # noqa: BLE001
            self.q.put(('out', f'\n读取输出出错：{exc}\n'))
        finally:
            self.q.put(('done', proc.wait()))

    def _pump(self) -> None:
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == 'out':
                    self.append(payload)
                else:
                    code = payload
                    if code == 0:
                        self.append('\n── 完成 ──\n', 'accent')
                        self.set_status('就绪')
                    else:
                        self.append(f'\n── 结束（退出码 {code}）──\n', 'err')
                        self.set_status(f'结束，退出码 {code}')
                    self.btn_cancel.config(state='disabled')
        except queue.Empty:
            pass
        self.root.after(40, self._pump)

    # ------------------------------------------------------------ 配置
    def load_config(self) -> dict:
        try:
            with open(CONFIG_PATH, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            return {}

    def _last_repo(self) -> str:
        try:
            with open(os.path.join(HERE, 'last_repo.txt'), encoding='utf-8') as fh:
                return fh.read().strip()
        except Exception:
            return ''

    def _save_last_repo(self, path: str) -> None:
        try:
            with open(os.path.join(HERE, 'last_repo.txt'), 'w', encoding='utf-8') as fh:
                fh.write(path)
        except Exception:
            pass

    def open_settings(self) -> None:
        cfg = self.load_config()
        win = tk.Toplevel(self.root)
        win.title('模型设置')
        win.configure(bg=BG)
        win.geometry('560x360')
        win.transient(self.root)
        win.grab_set()

        fields = [
            ('provider', '服务商', cfg.get('provider', 'deepseek')),
            ('model', '模型 ID', cfg.get('model', 'deepseek-flash')),
            ('base_url', 'base_url（可空）', cfg.get('base_url', '')),
            ('api_key', 'API Key', cfg.get('api_key', '')),
        ]
        entries = {}
        for i, (key, label, value) in enumerate(fields):
            tk.Label(win, text=label, bg=BG, fg=FG_DIM, font=self.font_ui,
                     anchor='w').place(x=24, y=24 + i * 62, width=140)
            e = tk.Entry(win, bg=PANEL, fg=FG, insertbackground=FG, relief='flat',
                         font=self.font_ui, highlightthickness=1,
                         highlightbackground=BORDER, highlightcolor=ACCENT_DIM,
                         show='*' if key == 'api_key' else '')
            e.insert(0, str(value or ''))
            e.place(x=176, y=22 + i * 62, width=340, height=32)
            entries[key] = e

        def save():
            data = {k: entries[k].get().strip() for k in entries}
            try:
                os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
                with open(CONFIG_PATH, 'w', encoding='utf-8') as fh:
                    json.dump(data, fh, ensure_ascii=False, indent=2)
                self.append(f'\n配置已保存 → {CONFIG_PATH}\n', 'accent')
                win.destroy()
            except Exception as exc:                   # noqa: BLE001
                messagebox.showerror('保存失败', str(exc))

        self._button(win, '保存', save, accent=True).place(x=176, y=286, width=110, height=36)
        self._button(win, '取消', win.destroy).place(x=300, y=286, width=110, height=36)
        tk.Label(win, text=CONFIG_PATH, bg=BG, fg=FG_DIM,
                 font=('Microsoft YaHei UI', 8)).place(x=24, y=330)


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()

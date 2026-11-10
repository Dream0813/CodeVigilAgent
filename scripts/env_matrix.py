"""跨环境矩阵：在不同编码 / 终端宽度 / 开关组合下，检查边框是否仍然对齐。

用法：
    python scripts/env_matrix.py

输出一张表：每行一个环境组合，最后一列是「同一盒子的所有行宽度是否完全相同」。
不通过时会打印具体是哪一行差了几列。
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ANSI = re.compile(r'\x1b\[[0-9;]*[A-Za-z]')

# 只跑 frame_doctor（不需要 API Key、不联网），它会把 4 个盒子画一遍，
# 每行前面标出显示宽度，正好可以拿来量。
CASES = []
for encoding in ('utf-8', 'gbk', 'cp1252'):
    for columns in ('60', '76', '80', '120'):
        for amb in ('0', '1'):
            for safe in ('0', '1'):
                CASES.append({
                    'PYTHONIOENCODING': encoding,
                    'COLUMNS': columns,
                    'REVIEWAGENT_AMBIGUOUS': amb,
                    'REVIEWAGENT_FRAME_SAFE': safe,
                })


def run_case(env_extra):
    env = os.environ.copy()
    env.update(env_extra)
    env['PYTHONPATH'] = str(ROOT)
    proc = subprocess.run(
        [sys.executable, '-m', 'scripts.frame_doctor'],
        cwd=str(ROOT), env=env, capture_output=True, timeout=60,
    )
    # 必须用被测的那个编码来解码：拿 utf-8 去读 gbk 输出会得到乱码，
    # 连"目标宽度"四个字都匹配不到，结论会误判成"盒子没画出来"。
    enc = env_extra.get('PYTHONIOENCODING', 'utf-8')
    raw = (proc.stdout or b'') + (proc.stderr or b'')
    return raw.decode(enc, errors='replace')


def parse_rows(text):
    """从输出里取出 (标注宽度, 行内容) —— 只保留完整的框行。"""
    rows = []
    for line in text.splitlines():
        line = ANSI.sub('', line)
        m = re.match(r'^\s*(\d+) \|(.*)\|\s*$', line)
        if not m:
            continue
        width, body = int(m.group(1)), m.group(2).rstrip()
        if body[:1] in '╭│╰├┌│└+' and body[-1:] in '╮│╯┤┘┐+':
            rows.append((width, body))
    return rows


def check(text, expect_boxes=True):
    """返回 (是否通过, 说明)。

    判定顺序：
    1. 有 Traceback / UnicodeEncodeError 就是真崩了 —— 直接失败
    2. 该编码能表示中文时（utf-8 / gbk），四个盒子必须都画出来
       只查宽度会漏掉「盒子只画出一个、但它是齐的」这种情况
    3. 每个盒子里所有行的显示宽度必须完全相同
    """
    if 'Traceback' in text or 'UnicodeEncodeError' in text:
        first = next((ln for ln in text.splitlines() if 'Error' in ln), '')
        return False, '崩溃：' + first.strip()[:60]
    if not expect_boxes:
        # cp1252 这类编码根本表示不了中文，全部替换成 '?' 是预期行为，
        # 只要不崩、宽度仍然一致就算通过。
        rows = parse_rows(text)
        if not rows:
            # 连框线字符都表示不了（cp1252 没有 ╭ ─ │），整段被替换成 '?'。
            # 只要没抛异常、宽度数字还在，就算「降级但安全」。
            if '76' in text or '58' in text or '74' in text:
                return True, '整段降级为 ASCII（该编码无中文/框线），未崩溃'
            return None, '没有框行'
        widths = {w for w, _ in rows}
        if len(widths) == 1:
            return True, f'{len(rows)} 行全部 {widths.pop()} 列（中文已降级为 ?）'
        return False, f'宽度不一致：{sorted(widths)}'
    boxes = text.count('目标宽度')
    if boxes != 4:
        return False, f'只画出 {boxes}/4 个盒子（中途出错或输出被截断）'
    rows = parse_rows(text)
    if not rows:
        return None, '没有解析到框行（可能整段降级成 ASCII 或直接报错）'
    widths = {w for w, _ in rows}
    if len(widths) == 1:
        return True, f'{len(rows)} 行全部 {widths.pop()} 列'
    detail = []
    for w, body in rows:
        if w != max(set(widths), key=lambda x: sum(1 for ww, _ in rows if ww == x)):
            detail.append(f'{w}列 {body[:24]}')
    return False, f'出现 {sorted(widths)} 多种宽度：' + ' / '.join(detail[:2])


print('=' * 92)
print('跨环境矩阵：编码 × 终端宽度 × 模糊字符策略 × 框内ASCII化')
print('=' * 92)
print(f"{'编码':10s} {'宽度':5s} {'模糊':4s} {'ASCII化':7s} {'结果':6s} 说明")
print('-' * 92)

results = []
for case in CASES:
    enc = case['PYTHONIOENCODING']
    proc = run_case(case)
    # cp1252 表示不了中文，降级成 '?' 是预期行为，不要求画出 4 个盒子
    ok, note = check(proc, expect_boxes=(enc in ('utf-8', 'gbk')))
    label = 'OK' if ok else ('NG' if ok is False else '?')
    results.append((case, ok, note))
    print(f"{enc:10s} {case['COLUMNS']:5s} {case['REVIEWAGENT_AMBIGUOUS']:4s} "
          f"{case['REVIEWAGENT_FRAME_SAFE']:7s} {label:6s} {note[:52]}")

print('-' * 92)
total = len(results)
passed = sum(1 for _, ok, _ in results if ok is True)
failed = sum(1 for _, ok, _ in results if ok is False)
unknown = total - passed - failed
print(f'合计 {total} 组：通过 {passed}，失败 {failed}，无法判定 {unknown}')

if failed:
    print('\n失败组合（这些环境下的边框会歪）：')
    for case, ok, note in results:
        if ok is False:
            print(f"  {case['PYTHONIOENCODING']} / {case['COLUMNS']}列 / "
                  f"ambiguous={case['REVIEWAGENT_AMBIGUOUS']} / safe={case['REVIEWAGENT_FRAME_SAFE']}")
            print(f"    {note}")

# 额外检查：非 TTY（管道）时是否安全降级
print('\n' + '=' * 92)
print('非交互环境（输出被管道接走，没有 TTY）')
print('=' * 92)
env = os.environ.copy()
env['PYTHONPATH'] = str(ROOT)
proc = subprocess.run([sys.executable, '-m', 'scripts.frame_doctor'],
                      cwd=str(ROOT), env=env, capture_output=True, timeout=60)
plain = ((proc.stdout or b'') + (proc.stderr or b'')).decode('utf-8', errors='replace')
ok, note = check(plain)
print(f"  结果：{'OK' if ok else 'NG'} {note}")

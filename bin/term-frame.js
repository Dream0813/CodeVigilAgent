/**
 * 终端字符宽度 / 盒子几何 —— Node 侧唯一真相。
 *
 * 与 scripts/term_frame.py 保持**逐条对应**：改这里就要同步改那边，
 * 否则 Python 画的框和 Node 画的框会差列。
 *
 * 为什么需要它：`string-width`（boxen 用的）把 EAW=A 的字符（● · → ◆ …）
 * 一律算 2 列，而中文 Windows 控制台对其中一部分按 1 列渲染。
 * 两边算法不一致 → 右边框被顶出框外。
 */

/** EAW=A 的字符按几列算。默认 2（中文控制台回退宋体时按全角画）。 */
function ambiguousWide() {
  const v = (process.env.REVIEWAGENT_AMBIGUOUS || '').trim().toLowerCase();
  if (['0', 'narrow', 'false', 'no'].includes(v)) return false;
  return true;
}

let AMB_WIDE = ambiguousWide();

const ANSI_RE = /\x1b\[[0-9;]*[A-Za-z]/g;

function stripAnsi(text) {
  return String(text == null ? '' : text).replace(ANSI_RE, '');
}

/** 单宽字体里必然窄的非 ASCII 字符：按 1 列 */
const NARROW_CHARS = new Set(['\u2018', '\u2019', '\u201c', '\u201d']);

// 宽度区间表由 scripts/gen_width_table.py 从 Python unicodedata 生成，
// 保证 Node 和 Python 算出来的宽度逐码点一致（手写过一版，BMP 里错了 8144 个）。
const TABLE = require('./width-table');

function inRanges(o, ranges) {
  let lo = 0;
  let hi = ranges.length - 1;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    const [a, b] = ranges[mid];
    if (o < a) hi = mid - 1;
    else if (o > b) lo = mid + 1;
    else return true;
  }
  return false;
}

function charWidth(ch) {
  const o = ch.codePointAt(0);
  if (ch === '\t') return 4;
  if (o < 0x20 || o === 0x7f) return 0;
  if (o < 0x7f) return 1;
  if (inRanges(o, TABLE.BOX_DRAWING)) return 1;        // ─ │ ╭ ╮ ╰ ╯
  if (NARROW_CHARS.has(ch)) return 1;
  if (inRanges(o, TABLE.NARROW_OVERRIDE)) return 1;
  if (inRanges(o, TABLE.ZERO)) return 0;
  if (inRanges(o, TABLE.WIDE)) return 2;
  if (inRanges(o, TABLE.AMBIGUOUS)) return AMB_WIDE ? 2 : 1;
  return 1;
}

function displayWidth(text) {
  let n = 0;
  for (const ch of stripAnsi(text)) n += charWidth(ch);
  return n;
}

function padDisplay(text, width) {
  const gap = width - displayWidth(text);
  return gap > 0 ? text + ' '.repeat(gap) : text;
}

function truncateDisplay(text, width, ellipsis = '...') {
  if (displayWidth(text) <= width) return text;
  const budget = Math.max(width - displayWidth(ellipsis), 0);
  let out = '';
  let acc = 0;
  for (const ch of stripAnsi(text)) {
    const w = charWidth(ch);
    if (acc + w > budget) return out + ellipsis;
    out += ch;
    acc += w;
  }
  return out;
}

function tokens(text) {
  const out = [];
  let pos = 0;
  const raw = String(text == null ? '' : text);
  ANSI_RE.lastIndex = 0;
  let m;
  while ((m = ANSI_RE.exec(raw)) !== null) {
    for (const ch of raw.slice(pos, m.index)) out.push([ch, charWidth(ch)]);
    out.push([m[0], 0]);
    pos = m.index + m[0].length;
  }
  for (const ch of raw.slice(pos)) out.push([ch, charWidth(ch)]);
  return out;
}

function wrapDisplay(text, width) {
  width = Math.max(1, width);
  if (!text) return [''];
  const lines = [];
  let cur = [];
  let curW = 0;
  for (const [tok, w] of tokens(text)) {
    if (w === 0) { cur.push([tok, w]); continue; }
    if (curW + w <= width) { cur.push([tok, w]); curW += w; continue; }
    let spaceAt = -1;
    for (let i = cur.length - 1; i >= 0; i--) {
      if (cur[i][0] === ' ') { spaceAt = i; break; }
    }
    if (spaceAt > 0) {
      const head = cur.slice(0, spaceAt);
      const tail = cur.slice(spaceAt + 1);
      lines.push(head.map(([t]) => t).join('').replace(/\s+$/, ''));
      cur = tail.concat([[tok, w]]);
      curW = tail.reduce((s, [, x]) => s + x, 0) + w;
      continue;
    }
    if (cur.length) {
      lines.push(cur.map(([t]) => t).join('').replace(/\s+$/, ''));
      cur = [[tok, w]];
      curW = w;
      continue;
    }
    cur.push([tok, w]);
    curW += w;
  }
  if (cur.length) lines.push(cur.map(([t]) => t).join('').replace(/\s+$/, ''));
  return lines.length ? lines : [''];
}

// ---------------------------------------------------------------------------
// 盒子几何
// ---------------------------------------------------------------------------

const MIN_TOTAL = 44;
const MAX_TOTAL = 76;

function totalWidth() {
  const cols = process.stdout.columns || 80;
  return Math.max(MIN_TOTAL, Math.min(cols - 2, MAX_TOTAL));
}

function contentWidth(total) {
  return Math.max(10, (total || totalWidth()) - 4);
}

function clipTitle(title, limit) {
  return truncateDisplay(title, Math.max(4, limit));
}

function fixTail(line, total) {
  const diff = total - displayWidth(line);
  if (diff > 0) return line.slice(0, -1) + '─'.repeat(diff) + line.slice(-1);
  if (diff < 0) return line.slice(0, line.length - 1 + diff) + line.slice(-1);
  return line;
}

function topBorder(title = '', total = 0) {
  total = total || totalWidth();
  const inner = total - 2;
  if (!title) return '╭' + '─'.repeat(inner) + '╮';
  const seg = ' ' + clipTitle(title, inner - 8) + ' ';
  const dashes = Math.max(2, inner - 3 - displayWidth(seg));
  return fixTail('╭─' + seg + '─'.repeat(dashes) + '╮', total);
}

function bottomBorder(note = '', total = 0) {
  total = total || totalWidth();
  const inner = total - 2;
  if (!note) return '╰' + '─'.repeat(inner) + '╯';
  const seg = ' ' + clipTitle(note, inner - 8) + ' ';
  const dashes = Math.max(2, inner - 3 - displayWidth(seg));
  return fixTail('╰─' + seg + '─'.repeat(dashes) + '╯', total);
}

function rowLines(text = '', total = 0, indent = '') {
  total = total || totalWidth();
  const avail = contentWidth(total);
  const bodyWidth = Math.max(1, avail - displayWidth(indent));
  const out = [];
  for (const [i, part] of wrapDisplay(text || '', bodyWidth).entries()) {
    const lead = i === 0 ? indent : ' '.repeat(displayWidth(indent));
    let body = frameSafe(lead + part);
    if (displayWidth(body) > avail) body = truncateDisplay(body, avail);
    out.push('│ ' + padDisplay(body, avail) + ' │');
  }
  if (!out.length) out.push('│ ' + ' '.repeat(avail) + ' │');
  return out;
}

function blankRow(total = 0) {
  total = total || totalWidth();
  return '│ ' + ' '.repeat(contentWidth(total)) + ' │';
}

function hr(total = 0) {
  return '─'.repeat((total || totalWidth()) - 2);
}

/**
 * 把「模糊宽度」字符换成等宽 ASCII。
 *
 * 为什么要在框内做这件事：`· ● ◆ → …` 属于 EAW=A，不同终端/字体
 * 一个按 1 列画、一个按 2 列画 —— 世界上没有任何算法能同时满足两边。
 * 换成 ASCII 后宽度**确定是 1 列**，边框永远不会歪。
 * 颜色不动，所以观感还在。
 */
const SAFE_MAP = [
  ['\u00b7', '|'],   // · 中点
  ['\u2022', '|'],   // • 项目符号
  ['\u25cf', '*'],   // ●
  ['\u25c6', '*'],   // ◆
  ['\u25c7', '*'],   // ◇
  ['\u258c', '|'],   // ▌
  ['\u2192', '->'],  // →
  ['\u2190', '<-'],  // ←
  ['\u2026', '...'], // …
  ['\u2014', '-'],   // —
  ['\u2013', '-'],   // –
  ['\u201c', '"'], ['\u201d', '"'],
  ['\u2018', "'"], ['\u2019', "'"],
  ['\u2460', '(1)'], ['\u2461', '(2)'], ['\u2462', '(3)'],
  ['\u2463', '(4)'], ['\u2464', '(5)'], ['\u2465', '(6)'],
  ['\u2466', '(7)'], ['\u2467', '(8)'], ['\u2468', '(9)'],
  ['\u00d7', 'x'],       // ×
  ['\u2605', '*'], ['\u2606', '*'],    // ★ ☆
  ['\u2726', '*'], ['\u2727', '*'],    // ✦ ✧
  ['\u2191', '^'], ['\u2193', 'v'],    // ↑ ↓
  ['\u2139', 'i'],       // ℹ
  ['\u26a0', '!'],       // ⚠
];

function frameSafe(text) {
  const v = (process.env.REVIEWAGENT_FRAME_SAFE || '').trim().toLowerCase();
  if (['0', 'off', 'false', 'no'].includes(v)) return String(text == null ? '' : text);
  let out = String(text == null ? '' : text);
  for (const [from, to] of SAFE_MAP) out = out.split(from).join(to);
  return out;
}

/**
 * 自检：三条边宽度必须相等。REVIEWAGENT_FRAME_DEBUG=1 时把问题打到 stderr。
 * 返回 true 表示对齐。
 */
function checkFrame(title, lines, total = 0) {
  total = total || totalWidth();
  const ws = lines.map((l) => displayWidth(l));
  const bad = ws.filter((w) => w !== total);
  if (bad.length) {
    if ((process.env.REVIEWAGENT_FRAME_DEBUG || '') === '1') {
      process.stderr.write(
        `[frame] 宽度不齐 title=${JSON.stringify(title)} 应为 ${total}，实际 ${JSON.stringify(ws)}\n`,
      );
    }
    return false;
  }
  return true;
}

module.exports = {
  ambiguousWide,
  stripAnsi,
  charWidth,
  displayWidth,
  padDisplay,
  truncateDisplay,
  wrapDisplay,
  totalWidth,
  contentWidth,
  topBorder,
  bottomBorder,
  rowLines,
  blankRow,
  hr,
  frameSafe,
  checkFrame,
  MIN_TOTAL,
  MAX_TOTAL,
};

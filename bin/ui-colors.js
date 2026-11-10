/**
 * Shared terminal colors + sleep (no heavy deps cycle).
 *
 * 关键点：chalk v5 是 ESM-only，`require('chalk')` 会抛 ERR_REQUIRE_ESM，
 * 所以必须有降级路径。降级时必须保证每个颜色项**一定是函数**——
 * 之前用 Proxy 兜底，`chalk.hex('#00C2A8')` 被代理成「返回入参字符串」，
 * 于是 c.brand 变成了字符串 '#00C2A8'，调用 c.brand(ch) 直接崩
 * 「c.brand is not a function」。
 */
const identity = (s) => (s === undefined || s === null ? '' : String(s));

/** 造一个「有内容就原样返回」的假 chalk */
function makeFallbackChalk() {
  const fake = {
    hex: () => identity,
    rgb: () => identity,
    bold: identity,
    dim: identity,
    italic: identity,
    underline: identity,
    red: identity,
    green: identity,
    yellow: identity,
    blue: identity,
    magenta: identity,
    cyan: identity,
    white: identity,
    gray: identity,
    grey: identity,
    black: identity,
    reset: identity,
  };
  // 任何没列到的属性（chalk 的链式 API）也返回 identity，保证句柄可调用
  return new Proxy(fake, {
    get(target, prop) {
      if (prop in target) return target[prop];
      if (prop === 'level') return 0;
      return identity;
    },
  });
}

let chalk;
try {
  chalk = require('chalk');
  if (!chalk || typeof chalk.hex !== 'function') chalk = makeFallbackChalk();
} catch {
  chalk = makeFallbackChalk();
}

/**
 * 取一个颜色函数。若 chalk.hex(...) 没返回函数（降级环境），
 * 自动退回到 16 色同名颜色，再不行就退到 identity。
 */
function pickColor(hexValue, fallbackName) {
  if (typeof chalk.hex === 'function') {
    const made = chalk.hex(hexValue);
    if (typeof made === 'function') return made;
  }
  const fb = chalk[fallbackName];
  if (typeof fb === 'function') return fb;
  return identity;
}

const c = {
  brand: pickColor('#00C2A8', 'cyan'),
  accent: pickColor('#FF8FAB', 'magenta'),
  glow: pickColor('#7EE8D0', 'cyan'),
  ink: typeof chalk.white === 'function' ? chalk.white : identity,
  mute: typeof chalk.gray === 'function' ? chalk.gray : identity,
  ok: typeof chalk.green === 'function' ? chalk.green : identity,
  warn: typeof chalk.yellow === 'function' ? chalk.yellow : identity,
};

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

module.exports = { chalk, c, sleep, identity };

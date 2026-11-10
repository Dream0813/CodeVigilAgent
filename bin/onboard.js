/**
 * First-run API setup wizard (Claude Code–style guided onboarding).
 */
const fs = require('fs');
const { homeDir, configPath, readConfig, c, boxen, spinner, sleep, tf, frameCard } = require('./ui');
const { react } = require('./buddy');

let inquirer;
try {
  inquirer = require('inquirer');
} catch {
  inquirer = null;
}

// 字形降级：conhost + 宋体不含 ✦ ❯ ✕ ✎ › ✓，会显示成方块 □
// 用 REVIEWAGENT_GLYPHS=fancy|safe 可强制指定
const FANCY = (() => {
  const o = String(process.env.REVIEWAGENT_GLYPHS || '').toLowerCase();
  if (o === 'fancy') return true;
  if (o === 'safe') return false;
  if (process.platform !== 'win32') return true;
  // Windows 一律保守：终端类型判断不可靠，用户也可能给 WT 配了宋体。
  // 想用花哨符号：set REVIEWAGENT_GLYPHS=fancy
  return false;
})();

const G = {
  spark: FANCY ? '✦' : '◆',
  prompt: FANCY ? '❯' : '>',
  close: FANCY ? '✕' : '×',
  pencil: FANCY ? '✎' : '·',
  sep: FANCY ? '›' : '>',
  ok: FANCY ? '✓' : '√',
};

/**
 * OpenAI-compatible catalogs (saved as provider=openai + base_url).
 *
 * 2026-11 校准：DeepSeek 官方已下线 deepseek-chat / deepseek-reasoner / deepseek-v3.x，
 * 现在只接受 deepseek-flash 与 deepseek-v4-pro（其他名字会返回
 * HTTP 400 invalid_request_error）。列表里不要再放旧名字，否则用户选了必崩。
 */
const PROVIDERS = [
  {
    name: 'DeepSeek',
    value: 'deepseek',
    hint: 'platform.deepseek.com',
    models: [
      'deepseek-flash',
      'deepseek-v4-pro',
    ],
  },
  {
    name: 'OpenAI / 兼容网关（中转、本地、vLLM）',
    value: 'openai',
    hint: '可自定义 base_url',
    openaiCompat: true,
    models: [
      'gpt-4o',
      'gpt-4o-mini',
      'gpt-4.1',
      'gpt-4.1-mini',
      'gpt-4.1-nano',
      'gpt-4-turbo',
      'gpt-4',
      'o1',
      'o1-mini',
      'o1-pro',
      'o3',
      'o3-mini',
      'o4-mini',
      'gpt-3.5-turbo',
    ],
  },
  {
    name: 'Claude (Anthropic)',
    value: 'claude',
    hint: 'console.anthropic.com',
    models: [
      'claude-opus-4-20250514',
      'claude-sonnet-4-20250514',
      'claude-3-7-sonnet-20250219',
      'claude-3-5-sonnet-20241022',
      'claude-3-5-haiku-20241022',
      'claude-3-opus-20240229',
      'claude-3-sonnet-20240229',
      'claude-3-haiku-20240307',
    ],
  },
  {
    name: 'Google Gemini',
    value: 'gemini',
    hint: 'aistudio.google.com · OpenAI 兼容',
    openaiCompat: true,
    defaultBase: 'https://generativelanguage.googleapis.com/v1beta/openai/',
    models: [
      'gemini-2.5-pro',
      'gemini-2.5-flash',
      'gemini-2.5-flash-lite',
      'gemini-2.0-flash',
      'gemini-2.0-flash-lite',
      'gemini-1.5-pro',
      'gemini-1.5-flash',
      'gemini-1.5-flash-8b',
      'gemini-exp-1206',
    ],
  },
  {
    name: 'xAI Grok（马斯克）',
    value: 'xai',
    hint: 'console.x.ai',
    openaiCompat: true,
    defaultBase: 'https://api.x.ai/v1',
    models: [
      'grok-4',
      'grok-4-latest',
      'grok-3',
      'grok-3-mini',
      'grok-3-fast',
      'grok-3-mini-fast',
      'grok-2',
      'grok-2-latest',
      'grok-2-vision-1212',
      'grok-beta',
    ],
  },
  {
    name: 'MiniMax',
    value: 'minimax',
    hint: 'platform.minimaxi.com · 对话请选 Text/M1，勿选 VL',
    openaiCompat: true,
    defaultBase: 'https://api.minimax.chat/v1',
    models: [
      'MiniMax-M1',
      'MiniMax-Text-01',
      'abab6.5s-chat',
      'abab6.5-chat',
      'abab6.5g-chat',
      'abab6.5t-chat',
      'abab5.5s-chat',
      'abab5.5-chat',
    ],
  },
  {
    name: '通义千问 Qwen（阿里）',
    value: 'qwen',
    hint: 'dashscope.aliyun.com',
    openaiCompat: true,
    defaultBase: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    models: [
      'qwen-max',
      'qwen-max-latest',
      'qwen-plus',
      'qwen-plus-latest',
      'qwen-turbo',
      'qwen-turbo-latest',
      'qwen-long',
      'qwen-coder-plus',
      'qwen-coder-turbo',
      'qwen2.5-72b-instruct',
      'qwen2.5-32b-instruct',
      'qwen2.5-14b-instruct',
      'qwen2.5-7b-instruct',
      'qwen2.5-coder-32b-instruct',
      'qwq-32b',
      'qwq-plus',
      'qwen3-235b-a22b',
      'qwen3-32b',
      'qwen3-14b',
      'qwen3-8b',
      'qwen-vl-max',
      'qwen-vl-plus',
    ],
  },
  {
    name: '豆包 Doubao（字节跳动）',
    value: 'doubao',
    hint: 'volcengine.com 火山方舟',
    openaiCompat: true,
    defaultBase: 'https://ark.cn-beijing.volces.com/api/v3',
    models: [
      'doubao-seed-1.6',
      'doubao-seed-1.6-flash',
      'doubao-seed-1.6-thinking',
      'doubao-1.5-pro-32k',
      'doubao-1.5-lite-32k',
      'doubao-1.5-thinking-pro',
      'doubao-pro-32k',
      'doubao-pro-128k',
      'doubao-lite-32k',
      'doubao-lite-128k',
      'doubao-vision-pro-32k',
    ],
  },
  {
    name: '混元 Hunyuan（腾讯）',
    value: 'hunyuan',
    hint: 'cloud.tencent.com/hunyuan',
    openaiCompat: true,
    defaultBase: 'https://api.hunyuan.cloud.tencent.com/v1',
    models: [
      'hunyuan-lite',
      'hunyuan-standard',
      'hunyuan-standard-256K',
      'hunyuan-pro',
      'hunyuan-turbo',
      'hunyuan-turbo-latest',
      'hunyuan-large',
      'hunyuan-large-longcontext',
      'hunyuan-role',
      'hunyuan-functioncall',
      'hunyuan-code',
      'hunyuan-vision',
    ],
  },
  {
    name: '智谱 GLM',
    value: 'glm',
    hint: 'open.bigmodel.cn',
    models: [
      'glm-4',
      'glm-4-plus',
      'glm-4-air',
      'glm-4-airx',
      'glm-4-flash',
      'glm-4-flashx',
      'glm-4-long',
      'glm-4-0520',
      'glm-4v',
      'glm-4v-plus',
      'glm-z1-air',
      'glm-z1-airx',
      'glm-z1-flash',
      'glm-3-turbo',
    ],
  },
  {
    name: 'Kimi (Moonshot)',
    value: 'kimi',
    hint: 'platform.moonshot.cn',
    openaiCompat: true,
    defaultBase: 'https://api.moonshot.cn/v1',
    models: [
      'moonshot-v1-8k',
      'moonshot-v1-32k',
      'moonshot-v1-128k',
      'kimi-latest',
      'kimi-thinking-preview',
      'kimi-k2-0711-preview',
    ],
  },
  {
    name: '硅基流动 SiliconFlow',
    value: 'siliconflow',
    hint: 'cloud.siliconflow.cn · 多模型/开源聚合',
    openaiCompat: true,
    defaultBase: 'https://api.siliconflow.cn/v1',
    models: [
      'deepseek-ai/DeepSeek-V3',
      'deepseek-ai/DeepSeek-R1',
      'MiniMaxAI/MiniMax-M1-80k',
      'Qwen/Qwen2.5-72B-Instruct',
      'Qwen/QwQ-32B',
      'Qwen/Qwen3-235B-A22B',
      'THUDM/GLM-4-9B-0414',
      'google/gemma-3-27b-it',
      'meta-llama/Llama-3.3-70B-Instruct',
      'Pro/deepseek-ai/DeepSeek-V3',
      'Pro/deepseek-ai/DeepSeek-R1',
    ],
  },
];

function ensureHome() {
  const home = homeDir();
  if (!fs.existsSync(home)) fs.mkdirSync(home, { recursive: true });
  return home;
}

function writeConfig(data) {
  ensureHome();
  const target = configPath();
  const prev = readConfig() || {};
  const next = { ...prev, ...data };
  fs.writeFileSync(target, `${JSON.stringify(next, null, 2)}\n`, 'utf8');
  return target;
}

/** Native adapters vs OpenAI-compatible HTTP (need base_url). */
const NATIVE = new Set(['deepseek', 'openai', 'claude', 'glm']);

function normalizeProvider(provider, meta) {
  if (meta && meta.openaiCompat && provider !== 'openai') {
    return { fileProvider: 'openai', logical: provider };
  }
  if (!NATIVE.has(provider)) {
    return { fileProvider: 'openai', logical: provider };
  }
  return { fileProvider: provider, logical: provider };
}

// ---------------------------------------------------------------------------
// 向导视觉小工具（美化层：清屏 + 步骤条 + 已选摘要）
// ---------------------------------------------------------------------------

const BACK = '__back__';
const EXIT = '__exit__';

/**
 * 输入屏（自定义模型 / base_url / API Key）是文本框，inquirer 塞不进"可选中项"，
 * 所以约定两个词：< 退回上一步，q 退出配置。
 * 两条出路都直接写在提示行里，不让人猜。
 */
const QUIT_TOKENS = new Set(['q', 'quit', 'exit', '退出', '放弃']);
const INPUT_HINT = () => c.mute('   · < 退回上一步   · q 退出配置（不写入）');

function isQuitInput(v) {
  return QUIT_TOKENS.has(String(v || '').trim().toLowerCase());
}

/**
 * 全局 Esc = 退出配置。
 * 文本框屏没有任何列表可选，但 Esc 是所有终端里通行的"取消"键，
 * 一个键就能脱身，不用记着 Ctrl+C。
 * 返回卸载函数；非 TTY（重定向、CI）时什么都不做。
 */
function attachEsc(onCancel) {
  if (!process.stdin.isTTY) return () => {};
  const handler = (chunk, key) => {
    if (key && key.name === 'escape') onCancel();
  };
  try {
    require('readline').emitKeypressEvents(process.stdin);
    process.stdin.on('keypress', handler);
  } catch {
    return () => {};
  }
  return () => {
    try {
      process.stdin.removeListener('keypress', handler);
    } catch {
      /* 忽略：stdin 已关闭 */
    }
  };
}

/** 清屏（TTY 才清，重定向到文件时保持原文，方便抓取对比图） */
function clearScreen() {
  if (!process.stdout.isTTY) return;
  process.stdout.write('\x1b[2J\x1b[H');
}

/** 把已选项目压成一行 chips */
function pairLine(pairs) {
  if (!pairs.length) return c.mute('还没有选择任何项目');
  return pairs.map(([k, v]) => `${c.mute(k)} ${c.brand(v)}`).join(c.mute('  ' + G.sep + '  '));
}

/** 每个步骤顶部的迷你横幅 */
function wizardBanner(pairs, stepLabel) {
  const bar = stepLabel ? `${c.accent(stepLabel)}  ${c.mute('─────')}  ` : '';
  return (
    `\n  ${c.accent(G.spark)} ${c.brand('ReviewAgent')} ${c.mute('配置向导')}    ${bar}\n` +
    `  ${c.mute('已选')}  ${pairLine(pairs)}\n` +
    `  ${c.mute(tf.hr())}\n`
  );
}

function showWelcome() {
  console.log(
    frameCard(
      '首次配置',
      `${c.accent(G.spark + ' 欢迎使用 ReviewAgent')}\n\n` +
        `${c.mute('像 Claude Code 一样，先完成 API 配置。')}\n` +
        `${c.mute('密钥只保存在本机：')}${c.brand(configPath())}\n\n` +
        `${c.brand('①')} ${c.mute('服务商')}    ${c.brand('②')} ${c.mute('模型')}    ` +
        `${c.brand('③')} ${c.mute('密钥')}\n\n` +
        `${c.mute('走错了怎么办')}\n` +
        `  ${c.accent('← 返回上一步')}  ${c.mute('列表里选中，或输入')} ${c.accent('<')}\n` +
        `  ${c.accent(G.close + ' 退出配置')}  ${c.mute('列表里选中，或按')} ${c.accent('Esc')}` +
        `${c.mute('、输入')} ${c.accent('q')}\n` +
        `  ${c.mute('怎么退都不写盘，密钥只存本机')}`,
      'magenta',
    ),
  );
}

function cancelWizard() {
  console.log();
  console.log(
    `  ${c.warn(G.close + ' 已取消配置')}  ${c.mute('没有写入任何设置，下次运行会重新询问。')}`,
  );
  console.log();
  return false;
}

async function runOnboarding() {
  showWelcome();

  if (!inquirer) {
    console.log(c.warn('缺少 inquirer，请运行: npm install'));
    console.log(c.mute('或手动编辑'), configPath());
    return false;
  }

  let provider = null;
  let meta = null;
  let model = null;
  let base_url = '';
  let api_key = '';
  let stage = 'provider';

  // 退出统一出口：恢复光标 → 打印取消说明 → 以失败码退出
  let leaving = false;
  const bail = () => {
    if (leaving) return;
    leaving = true;
    if (process.stdout.isTTY) process.stdout.write('\x1b[?25h');
    cancelWizard();
    process.exit(1);
  };
  const detachEsc = attachEsc(bail);
  const onSigint = () => bail();
  process.once('SIGINT', onSigint);

  // 内部退出（列表屏选中"退出配置"）：同一套收尾，但不强杀进程
  const quit = () => {
    detachEsc();
    process.removeListener('SIGINT', onSigint);
    return cancelWizard();
  };

  /** 需要填 base_url 的供应商多一步 */
  const needsBase = (m) => Boolean(m && (m.openaiCompat || m.defaultBase));
  const stepLabel = (n, m) =>
    m ? `第 ${n} 步 / 共 ${needsBase(m) ? 4 : 3} 步` : `第 ${n} 步`;

  const base = { pageSize: 16, loop: false, prefix: c.brand(G.prompt) };

  while (true) {
    // ---- 第 1 步：服务商 ----------------------------------------------------
    if (stage === 'provider') {
      clearScreen();
      process.stdout.write(wizardBanner([], stepLabel(1)));
      const { pick } = await inquirer.prompt([
        {
          ...base,
          type: 'list',
          name: 'pick',
          message: c.brand('选择模型提供商') + c.mute('（↑↓ 移动，回车确认，Esc 退出）'),
          choices: [
            ...PROVIDERS.map((p) => ({
              name: `${p.name}  ${c.mute(p.hint)}`,
              value: p.value,
            })),
            new inquirer.Separator(),
            { name: c.mute(G.close + '  退出配置（不写入）'), value: EXIT },
          ],
        },
      ]);
      if (pick === EXIT) return quit();
      provider = pick;
      meta = PROVIDERS.find((p) => p.value === provider);
      // 从确认页退回重选时，上一轮的填写结果必须清空 ——
      // 新服务商若不需要 base_url，旧值会被一起写进配置。
      model = null;
      base_url = '';
      api_key = '';
      stage = 'model';
      continue;
    }

    // ---- 第 2 步：模型 ------------------------------------------------------
    if (stage === 'model') {
      clearScreen();
      process.stdout.write(wizardBanner([['服务商', meta.name]], stepLabel(2, meta)));
      const { pick } = await inquirer.prompt([
        {
          ...base,
          type: 'list',
          name: 'pick',
          message:
            c.brand('选择模型') + c.mute('（↑↓ 移动，回车确认，Esc 退出）'),
          choices: [
            ...meta.models.map((m) => ({ name: m, value: m })),
            new inquirer.Separator(),
            { name: c.mute(G.pencil + '  自定义模型 ID…'), value: '__custom__' },
            { name: c.accent('←  返回上一步（重选服务商）'), value: BACK },
            { name: c.mute(G.close + '  退出配置（不写入）'), value: EXIT },
          ],
        },
      ]);
      if (pick === BACK) {
        stage = 'provider';
        continue;
      }
      if (pick === EXIT) return quit();
      if (pick === '__custom__') {
        stage = 'modelCustom';
        continue;
      }
      model = pick;
      stage = meta.openaiCompat || meta.defaultBase ? 'base' : 'key';
      continue;
    }

    // ---- 第 2 步补充：自定义模型 ID -----------------------------------------
    if (stage === 'modelCustom') {
      clearScreen();
      process.stdout.write(wizardBanner([['服务商', meta.name]], stepLabel(2, meta)));
      const ans = await inquirer.prompt([
        {
          prefix: c.brand(G.prompt),
          type: 'input',
          name: 'model',
          message: c.brand('自定义模型 ID') + c.mute('（豆包等填接入点 ep-xxx）'),
          suffix: INPUT_HINT(),
          validate: (v) => {
            const s = String(v || '').trim();
            if (isQuitInput(s)) return true;
            if (!s) return '不能为空（输入 < 返回，q 退出）';
            return true;
          },
        },
      ]);
      const v = String(ans.model || '').trim();
      if (isQuitInput(v)) return quit();
      if (v === '<') {
        stage = 'model';
        continue;
      }
      model = v;
      stage = meta.openaiCompat || meta.defaultBase ? 'base' : 'key';
      continue;
    }

    // ---- 第 3 步（可能是最后一步）：base_url --------------------------------
    if (stage === 'base') {
      clearScreen();
      process.stdout.write(
        wizardBanner(
          [
            ['服务商', meta.name],
            ['模型', model],
          ],
          stepLabel(3, meta),
        ),
      );
      const ans = await inquirer.prompt([
        {
          prefix: c.brand(G.prompt),
          type: 'input',
          name: 'base_url',
          message: c.brand('OpenAI 兼容 base_url'),
          default: meta.defaultBase || 'https://api.openai.com/v1',
          suffix: INPUT_HINT(),
        },
      ]);
      const v = String(ans.base_url || '').trim();
      if (isQuitInput(v)) return quit();
      if (v === '<') {
        stage = 'model';
        continue;
      }
      base_url = v;
      stage = 'key';
      continue;
    }

    // ---- 最后一步：API Key --------------------------------------------------
    if (stage === 'key') {
      clearScreen();
      process.stdout.write(
        wizardBanner(
          [
            ['服务商', meta.name],
            ['模型', model],
            ...(base_url ? [['base_url', base_url]] : []),
          ],
          stepLabel(base_url ? 4 : 3, meta),
        ),
      );
      const { api_key: key } = await inquirer.prompt([
        {
          prefix: c.brand(G.prompt),
          type: 'password',
          name: 'api_key',
          message:
            c.brand('API Key') + c.mute('（输入时隐藏，粘贴后回车）'),
          mask: FANCY ? '✦' : '*',
          suffix: INPUT_HINT(),
          validate: (v) => {
            const s = String(v || '').trim();
            if (isQuitInput(s) || s === '<') return true;
            if (!s || s === 'YOUR_API_KEY_HERE')
              return '请填写真实 API Key（输入 < 返回，q 退出）';
            if (s.length < 8) return 'Key 太短，请检查（输入 < 返回，q 退出）';
            return true;
          },
        },
      ]);
      const v = String(key || '').trim();
      if (isQuitInput(v)) return quit();
      if (v === '<') {
        stage = base_url ? 'base' : 'model';
        continue;
      }
      api_key = v;
      stage = 'confirm';
      continue;
    }

    // ---- 保存前确认：填完了还能反悔 ----------------------------------------
    // 之前填完 Key 就直接写盘，发现选错了只能整体重跑（reviewagent config -w）。
    // 这里补一个摘要 + 退回入口。
    if (stage === 'confirm') {
      clearScreen();
      const summary = [
        ['服务商', `${meta.name} → ${provider}`],
        ['模型', model],
      ];
      if (base_url) summary.push(['base_url', base_url]);
      summary.push(['密钥', '已填写（不显示）']);
      process.stdout.write(wizardBanner(summary, '确认'));

      const { action } = await inquirer.prompt([
        {
          ...base,
          type: 'list',
          name: 'action',
          message: c.brand('配置是否正确？') + c.mute('（↑↓ 选择，回车确认）'),
          choices: [
            { name: c.ok('✓  保存并启动'), value: 'save' },
            new inquirer.Separator(),
            { name: `${c.accent('←')}  改 API Key`, value: 'key' },
            { name: `${c.accent('←')}  改模型`, value: 'model' },
            { name: `${c.accent('←')}  改服务商`, value: 'provider' },
            new inquirer.Separator(),
            { name: c.mute(G.close + '  退出配置（不写入）'), value: EXIT },
          ],
        },
      ]);

      if (action === EXIT) return quit();
      if (action === 'save') break;
      stage = action;
      continue;
    }
  }

  // 收集完毕：摘掉 Esc / Ctrl+C 的取消钩子，避免写盘过程中被误触打断
  detachEsc();
  process.removeListener('SIGINT', onSigint);

  const spin = spinner('buddy 正在把配置藏进本机…');
  spin.start();
  await sleep(420);
  const { fileProvider } = normalizeProvider(provider, meta);
  const saved = writeConfig({
    provider: fileProvider,
    model,
    api_key,
    base_url: base_url || '',
    label: provider,
  });
  spin.succeed(c.ok(`配置已保存 → ${saved}`));
  await react('hop');

  console.log(
    frameCard(
      '',
      `${c.ok(G.ok + ' 配置完成')}   ${c.mute('改错了重新跑：')}${c.brand('reviewagent config -w')}\n\n` +
        `${c.mute('服务商')}    ${c.brand(provider)} ${c.mute('→')} ${c.mute(fileProvider)}\n` +
        `${c.mute('模型')}      ${c.brand(model)}\n` +
        (base_url ? `${c.mute('base_url')}  ${c.mute(base_url)}\n` : '') +
        `${c.mute('密钥')}      ${c.ok('已写入本机，不显示')}\n` +
        `\n${c.accent('正在启动 Agent…')}`,
      'cyan',
    ),
  );
  await sleep(280);
  return true;
}

module.exports = { runOnboarding, writeConfig, PROVIDERS, G };

/**
 * 验证「保存前确认页」：填完 Key 之后能不能退回上一步。
 *
 * 用 mock inquirer 模拟按键序列，REVIEWAGENT_HOME 重定向到临时目录，
 * 绝不碰用户的真实配置。
 */
const path = require('path');
const fs = require('fs');
const os = require('os');
const Module = require('module');

const ROOT = path.join(__dirname, '..');
const tmpHome = path.join(os.tmpdir(), 'ra-confirm-' + Date.now());
fs.mkdirSync(tmpHome, { recursive: true });
process.env.REVIEWAGENT_HOME = tmpHome;
process.env.REVIEWAGENT_COLORS = '0';

let queue = [];
let asked = [];

const SEP = class Separator {
  constructor(s) { this.s = s; this.isSeparator = true; }
};
const fakeInquirer = {
  Separator: SEP,
  prompt: async (qs) => {
    const q = qs[0];
    const next = queue.shift();
    if (next === undefined) throw new Error(`题目用完了，卡在: ${q.message}`);
    asked.push(`${q.name}=${next}`);
    if (q.validate) {
      const r = q.validate(next);
      if (r !== true) throw new Error(`validate 拒绝 "${next}": ${r}`);
    }
    return { [q.name]: next };
  },
};
const origLoad = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === 'inquirer') return fakeInquirer;
  return origLoad.apply(this, arguments);
};

// 屏蔽界面输出，只保留断言信息
const realWrite = process.stdout.write.bind(process.stdout);
process.stdout.write = () => true;
const log = (...a) => realWrite(a.join(' ') + '\n');

process.chdir(ROOT);
const { runOnboarding } = require(path.join(ROOT, 'bin/onboard.js'));

async function run(name, answers) {
  queue = answers.slice();
  asked = [];
  const ok = await runOnboarding();
  return { ok, asked };
}

function configFile() {
  return path.join(tmpHome, 'ai_config.json');
}

(async () => {
  let pass = 0, fail = 0;
  const check = (label, cond, extra = '') => {
    if (cond) { pass++; log(`  ✓ ${label}`); }
    else { fail++; log(`  ✗ ${label} ${extra}`); }
  };

  // ---------- 场景 1：一路直行，确认页选「保存」 ----------
  log('\n【场景 1】DeepSeek 直行 → 确认页保存');
  await run('save', ['deepseek', 'deepseek-flash', 'sk-test-key-12345678', 'save']);
  check('出现了确认页', asked.some((a) => a.startsWith('action=')),
        JSON.stringify(asked));
  const cfg1 = JSON.parse(fs.readFileSync(configFile(), 'utf8'));
  check('写入了 deepseek / deepseek-flash',
        cfg1.provider === 'deepseek' && cfg1.model === 'deepseek-flash',
        JSON.stringify(cfg1));
  check('未把确认页的 action 写进配置', !('action' in cfg1));

  // ---------- 场景 2：确认页退回改模型 ----------
  log('\n【场景 2】确认页 → 改模型 → 再保存');
  await run('back-model', [
    'deepseek', 'deepseek-flash', 'sk-test-key-11111111',
    'model',                                  // 确认页退回改模型
    'deepseek-v4-pro', 'sk-test-key-22222222',
    'save',
  ]);
  const cfg2 = JSON.parse(fs.readFileSync(configFile(), 'utf8'));
  check('模型已改成 deepseek-v4-pro', cfg2.model === 'deepseek-v4-pro', JSON.stringify(cfg2));
  check('密钥用的是最后一次输入', cfg2.api_key === 'sk-test-key-22222222',
        cfg2.api_key);
  check('确认页被问了两次',
        asked.filter((a) => a.startsWith('action=')).length === 2,
        JSON.stringify(asked));

  // ---------- 场景 3：确认页退回重选服务商，旧的 base_url 必须被清掉 ----------
  log('\n【场景 3】确认页 → 改服务商（DeepSeek → OpenAI）');
  await run('back-provider', [
    'deepseek', 'deepseek-flash', 'sk-test-key-33333333',
    'provider',                               // 确认页退回重选服务商
    'openai', 'gpt-4o', 'https://api.example.com/v1', 'sk-test-key-44444444',
    'save',
  ]);
  const cfg3 = JSON.parse(fs.readFileSync(configFile(), 'utf8'));
  check('服务商/模型/base 都换成了 OpenAI',
        cfg3.provider === 'openai' && cfg3.model === 'gpt-4o'
        && cfg3.base_url === 'https://api.example.com/v1',
        JSON.stringify(cfg3));

  // ---------- 场景 4：确认页选退出，不应写盘 ----------
  log('\n【场景 4】确认页 → 退出（不写入）');
  const before = fs.readFileSync(configFile(), 'utf8');
  await run('exit', ['deepseek', 'deepseek-flash', 'sk-test-key-55555555', '__exit__']);
  const after = fs.readFileSync(configFile(), 'utf8');
  check('配置文件未被修改', before === after);

  // ---------- 场景 5：Key 步骤输入 < 退回 ----------
  log('\n【场景 5】Key 输入时敲 < 退回上一步');
  await run('lt-key', [
    'deepseek', 'deepseek-flash',
    '<',                                      // Key 步骤退回
    'deepseek-flash', 'sk-test-key-66666666',
    'save',
  ]);
  const cfg5 = JSON.parse(fs.readFileSync(configFile(), 'utf8'));
  check('退回后重新走完流程并保存', cfg5.api_key === 'sk-test-key-66666666',
        JSON.stringify(cfg5));

  log(`\n================  通过 ${pass}  失败 ${fail}  ================`);
  process.exit(fail ? 1 : 0);
})().catch((e) => {
  log('\n✗ 测试抛出异常：' + e.message);
  log(e.stack);
  process.exit(1);
});

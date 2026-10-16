/**
 * Worker 集成测试：真实 SQLite 模拟 D1，验证方案 B 后端逻辑
 */
const Database = require('better-sqlite3');
const fs = require('fs');
const path = require('path');

const PROJECT = '/Users/leo/教育平权项目/05-后端原型';
const DB_PATH = '/tmp/d1test/test.db';

/* ---------- 1. 载入 contract.js（ESM → CJS） ---------- */
function loadContract() {
  let src = fs.readFileSync(path.join(PROJECT, 'contract.js'), 'utf8');
  src = src.replace(/export\s+const\s+/g, 'const ')
           .replace(/export\s+function\s+/g, 'function ');
  const m = { exports: {} };
  const names = ['todayStr','addDays','nextCardDue','nextErrorDue',
                 'advanceCard','regressCard','resolveErrorOnce',
                 'CARD_STEPS','ERROR_STEPS','isDue','makeId'];
  new Function('module', 'exports', src + `\nmodule.exports = {${names.join(',')}};`)(m, m.exports);
  return m.exports;
}
const C = loadContract();

/* ---------- 2. 载入 worker.js（ESM → CJS），注入 contract ---------- */
function loadWorker() {
  let src = fs.readFileSync(path.join(PROJECT, 'B-云端D1/worker.js'), 'utf8');
  // 删掉 import 块
  src = src.replace(/import\s*\{[\s\S]*?\}\s*from\s*['"][^'"]*contract\.js['"];/, '');
  src = src.replace(/export\s+default/, 'module.exports =');
  // 前置 contract 的具名绑定
  const shim = ['todayStr','addDays','nextCardDue','nextErrorDue',
                'advanceCard','regressCard','resolveErrorOnce']
    .map(n => `const ${n} = __C.${n};`).join('\n');
  const m = { exports: {} };
  new Function('module', 'exports', '__C', shim + '\n' + src)(m, m.exports, C);
  return m.exports.default || m.exports;
}
const worker = loadWorker();

/* ---------- 3. D1 兼容层 ---------- */
function makeD1(db) {
  return {
    prepare(sql) {
      const stmt = db.prepare(sql);
      let binds = [];
      const api = {
        bind(...a) { binds = a; return api; },
        async first() { return stmt.get(...binds) ?? null; },
        async all() { return { results: stmt.all(...binds) }; },
        async run() { return { success: true, meta: stmt.run(...binds) }; },
      };
      return api;
    },
    async batch(stmts) { return Promise.all(stmts.map(s => s.run())); },
  };
}

/* ---------- 4. 测试 ---------- */
let pass = 0, fail = 0;
const failures = [];
function check(name, cond, extra = '') {
  if (cond) { console.log(`  ✅ ${name}`); pass++; }
  else { console.log(`  ❌ ${name} ${extra}`); fail++; failures.push(name); }
}

const db = new Database(DB_PATH);
const env = { DB: makeD1(db) };

async function call(method, p, body, token) {
  const req = new Request('https://x' + p, {
    method,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: 'Bearer ' + token } : {}),
    },
    body: body ? JSON.stringify(body) : undefined,
  });
  const res = await worker.fetch(req, env);
  let data = null;
  try { data = await res.json(); } catch {}
  return { status: res.status, data };
}

(async () => {
  console.log('=== 方案 B 后端集成测试（真实 SQLite 模拟 D1） ===\n');

  db.exec('DELETE FROM cards; DELETE FROM errors; DELETE FROM kids; DELETE FROM sessions; DELETE FROM families;');
  db.prepare('INSERT INTO families (id,code,created_at) VALUES (?,?,?)').run('fam1', 'FAM-TEST', Date.now());

  console.log('【1】健康检查 / 合规说明');
  let r = await call('GET', '/api/health');
  check('健康检查 200', r.status === 200 && r.data?.ok === true);
  r = await call('GET', '/api/consent-notice');
  check('合规说明可读', r.status === 200 && Array.isArray(r.data?.collects));
  check('声明不收集真实姓名', (r.data?.neverCollects || []).some(x => x.includes('真实姓名')));

  console.log('\n【2】鉴权');
  r = await call('GET', '/api/kids/xxx/cards');
  check('无令牌 → 401', r.status === 401);
  r = await call('POST', '/api/login', { familyCode: 'WRONG' });
  check('错误家庭码 → 401', r.status === 401);
  r = await call('POST', '/api/login', { familyCode: 'FAM-TEST' });
  check('正确家庭码登录成功', r.status === 200 && !!r.data?.token);
  const token = r.data.token;

  console.log('\n【3】创建档案（合规：需家长同意）');
  r = await call('POST', '/api/kids', { nickname: '老大', stage: 'high' }, token);
  check('未同意 → 403', r.status === 403);
  r = await call('POST', '/api/kids', { nickname: '老大', stage: 'high', consent: true }, token);
  check('同意后创建成功', r.status === 200 && !!r.data?.id);
  const kidId = r.data.id;
  r = await call('POST', '/api/kids', { nickname: 'x', stage: 'bad', consent: true }, token);
  check('非法学段 → 400', r.status === 400);

  console.log('\n【4】知识卡');
  r = await call('POST', `/api/kids/${kidId}/cards`,
    { front: '为什么 1/2 = 2/4？', back: '分子分母同乘 2', subject: '数学' }, token);
  check('创建卡片 step=0', r.status === 200 && r.data?.step === 0);
  const cardId = r.data.id;
  r = await call('POST', `/api/kids/${kidId}/cards`, { front: '只有正面' }, token);
  check('缺背面 → 400', r.status === 400);
  r = await call('POST', `/api/kids/${kidId}/cards/${cardId}/grade`, { remembered: true }, token);
  check('答对 → step 1', r.status === 200 && r.data?.step === 1);
  r = await call('POST', `/api/kids/${kidId}/cards/${cardId}/grade`, { remembered: true }, token);
  check('再答对 → step 2', r.data?.step === 2);
  r = await call('POST', `/api/kids/${kidId}/cards/${cardId}/grade`, { remembered: false }, token);
  check('答错 → 回退 step 0', r.data?.step === 0);
  r = await call('GET', `/api/kids/${kidId}/cards`, null, token);
  check('列表返回 1 张', r.status === 200 && r.data?.length === 1);

  console.log('\n【5】错题（做对 3 次归档）');
  r = await call('POST', `/api/kids/${kidId}/errors`,
    { question: '3/4 + 1/6', thinking: '我直接分子加分子了', type: '概念不懂' }, token);
  check('记录错题 round=0', r.status === 200 && r.data?.round === 0);
  const errId = r.data.id;
  r = await call('POST', `/api/kids/${kidId}/errors/${errId}/resolve`, null, token);
  check('做对第 1 次', r.data?.round === 1 && r.data?.archived === false);
  r = await call('POST', `/api/kids/${kidId}/errors/${errId}/resolve`, null, token);
  check('做对第 2 次', r.data?.round === 2 && r.data?.archived === false);
  r = await call('POST', `/api/kids/${kidId}/errors/${errId}/resolve`, null, token);
  check('做对第 3 次 → 归档', r.data?.round === 3 && r.data?.archived === true);

  console.log('\n【6】越权防护（另一个家庭）');
  db.prepare('INSERT INTO families (id,code,created_at) VALUES (?,?,?)').run('fam2', 'FAM-OTHER', Date.now());
  r = await call('POST', '/api/login', { familyCode: 'FAM-OTHER' });
  const other = r.data.token;
  r = await call('GET', `/api/kids/${kidId}/cards`, null, other);
  check('他人家族读不到 → 404', r.status === 404);
  r = await call('POST', `/api/kids/${kidId}/cards`, { front: 'a', back: 'b' }, other);
  check('他人家族写不进 → 404', r.status === 404);

  console.log('\n【7】合规：导出 / 彻底删除');
  r = await call('GET', `/api/kids/${kidId}/export`, null, token);
  check('可全量导出', r.status === 200 && Array.isArray(r.data?.cards) && Array.isArray(r.data?.errors));
  r = await call('DELETE', `/api/kids/${kidId}`, null, token);
  check('删除成功', r.status === 200 && r.data?.deleted === true);
  const c1 = db.prepare('SELECT COUNT(*) c FROM cards WHERE kid_id=?').get(kidId).c;
  const c2 = db.prepare('SELECT COUNT(*) c FROM errors WHERE kid_id=?').get(kidId).c;
  const c3 = db.prepare('SELECT COUNT(*) c FROM kids WHERE id=?').get(kidId).c;
  check('物理删除卡片', c1 === 0);
  check('物理删除错题', c2 === 0);
  check('物理删除档案', c3 === 0);

  console.log('\n' + '='.repeat(46));
  console.log(`通过 ${pass} 项，失败 ${fail} 项`);
  if (failures.length) console.log('失败项：' + failures.join(' / '));
  console.log('='.repeat(46));
  process.exit(fail ? 1 : 0);
})();

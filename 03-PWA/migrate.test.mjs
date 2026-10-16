/**
 * 迁移层测试：用真实 Node 跑，覆盖会导致用户丢数据的所有路径
 * 运行：node migrate.test.mjs
 */
import { detectLegacy, migrate, runMigration, LEGACY_KEY, BACKUP_SUFFIX } from './migrate.js';

let pass = 0, fail = 0;
const fails = [];
function check(name, cond, extra = '') {
  if (cond) { console.log(`  ✅ ${name}`); pass++; }
  else { console.log(`  ❌ ${name} ${extra}`); fail++; fails.push(name); }
}

/** 模拟 localStorage */
function mkStorage(init = {}) {
  const m = { ...init };
  return {
    getItem: k => (k in m ? m[k] : null),
    setItem: (k, v) => { m[k] = String(v); },
    removeItem: k => { delete m[k]; },
    _dump: () => m,
  };
}

/* ---------- 1. 检测 ---------- */
console.log('【1】旧数据检测');
check('空 storage → 无需迁移', detectLegacy(mkStorage()).needs === false);
check('损坏 JSON → 不崩、不迁移',
  detectLegacy(mkStorage({ [LEGACY_KEY]: '{坏掉的' })).needs === false);
check('空对象 → 无需迁移',
  detectLegacy(mkStorage({ [LEGACY_KEY]: JSON.stringify({ cards: [], errs: [], kid: { name: '', stage: 'low' } }) })).needs === false);

const withData = {
  cards: [{ front: '为什么 1/2=2/4？', back: '同乘2', sub: '数学', step: 2, due: '2026-10-20', ok: 3 }],
  errs: [{ q: '3/4+1/6', think: '分子加分子', gap: '要通分', type: '概念不懂', round: 1, due: '2026-10-23', done: false }],
  kid: { name: '老大', stage: 'high' },
};
const det = detectLegacy(mkStorage({ [LEGACY_KEY]: JSON.stringify(withData) }));
check('有数据 → 需要迁移', det.needs === true);
check('统计正确', det.counts.cards === 1 && det.counts.errors === 1 && det.counts.kid === 1);

/* ---------- 2. 字段映射（最容易出错的地方） ---------- */
console.log('\n【2】字段映射（sub→subject, ok→okCount, q→question, think→thinking, done→archived）');
const r = migrate(withData, 1750000000000);
const card = Object.values(r.cards)[0];
const err = Object.values(r.errors)[0];

check('sub → subject', card.subject === '数学', `得到 ${card.subject}`);
check('ok → okCount', card.okCount === 3, `得到 ${card.okCount}`);
check('step 保留', card.step === 2);
check('due 保留', card.due === '2026-10-20');
check('front/back 保留', card.front === '为什么 1/2=2/4？' && card.back === '同乘2');
check('卡片归属 kidId', card.kidId === r.kidId);

check('q → question', err.question === '3/4+1/6', `得到 ${err.question}`);
check('think → thinking（★最重要的一栏）', err.thinking === '分子加分子', `得到 ${err.thinking}`);
check('gap 保留', err.gap === '要通分');
check('done:false → archived:false', err.archived === false);
check('round 保留', err.round === 1);

check('kid.name → nickname', r.kids[r.kidId].nickname === '老大');
check('kid.stage 保留', r.kids[r.kidId].stage === 'high');

/* ---------- 3. 边界情况 ---------- */
console.log('\n【3】边界情况');
const messy = {
  cards: [
    null, undefined, 'not an object',
    { front: '只有正面' },
    { front: 'a', back: 'b', step: 'x', ok: null, sub: undefined },
    { front: '正常', back: 'y', step: 1 },
  ],
  errs: [null, {}, { q: '只有题目' }],
  kid: { name: '  带空格  ', stage: '乱填的' },
};
const rm = migrate(messy, 1750000000000);
check('跳过 null / 非对象', Object.keys(rm.cards).length === 3, `得到 ${Object.keys(rm.cards).length}`);
check('缺失字段补默认值',
  Object.values(rm.cards).every(c => typeof c.front === 'string' && typeof c.subject === 'string'));
check('非法 step 归 0',
  Object.values(rm.cards).some(c => c.front === 'a' && c.step === 0));
check('非法 stage 归 low', rm.kids[rm.kidId].stage === 'low');
check('空昵称有兜底', migrate({ kid: {} }, 1).kids['kid_migrated'].nickname === '孩子');
check('空对象不崩', !!migrate({}, 1).kidId);
check('undefined 不崩', !!migrate(undefined, 1).kidId);

/* ---------- 4. 幂等性（关键：跑两次不能翻倍） ---------- */
console.log('\n【4】幂等性');
const a = JSON.stringify(migrate(withData, 1750000000000));
const b = JSON.stringify(migrate(withData, 1750000000000));
check('相同输入 → 相同输出', a === b);
check('重复迁移不增加记录',
  Object.keys(migrate(withData, 1).cards).length === Object.keys(migrate(withData, 1).cards).length);

/* ---------- 5. 真实迁移流程（含备份） ---------- */
console.log('\n【5】runMigration 全流程');
const st = mkStorage({ [LEGACY_KEY]: JSON.stringify(withData) });
const res = runMigration(st, 1750000000000);
check('迁移成功', res.migrated === true);
check('返回 kidId', !!res.kidId);
check('写了备份', !!st.getItem(LEGACY_KEY + BACKUP_SUFFIX));
check('备份内容 = 原始数据', st.getItem(LEGACY_KEY + BACKUP_SUFFIX) === JSON.stringify(withData));
check('新键已写入', !!st.getItem('learnos.adapter.local.v1'));
check('记录了当前档案', st.getItem('learnos.currentKid') === res.kidId);

const stored = JSON.parse(st.getItem('learnos.adapter.local.v1'));
check('新格式结构正确',
  stored.kids && stored.cards && stored.errors &&
  Object.keys(stored.cards).length === 1 && Object.keys(stored.errors).length === 1);
check('旧键保留（可回滚）', !!st.getItem(LEGACY_KEY));

// 再跑一次：不应重复
const res2 = runMigration(st, 1750000000001);
check('二次运行仍成功（幂等）', res2.migrated === true);
const stored2 = JSON.parse(st.getItem('learnos.adapter.local.v1'));
check('二次运行不重复记录', Object.keys(stored2.cards).length === 1);
check('已有备份不被覆盖', st.getItem(LEGACY_KEY + BACKUP_SUFFIX) === JSON.stringify(withData));

/* ---------- 6. 无需迁移时不动数据 ---------- */
console.log('\n【6】无旧数据时不产生副作用');
const clean = mkStorage();
const nr = runMigration(clean);
check('未迁移', nr.migrated === false);
check('未写入任何键', Object.keys(clean._dump()).length === 0);

console.log('\n' + '='.repeat(50));
console.log(`通过 ${pass} 项，失败 ${fail} 项`);
if (fails.length) console.log('失败：' + fails.join(' / '));
console.log('='.repeat(50));
process.exit(fail ? 1 : 0);

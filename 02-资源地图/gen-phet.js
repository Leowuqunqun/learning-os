const j = require('/tmp/phet.json');
const cats = j.categories;

// 权威顶层学科分类
const TOP = {
  4: '物理', 13: '化学', 12: '生物',
  14: '地球与空间', 15: '数学与统计'
};

// simId → 顶层学科
const simTop = {};
Object.entries(TOP).forEach(([id, label]) => {
  const t = cats[id] || {};
  const all = new Set(t.simulationIds || []);
  (t.childrenIds || []).forEach(cid => {
    const c = cats[cid] || {};
    (c.simulationIds || []).forEach(i => all.add(i));
    (c.childrenIds || []).forEach(gid => {
      const g = cats[gid] || {};
      (g.simulationIds || []).forEach(i => all.add(i));
    });
  });
  all.forEach(i => { simTop[i] = label; });
});

let all = [];
(j.projects || []).forEach(p => (p.simulations || []).forEach(s => all.push(s)));

const hasZh = all.filter(s => s.localizedSimulations && s.localizedSimulations['zh_CN']);
const zh = hasZh.filter(s => !/\.jar$/.test(s.localizedSimulations['zh_CN'].runUrl));
const javaOnly = hasZh.length - zh.length;

const by = {};
zh.forEach(s => {
  const z = s.localizedSimulations['zh_CN'];
  const title = (z.title || s.name).trim();
  const subj = simTop[s.id] || '综合';
  (by[subj] = by[subj] || []).push([title, s.name]);
});

const BASE = 'https://phet.colorado.edu/sims/html/';
const TICK = '`';

let out = '# PhET 中文可离线模拟清单（HTML5 版）\n\n';
out += '> 数据来源：PhET 官方元数据 API（含官方学科分类表），实测于 2026-10-16。\n';
out += '> 共 **' + zh.length + ' 个** HTML5 中文模拟，已排除 ' + javaOnly + ' 个无法在平板运行的遗留 Java 版。\n';
out += '> 授权 **CC BY 4.0** —— 可自由再分发、可离线、免费。\n\n';

out += '## 怎么用（3 步）\n\n';
out += '1. 在下表找到要用的模拟，记下它的**英文名**\n';
out += '2. 按下面格式拼成直链\n';
out += '3. 在 iPad Safari 打开即用 → 分享 → 「添加到主屏幕」→ 断网也能用\n\n';
out += '```\n' + BASE + '<英文名>/latest/<英文名>_zh_CN.html\n```\n\n';
out += '> 例：四则运算 → ' + BASE + 'arithmetic/latest/arithmetic_zh_CN.html\n';
out += '> （已实测返回 200，页面标题正确显示「四则运算」）\n\n';
out += '---\n\n';

Object.entries(by)
  .sort((a, b) => b[1].length - a[1].length)
  .forEach(([subj, arr]) => {
    arr.sort((a, b) => a[0].localeCompare(b[0], 'zh'));
    out += '## ' + subj + '（' + arr.length + '）\n\n';
    out += '| 中文名 | 英文名（拼直链用） |\n|---|---|\n';
    arr.forEach(([t, n]) => { out += '| ' + t + ' | ' + TICK + n + TICK + ' |\n'; });
    out += '\n';
  });

require('fs').writeFileSync('PhET中文模拟清单.md', out);
console.log('✅ 生成完成，总计', zh.length, '个');
Object.entries(by).forEach(([k, v]) => console.log('   ', k, ':', v.length));

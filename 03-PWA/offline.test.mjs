/**
 * 真实离线测试（CDP）
 * 1. 打开页面 → 等 Service Worker 装好
 * 2. 停掉服务器（网络层真实断开）
 * 3. 重新加载页面 → 应该仍然能用
 * 4. 验证数据仍在、UI 正常
 */
const PORT = 9333;
const APP = 'http://127.0.0.1:8120/index.html';

let id = 0;
const pending = new Map();

async function connect() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  let target = list.find(t => t.type === 'page');
  if (!target) {
    target = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: 'PUT' })).json();
  }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise((res) => {
    const mid = ++id;
    pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  return { send, ws };
}

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function evaluate(send, expr) {
  const r = await send('Runtime.evaluate', {
    expression: expr, returnByValue: true, awaitPromise: true,
  });
  if (r.result?.exceptionDetails) {
    throw new Error(r.result.exceptionDetails.text + ' ' +
      (r.result.exceptionDetails.exception?.description || ''));
  }
  return r.result?.result?.value;
}

(async () => {
  let pass = 0, fail = 0;
  const check = (n, c, extra = '') => {
    if (c) { console.log(`  ✅ ${n}`); pass++; }
    else { console.log(`  ❌ ${n} ${extra}`); fail++; }
  };

  const { send } = await connect();
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');

  console.log('=== 真实离线测试 ===\n');

  console.log('【1】首次加载（在线）');
  await send('Page.navigate', { url: APP });
  await sleep(6000);

  const swReady = await evaluate(send, `
    (async () => {
      if (!('serviceWorker' in navigator)) return 'no-sw-support';
      const reg = await navigator.serviceWorker.getRegistration();
      if (!reg) return 'no-registration';
      if (!reg.active) return 'no-active';
      const keys = await caches.keys();
      const c = await caches.open(keys[0]);
      const reqs = await c.keys();
      return JSON.stringify({ active: true, cacheName: keys[0], cached: reqs.length });
    })()
  `);
  console.log('    SW 状态:', swReady);
  check('Service Worker 已激活并有缓存',
    typeof swReady === 'string' && swReady.includes('"active":true'));

  // 写一些数据（验证离线后数据还在）
  console.log('\n【2】写入数据（在线状态）');
  const wrote = await evaluate(send, `
    (async () => {
      const btn = [...document.querySelectorAll('button')].find(b => b.textContent.includes('更多'));
      if (btn) btn.click();
      await new Promise(r => setTimeout(r, 400));
      if (typeof toggleKidForm === 'function') toggleKidForm(true);
      await new Promise(r => setTimeout(r, 200));
      const n = document.getElementById('kidName');
      const s = document.getElementById('kidStage');
      if (!n) return 'no-form';
      n.value = '离线测试娃'; s.value = 'high';
      await saveKid();
      await new Promise(r => setTimeout(r, 500));
      return localStorage.getItem('learnos.adapter.local.v1') ? 'saved' : 'not-saved';
    })()
  `);
  check('在线时成功写入数据', wrote === 'saved', `得到 ${wrote}`);

  /* ------- 关键步骤：真的断开网络 ------- */
  console.log('\n【3】断开网络（CDP 离线模式）');
  await send('Network.emulateNetworkConditions', {
    offline: true, latency: 0, downloadThroughput: 0, uploadThroughput: 0,
  });
  await sleep(800);
  const off = await evaluate(send, 'navigator.onLine');
  check('浏览器确认已离线', off === false, `navigator.onLine=${off}`);

  console.log('\n【4】离线状态下重新加载页面');
  await send('Page.navigate', { url: APP });
  await sleep(6000);

  const offlineState = await evaluate(send, `
    (() => {
      const body = document.body.innerText;
      return JSON.stringify({
        hasTitle: body.includes('学习操作系统'),
        hasNav: !!document.querySelector('nav button'),
        kids: document.querySelectorAll('#kidList .item').length,
        stored: !!localStorage.getItem('learnos.adapter.local.v1'),
        cards: document.getElementById('sCards')?.textContent,
      });
    })()
  `);
  console.log('    离线加载结果:', offlineState);
  const os = JSON.parse(offlineState);
  check('离线仍能加载页面', os.hasTitle === true);
  check('离线仍有导航', os.hasNav === true);
  check('离线数据仍在（未丢失）', os.stored === true);
  check('离线仍能读到档案', os.kids >= 1, `kids=${os.kids}`);

  console.log('\n【5】离线状态下写入新数据');
  const offlineWrite = await evaluate(send, `
    (async () => {
      const btn = [...document.querySelectorAll('nav button')].find(b => b.textContent.includes('错题'));
      btn.click();
      await new Promise(r => setTimeout(r, 400));
      const q = document.getElementById('eQ');
      const t = document.getElementById('eThink');
      q.value = '离线记录的错题';
      t.value = '离线时写的思路';
      await addErr();
      await new Promise(r => setTimeout(r, 600));
      return JSON.stringify({
        errs: document.querySelectorAll('#errList .item').length,
        text: document.querySelector('#errList .item .t')?.textContent || '',
      });
    })()
  `);
  console.log('    离线写入:', offlineWrite);
  const ow = JSON.parse(offlineWrite);
  check('离线仍能记录错题', ow.errs >= 1, `errs=${ow.errs}`);
  check('离线写入内容正确', ow.text.includes('离线记录的错题'));

  /* ------- 恢复网络 ------- */
  console.log('\n【6】恢复网络');
  await send('Network.emulateNetworkConditions', {
    offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
  });
  await sleep(1000);
  const on = await evaluate(send, 'navigator.onLine');
  check('网络已恢复', on === true);

  const finalState = await evaluate(send, `
    JSON.stringify({
      kids: JSON.parse(localStorage.getItem('learnos.adapter.local.v1')||'{}').kids
        ? Object.keys(JSON.parse(localStorage.getItem('learnos.adapter.local.v1')).kids).length : 0,
      errs: JSON.parse(localStorage.getItem('learnos.adapter.local.v1')||'{}').errors
        ? Object.keys(JSON.parse(localStorage.getItem('learnos.adapter.local.v1')).errors).length : 0,
    })
  `);
  console.log('    最终数据:', finalState);
  const fs2 = JSON.parse(finalState);
  check('离线期间的数据已持久化', fs2.errs >= 1, `errs=${fs2.errs}`);

  console.log('\n' + '='.repeat(48));
  console.log(`通过 ${pass} 项，失败 ${fail} 项`);
  console.log('='.repeat(48));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('测试异常:', e.message); process.exit(1); });

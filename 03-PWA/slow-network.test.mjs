/**
 * 低带宽可用性测试（CDP 网络限速）
 * ===================================
 * 为什么做：本项目的红线之一是「低配设备、低带宽可用」。
 * 但此前只测过"断网后能用"（离线），没测过"在慢网下首次加载"。
 *
 * 很多家庭的真实情况是：不是没网，而是很慢（3G / 弱 WiFi / 流量限速）。
 * 如果首屏要等 30 秒，家长会直接放弃。
 *
 * 前置：需先启动带调试端口的 Chrome 与本地服务
 *   python3 -m http.server 8150 &
 *   "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
 *     --headless=new --remote-debugging-port=9345 about:blank &
 *   node slow-network.test.mjs
 *
 * 本测试模拟：
 *   ① Slow 3G（400kbps 下载 / 400ms 延迟）—— 最差情况
 *   ② Fast 3G（1.6Mbps / 150ms）—— 常见弱网
 * 验证：页面能否在合理时间内可用。
 */
const PORT = Number(process.env.CDP_PORT || 9345);
const APP = process.env.APP_URL || 'http://127.0.0.1:8150/03-PWA/index.html';

let id = 0;
const pending = new Map();
const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function connect() {
  const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const target = list.find(t => t.type === 'page');
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej; });
  ws.onmessage = e => {
    const m = JSON.parse(e.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); }
  };
  const send = (method, params = {}) => new Promise(res => {
    const mid = ++id; pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
  return send;
}

async function evalJs(send, expr) {
  const r = await send('Runtime.evaluate', { expression: expr, returnByValue: true, awaitPromise: true });
  return r.result?.result?.value;
}

// 网络档位（CDP 单位：字节/秒）
const PROFILES = {
  'Slow 3G': { downloadThroughput: 400 * 1024 / 8, uploadThroughput: 400 * 1024 / 8, latency: 400 },
  'Fast 3G': { downloadThroughput: 1.6 * 1024 * 1024 / 8, uploadThroughput: 750 * 1024 / 8, latency: 150 },
};

(async () => {
  const send = await connect();
  await send('Page.enable');
  await send('Runtime.enable');
  await send('Network.enable');

  let pass = 0, fail = 0;
  const check = (n, c, extra = '') => {
    if (c) { console.log(`  ✅ ${n}`); pass++; }
    else { console.log(`  ❌ ${n} ${extra}`); fail++; }
  };

  console.log('=== 低带宽可用性测试 ===\n');

  for (const [name, profile] of Object.entries(PROFILES)) {
    console.log(`【${name}】下载 ${(profile.downloadThroughput * 8 / 1024).toFixed(0)} kbps，延迟 ${profile.latency}ms`);

    // 真正模拟「首次访问」：光清 HTTP 缓存不够——
    // Service Worker 仍会从 Cache Storage 直接返回，测出来是假快。
    // 必须先反注册 SW 并清空所有 storage。
    await send('Network.clearBrowserCache');
    try {
      await send('Storage.clearDataForOrigin', {
        origin: 'http://127.0.0.1:8150', storageTypes: 'all',
      });
    } catch {}
    try {
      await evalJs(send, `(async()=>{
        const rs = await navigator.serviceWorker.getRegistrations();
        for (const r of rs) await r.unregister();
        const ks = await caches.keys();
        for (const k of ks) await caches.delete(k);
        return true;
      })()`);
    } catch {}
    await send('Network.emulateNetworkConditions', { offline: false, ...profile });

    const t0 = Date.now();
    await send('Page.navigate', { url: APP });

    // 轮询直到应用真正可用（出现导航按钮）
    let ready = false, elapsed = 0;
    for (let i = 0; i < 100; i++) {
      await sleep(500);
      try {
        const ok = await evalJs(send, `!!document.querySelector('nav button')`);
        if (ok) { ready = true; elapsed = Date.now() - t0; break; }
      } catch {}
    }

    console.log(`    首屏可用耗时：${ready ? (elapsed / 1000).toFixed(1) + 's' : '超时(>50s)'}`);
    check(`${name} 下能在 15 秒内可用`, ready && elapsed < 15000,
      ready ? `实际 ${(elapsed / 1000).toFixed(1)}s` : '未就绪');

    if (ready) {
      const info = await evalJs(send, `JSON.stringify({
        nav: document.querySelectorAll('nav button').length,
        title: document.title,
        hasSw: 'serviceWorker' in navigator
      })`);
      const d = JSON.parse(info || '{}');
      check(`${name} 下导航完整（6 个）`, d.nav === 6, `实际 ${d.nav}`);
      check(`${name} 下标题正确`, d.title === '学习操作系统', d.title);
    }
    console.log('');
  }

  // 恢复网络
  await send('Network.emulateNetworkConditions', {
    offline: false, latency: 0, downloadThroughput: -1, uploadThroughput: -1,
  });

  console.log('='.repeat(50));
  console.log(`通过 ${pass} 项，失败 ${fail} 项`);
  console.log('='.repeat(50));
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('测试异常:', e.message); process.exit(1); });

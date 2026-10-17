/**
 * 离线时外链行为的回归测试
 * ==========================
 * 背景：Service Worker 的 scope 是 03-PWA/，管不到 ../docs/ 与 ../01-方法论/。
 * 所以那些页面**离线打不开**（白屏/错误页），而 App 里正好有 9 个链接指向它们。
 *
 * 核心功能（记录/复习/统计）在 App 内，离线完全可用；
 * 本测试确保：离线时点击外链**不会撞白屏**，而是给出明确提示。
 *
 * 前置：需启动 Chrome 远程调试端口，且本地服务在 8150
 *   APP_URL / CDP_PORT 可通过环境变量覆盖
 */
const PORT = Number(process.env.CDP_PORT || 9362);
const APP = process.env.APP_URL || 'http://127.0.0.1:8150/03-PWA/index.html';
let id=0; const pending=new Map(); const sleep=ms=>new Promise(r=>setTimeout(r,ms));
async function connect(){
  const l=await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
  const t=l.find(x=>x.type==='page');
  const ws=new WebSocket(t.webSocketDebuggerUrl);
  await new Promise((r,j)=>{ws.onopen=r;ws.onerror=j;});
  ws.onmessage=e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){pending.get(m.id)(m);pending.delete(m.id);}};
  return (method,params={})=>new Promise(res=>{const mid=++id;pending.set(mid,res);
    ws.send(JSON.stringify({id:mid,method,params}));});
}
const ev=async(s,x)=>{const r=await s('Runtime.evaluate',{expression:x,returnByValue:true,awaitPromise:true});
  return r.result?.result?.value;};
let pass=0,fail=0;
const check=(n,c,x='')=>{if(c){console.log('  ✅ '+n);pass++;}else{console.log('  ❌ '+n+' '+x);fail++;}};

(async()=>{
  const send=await connect();
  await send('Page.enable'); await send('Runtime.enable'); await send('Network.enable');
  await send('Page.navigate',{url:APP}); await sleep(5000);

  console.log('=== 在线状态 ===');
  const marked = await ev(send,"document.querySelectorAll('[data-needs-net]').length");
  check('外链已打标记（9 个）', marked===9, marked);
  const opOn = await ev(send,"getComputedStyle(document.querySelector('[data-needs-net]')).opacity");
  check('在线时不置灰', opOn==='1', opOn);

  // 断网
  await send('Network.emulateNetworkConditions',{offline:true,latency:0,downloadThroughput:0,uploadThroughput:0});
  await sleep(1200);

  console.log('\n=== 离线状态 ===');
  const isOff = await ev(send,"navigator.onLine");
  check('已离线', isOff===false);

  // 触发 online/offline 事件让 UI 更新
  await ev(send,"window.dispatchEvent(new Event('offline')); 1");
  await sleep(400);
  const opOff = await ev(send,"getComputedStyle(document.querySelector('[data-needs-net]')).opacity");
  check('★离线时外链置灰', parseFloat(opOff) < 0.9, opOff);
  const tip = await ev(send,"document.querySelector('[data-needs-net]').title");
  check('★离线时有悬停说明', tip.includes('需要联网'), tip);

  // 点击外链应被拦截
  const before = await ev(send,"location.href");
  await ev(send,"document.querySelector('[data-needs-net]').click(); 1");
  await sleep(800);
  const after = await ev(send,"location.href");
  check('★离线点击外链被拦截（未跳转）', before===after, `${before} → ${after}`);

  const toast = await ev(send,"document.querySelector('#toast')?.textContent || ''");
  check('★给出友好提示', toast.includes('需要联网'), toast.slice(0,30));
  check('提示说明记录不受影响', toast.includes('不影响')||toast.includes('离线也能'), toast.slice(0,40));

  // 核心功能仍可用
  await send('Page.navigate',{url:APP}); await sleep(3500);
  const appOk = await ev(send,"!!document.querySelector('nav button')");
  check('★离线时 App 核心仍可用', appOk===true);

  await send('Network.emulateNetworkConditions',{offline:false,latency:0,downloadThroughput:-1,uploadThroughput:-1});
  console.log(`\n通过 ${pass} 项，失败 ${fail} 项`);
  process.exit(fail?1:0);
})();

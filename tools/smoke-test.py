#!/usr/bin/env python3
"""
冒烟测试（Smoke Test）—— 防「静默炸掉」
==========================================
为什么需要（真实教训）：
2026-10 出现过一个致命 bug——重写复习流程时删掉了 showAnswer 函数，
但 Object.assign(window, {... showAnswer ...}) 的引用没清理。
那行在**模块加载时执行**，直接抛 ReferenceError，
中断整个模块初始化，导致 bootStore / loadDB / renderAll 全部不执行。

表现：localStorage 里数据完好，但界面上「知识卡 0、档案空」——
看起来像数据丢了，实际是代码根本没跑。

当时已有的四套审计全部漏掉：
  · migrate.test.mjs      —— Node 环境，不加载 index.html
  · audit-mobile.py       —— 只测布局，页面能渲染即通过
  · audit-reachability.py —— 只测链接可达
  · verify-deploy.py      —— 只测 HTTP 200 + 内容关键字

它们的共同盲区：**都在验证「改动本身」，没有验证「改动有没有破坏别的」**。

本脚本补上这块：加载真实页面，断言
  ① 无 JS 运行时错误（含模块解析错误）
  ② 关键函数已挂到 window（即模块执行到底了）
  ③ 应用完成初始化（数据加载 + DOM 渲染）
  ④ 核心交互可触发且不抛错

用法：
    python3 -m http.server 8150 &
    python3 tools/smoke-test.py
返回码：0 = 通过；1 = 失败
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.expanduser('~/教育平权项目')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
BASE = os.environ.get('SMOKE_BASE', 'http://127.0.0.1:8150')
PWA = f'{BASE}/03-PWA/index.html'

def required_globals():
    """
    从 index.html **自动提取**必须挂到 window 的函数名。

    为什么自动提取：手写清单会继承我的盲区。
    2026-10 就是这样漏掉了 importData —— 它被 inline onchange 调用，
    但从未加到 window，导致「导入」按钮点了完全没反应，
    而手写的检查清单里恰好没有它。

    提取来源：
      ① HTML 部分里 inline 的 onclick/onchange
      ② 模块内模板字符串中动态生成的 onclick（今日列表、档案列表等）
    """
    src = open(os.path.join(ROOT, '03-PWA', 'index.html'), encoding='utf-8').read()
    parts = src.split('<script type="module">')
    html_part = parts[0]
    mod_part = parts[1] if len(parts) > 1 else ''

    needed = set()
    for m in re.finditer(r'on(?:click|change|input)="([a-zA-Z_$][\w$]*)\s*\(', html_part):
        needed.add(m.group(1))
    for m in re.finditer(r"onclick=\\?[\"']([a-zA-Z_$][\w$]*)\(", mod_part):
        needed.add(m.group(1))
    return sorted(needed)


REQUIRED_GLOBALS = required_globals()


def run_probe(url, script, timeout=90, profile='smoke'):
    """在 headless Chrome 里加载 url 并执行 script，返回 document.title"""
    prof = f'/tmp/{profile}-{abs(hash(url)) % 99999}'
    try:
        r = subprocess.run(
            [CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
             f'--user-data-dir={prof}', '--virtual-time-budget=14000',
             '--dump-dom', url],
            capture_output=True, text=True, timeout=timeout)
        m = re.search(r'<title>([\s\S]*?)</title>', r.stdout)
        return m.group(1).strip() if m else '(无 title)'
    except subprocess.TimeoutExpired:
        return 'TIMEOUT'
    finally:
        subprocess.run(['rm', '-rf', prof], capture_output=True)


def make_fixture(name, extra_head='', extra_body=''):
    """生成一个带探针的临时页面（在 </head> 前注入，确保早于模块执行）"""
    src = open(os.path.join(ROOT, '03-PWA', 'index.html'), encoding='utf-8').read()
    path = os.path.join(ROOT, '03-PWA', f'_smoke_{name}.html')
    open(path, 'w', encoding='utf-8').write(
        src.replace('</head>', extra_head + '</head>', 1)
           .replace('</body>', extra_body + '</body>', 1))
    return path


def main():
    if not os.path.exists(os.path.join(ROOT, '03-PWA', 'index.html')):
        print('❌ 找不到 03-PWA/index.html')
        return 1

    # 检查服务是否在跑
    try:
        import urllib.request
        urllib.request.urlopen(f'{BASE}/03-PWA/index.html', timeout=5)
    except Exception as e:
        print(f'❌ 本地服务不可达（{BASE}）——请先运行：')
        print('   cd ~/教育平权项目 && python3 -m http.server 8150')
        return 1

    print('=' * 72)
    print('冒烟测试：应用能否正常启动并对外可用')
    print('=' * 72)

    passed, failed = 0, 0
    problems = []

    def check(name, ok, extra=''):
        nonlocal passed, failed
        if ok:
            print(f'  ✅ {name}')
            passed += 1
        else:
            print(f'  ❌ {name} {extra}')
            failed += 1
            problems.append(name)

    # ---------- 1. 无 JS 错误 + 关键函数存在 + 初始化完成 ----------
    print('\n【1】模块加载与初始化')
    probe_body = '''<script>
window.__errs = [];
window.addEventListener('error', e => window.__errs.push(e.message || String(e)), true);
window.addEventListener('unhandledrejection', e =>
  window.__errs.push('unhandled: ' + (e.reason && e.reason.message || e.reason)));
</script>
<script type="module">
setTimeout(() => {
  try {
    const missing = %s.filter(n => typeof window[n] !== 'function');
    const nav = document.querySelectorAll('nav button').length;
    document.title = 'SMOKE|' + JSON.stringify({
      errs: window.__errs,
      missing: missing,
      nav: nav,
      title: document.title,
      rendered: !!document.querySelector('main')
    });
  } catch (e) { document.title = 'SMOKEERR|' + e.message; }
}, 3000);
</script>''' % json.dumps(REQUIRED_GLOBALS)

    fixture = make_fixture('boot', extra_body=probe_body)
    try:
        out = run_probe(f'{BASE}/03-PWA/{os.path.basename(fixture)}', None, profile='smoke-boot')
    finally:
        os.remove(fixture)

    if out.startswith('SMOKEERR'):
        check('探针可执行', False, out)
    elif out == 'TIMEOUT':
        check('页面可加载', False, '超时')
    else:
        m = re.search(r'SMOKE\|(.*)', out, re.S)
        if not m:
            check('探针返回结果', False, f'得到 {out[:80]}')
        else:
            d = json.loads(m.group(1))
            check('★无 JS 运行时错误', len(d['errs']) == 0,
                  f'错误: {d["errs"][:2]}')
            check('★关键函数全部挂在 window', len(d['missing']) == 0,
                  f'缺失: {d["missing"]}')
            check('导航渲染完成（6 个标签）', d['nav'] == 6, f'实际 {d["nav"]}')
            check('主体内容已渲染', d['rendered'] is True)

    # ---------- 2. 有数据时能正确加载 ----------
    print('\n【2】数据加载（模拟老用户）')
    from datetime import date, timedelta
    today = date.today()
    iso = lambda n: (today - timedelta(days=n)).isoformat()
    seed = {
        "kids": {"k1": {"id": "k1", "nickname": "冒烟娃", "stage": "high",
                        "createdAt": iso(10)}},
        "cards": {
            "c1": {"id": "c1", "kidId": "k1", "front": "问题一", "back": "答案一",
                   "subject": "数学", "step": 1, "okCount": 1,
                   "due": iso(1), "createdAt": iso(5)},
            "c2": {"id": "c2", "kidId": "k1", "front": "问题二", "back": "答案二",
                   "subject": "语文", "step": 0, "okCount": 0,
                   "due": iso(0), "createdAt": iso(3)},
        },
        "errors": {
            "e1": {"id": "e1", "kidId": "k1", "question": "错题一",
                   "thinking": "当时想错了", "gap": "差在这", "type": "概念不懂",
                   "round": 0, "due": iso(1), "archived": False, "createdAt": iso(2)},
        },
    }
    head = ('<script>localStorage.setItem("learnos.onboarded","1");'
            'localStorage.setItem("learnos.currentKid","k1");'
            'localStorage.setItem("learnos.adapter.local.v1", %s);</script>'
            % json.dumps(json.dumps(seed, ensure_ascii=False), ensure_ascii=False))

    body = '''<script type="module">
setTimeout(() => {
  try {
    document.title = 'DATA|' + JSON.stringify({
      cards: document.getElementById('sCards').textContent,
      due: document.getElementById('sDue').textContent,
      errs: document.getElementById('sErr').textContent,
      listItems: document.querySelectorAll('#dueList .item').length,
    });
  } catch (e) { document.title = 'DATAERR|' + e.message; }
}, 3000);
</script>'''

    fixture = make_fixture('data', extra_head=head, extra_body=body)
    try:
        out = run_probe(f'{BASE}/03-PWA/{os.path.basename(fixture)}', None, profile='smoke-data')
    finally:
        os.remove(fixture)

    m = re.search(r'DATA\|(.*)', out, re.S)
    if not m:
        check('数据探针返回', False, out[:100])
    else:
        d = json.loads(m.group(1))
        check('★知识卡计数正确（2）', d['cards'] == '2', f'实际 {d["cards"]}')
        # c1(due=昨天) 与 c2(due=今天) 都已到期，isDue 用 due<=today
        check('★待复习计数正确（2）', d['due'] == '2',
              f'实际 {d["due"]}（若为 1，多半是时区 bug：today() 用了 UTC）')
        check('待重做错题计数正确（1）', d['errs'] == '1', f'实际 {d["errs"]}')
        check('今日列表渲染了条目', d['listItems'] >= 1, f'实际 {d["listItems"]}')

    # ---------- 3. 核心交互可触发 ----------
    print('\n【3】核心交互（真实点击）')
    body3 = '''<script>
window.__errs = [];
window.addEventListener('error', e => window.__errs.push(e.message), true);
</script>
<script type="module">
setTimeout(async () => {
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const click = t => { const b = [...document.querySelectorAll('button')]
    .find(x => x.textContent.includes(t)); if (b) { b.click(); return true; } return false; };
  const R = {};
  try {
    R.clickedStart = click('开始自测复习');
    await sleep(700);
    R.reviewOpen = !document.getElementById('review').hidden;
    R.answerHidden = document.getElementById('rAnswerBox').hidden;
    R.progress = document.getElementById('rProgress').textContent;
    click('看答案');
    await sleep(400);
    R.revealedOk = !document.getElementById('rAnswerBox').hidden;
    click('想起来了');
    await sleep(800);
    R.advanced = document.getElementById('rProgress').textContent;
    R.reset = document.getElementById('rAnswerBox').hidden;
    R.errs = window.__errs;
    document.title = 'INT|' + JSON.stringify(R);
  } catch (e) { document.title = 'INTERR|' + e.message; }
}, 3000);
</script>'''

    fixture = make_fixture('interact', extra_head=head, extra_body=body3)
    try:
        out = run_probe(f'{BASE}/03-PWA/{os.path.basename(fixture)}', None, profile='smoke-int')
    finally:
        os.remove(fixture)

    m = re.search(r'INT\|(.*)', out, re.S)
    if not m:
        check('交互探针返回', False, out[:100])
    else:
        d = json.loads(m.group(1))
        check('点击「开始自测复习」有响应', d.get('clickedStart') is True)
        check('★复习层打开', d.get('reviewOpen') is True)
        check('★答案初始隐藏（先合书自测）', d.get('answerHidden') is True)
        check('点「看答案」后显示答案', d.get('revealedOk') is True)
        check('评分后进度前进', d.get('advanced', '') not in ('', '1 / 1'),
              d.get('advanced'))
        check('新题重置为隐藏', d.get('reset') is True)
        check('交互过程无 JS 错误', len(d.get('errs', [])) == 0, d.get('errs'))


    # ---------- 4. 静态完整性（无需浏览器） ----------
    print('\n【4】静态完整性（声明与实现是否对得上）')
    src = open(os.path.join(ROOT, '03-PWA', 'index.html'), encoding='utf-8').read()
    parts = src.split('<script type="module">')
    html_part = parts[0]
    mod = parts[1] if len(parts) > 1 else ''

    # 4a. JS 引用但 HTML 里不存在的 id（会返回 null，后续操作报错）
    html_ids = set(re.findall(r'id="([\w-]+)"', html_part))
    js_ids = set(re.findall(r"getElementById\('([\w-]+)'\)", mod))
    js_ids |= set(re.findall(r"\$\('([\w-]+)'\)", mod))
    missing_ids = sorted(js_ids - html_ids)
    check('★JS 引用的 id 都存在', not missing_ids, f'缺失: {missing_ids}')

    # 4b. 死代码：定义了、没导出、HTML 没调用、模块内也没别处调用
    defined = set(re.findall(r'^(?:async\s+)?function\s+([a-zA-Z_$][\w$]*)', mod, re.M))
    mm = re.search(r'Object\.assign\(window,\s*\{([\s\S]*?)\}\)', mod)
    exported = set(re.findall(r'([a-zA-Z_$][\w$]*)', mm.group(1))) if mm else set()
    called_html = set(re.findall(r'on(?:click|change|input)="([a-zA-Z_$][\w$]*)\s*\(', html_part))
    dead = []
    for f in sorted(defined):
        if f in exported or f in called_html:
            continue
        # 统计模块内调用次数（定义行本身算 1 次）
        if len(re.findall(r'(?<![\w.$])' + re.escape(f) + r'\s*\(', mod)) <= 1:
            dead.append(f)
    check('★没有无人调用的死函数', not dead, f'死代码: {dead}')

    # 4c. 每个 on* 处理器引用的函数必须真的定义了
    handlers = set(re.findall(r'on(?:click|change|input)="([a-zA-Z_$][\w$]*)\s*\(', html_part))
    handlers |= set(re.findall(r"onclick=\\?[\"']([a-zA-Z_$][\w$]*)\(", mod))
    undef = sorted(h for h in handlers if h not in defined and h not in exported)
    check('★所有事件处理器都有对应函数', not undef, f'未定义: {undef}')

    print('\n' + '=' * 72)
    if failed:
        print(f'通过 {passed} 项，失败 {failed} 项')
        print('失败项：')
        for p in problems:
            print(f'  · {p}')
    else:
        print(f'全部通过（{passed} 项）—— 应用可正常启动')
    print('=' * 72)
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())

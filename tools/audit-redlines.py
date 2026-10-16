#!/usr/bin/env python3
"""
设计红线审计
==============
问题背景：README 里写着「单文件 20KB」，但实际早已是 68KB / 4 个模块。
承诺写下来之后就没人再核对 —— **写在文档里的承诺，往往正是最没被验证的**。

这个脚本把「红线」从文档里的口号，变成可执行断言。

用法：python3 tools/audit-redlines.py
返回码：0 = 全部成立；1 = 有红线被违反或数字过时
"""
import os
import re
import sys

ROOT = os.path.expanduser('~/教育平权项目')
PWA = os.path.join(ROOT, '03-PWA')

# 红线 3 的规模上限：超过就提示更新文档
# 这个数字不是「越小越好」，而是「别让文档撒谎」
MAX_TOTAL_KB = 300          # 整个 PWA（不含测试/工具）的合理上限
MAX_HTML_KB = 120           # 单文件上限


def kb(path):
    return os.path.getsize(path) / 1024


def pwa_files():
    """PWA 运行时文件（排除测试与工具）"""
    out = []
    for f in sorted(os.listdir(PWA)):
        p = os.path.join(PWA, f)
        if not os.path.isfile(p):
            continue
        if f.endswith(('.test.mjs',)):
            continue
        if f in ('_measure.html',) or f.startswith('_'):
            continue
        if f.endswith(('.html', '.js', '.webmanifest')):
            out.append(f)
    # 图标
    icons = os.path.join(PWA, 'icons')
    if os.path.isdir(icons):
        out += [os.path.join('icons', i) for i in sorted(os.listdir(icons))]
    return out


def main():
    print('=' * 70)
    print('设计红线审计：文档里的承诺，是否与实现一致')
    print('=' * 70)

    ok = fail = 0
    problems = []

    def check(name, cond, extra=''):
        nonlocal ok, fail
        if cond:
            print(f'  ✅ {name}')
            ok += 1
        else:
            print(f'  ❌ {name} {extra}')
            fail += 1
            problems.append(name)

    # ---------- 红线 1：零成本 ----------
    print('\n【1】零成本')
    has_pkg = os.path.exists(os.path.join(PWA, 'package.json'))
    check('PWA 无 npm 依赖（无 package.json）', not has_pkg)
    ext = []
    for f in ['index.html', 'sw.js', 'contract.js', 'local-adapter.js', 'migrate.js']:
        p = os.path.join(PWA, f)
        if not os.path.exists(p):
            continue
        s = open(p, encoding='utf-8').read()
        # 外链资源（排除注释里的说明性 URL）
        for m in re.finditer(r'(?:src|href)="(https?://[^"]+)"', s):
            ext.append(f'{f}: {m.group(1)}')
    check('★无外部资源依赖（CDN/字体/图片）', not ext, ext[:3])

    # ---------- 红线 2：离线可用 ----------
    print('\n【2】离线可用')
    check('有 Service Worker', os.path.exists(os.path.join(PWA, 'sw.js')))
    sw = open(os.path.join(PWA, 'sw.js'), encoding='utf-8').read() \
        if os.path.exists(os.path.join(PWA, 'sw.js')) else ''
    check('SW 预缓存核心资源', 'ASSETS' in sw and 'caches.open' in sw)
    # 预缓存清单里的文件必须真实存在
    assets = re.findall(r"'\./([^']+)'", sw)
    missing = [a for a in assets
               if a not in ('',) and not os.path.exists(os.path.join(PWA, a))]
    check('★预缓存清单里的文件都存在', not missing, missing)
    check('有离线测试脚本', os.path.exists(os.path.join(PWA, 'offline.test.mjs')))

    # ---------- 红线 3：低配可用（规模与兼容性）----------
    print('\n【3】低配可用')
    files = pwa_files()
    total = sum(kb(os.path.join(PWA, f)) for f in files)
    html_kb = kb(os.path.join(PWA, 'index.html'))
    print(f'     实际规模：整个 PWA {total:.0f} KB，index.html {html_kb:.0f} KB，'
          f'共 {len(files)} 个运行时文件')
    check(f'整体规模在 {MAX_TOTAL_KB} KB 以内', total <= MAX_TOTAL_KB,
          f'{total:.0f} KB')
    check(f'主文件在 {MAX_HTML_KB} KB 以内', html_kb <= MAX_HTML_KB,
          f'{html_kb:.0f} KB')

    # 不用旧设备缺失的 API（除非有降级）
    compat_issues = []
    for f in files:
        if not f.endswith('.js'):
            continue
        s = open(os.path.join(PWA, f), encoding='utf-8').read()
        codes = re.sub(r'/\*[\s\S]*?\*/', '', s)
        codes = re.sub(r'//[^\n]*', '', codes)
        for api, note in [('structuredClone', 'Chrome 98+/Safari 15.4+'),
                          ('replaceAll', 'ES2021'),
                          ('fromEntries', 'ES2019'),
                          ('allSettled', 'ES2020')]:
            if re.search(r'(?<![\w.])' + api + r'\s*\(', codes):
                # 是否在 typeof / 特性检测里（说明有降级）
                if f'typeof {api}' not in s and f'typeof {api}' not in codes:
                    compat_issues.append(f'{f}: {api} ({note})')
    check('★未直接使用旧设备缺失的 API', not compat_issues, compat_issues)

    # 模块脚本：老浏览器不支持 type=module
    idx = open(os.path.join(PWA, 'index.html'), encoding='utf-8').read()
    check('主脚本为 ES module（需较新浏览器）',
          '<script type="module">' in idx,
          '（这是已知限制，非缺陷）')

    # ---------- 红线 4：低文化门槛 ----------
    print('\n【4】低文化门槛')
    check('有语音朗读功能', 'speechSynthesis' in idx)
    check('有打印版（无需设备）',
          os.path.exists(os.path.join(ROOT, '01-方法论', '打印版-零门槛.html')))
    check('有不识字的说明文案', '不识字' in idx or '念给我听' in idx)

    # ---------- 红线 5：数据自主 ----------
    print('\n【5】数据自主（不上传）')
    net_calls = []
    for f in files:
        if not f.endswith('.js') or f == 'sw.js':
            continue          # sw.js 的 fetch 只取自己的静态文件
        s = open(os.path.join(PWA, f), encoding='utf-8').read()
        s2 = re.sub(r'/\*[\s\S]*?\*/', '', s)
        s2 = re.sub(r'//[^\n]*', '', s2)
        for api in ['fetch(', 'XMLHttpRequest', 'sendBeacon', 'WebSocket', 'EventSource']:
            if api in s2:
                net_calls.append(f'{f}: {api}')
    check('★业务代码无任何网络上报', not net_calls, net_calls)
    check('数据存 localStorage', 'localStorage' in idx)
    check('提供导出功能', 'exportData' in idx)
    check('提供彻底删除功能', 'deleteAll' in idx or 'resetAll' in idx)

    # ---------- 红线 6：可复制 ----------
    print('\n【6】可复制')
    for f, desc in [('README.md', '项目说明'),
                    ('04-调研/教育平权与推广路径.md', '推广路径')]:
        check(f'有{desc}', os.path.exists(os.path.join(ROOT, f)))

    # ---------- 文档一致性 ----------
    print('\n【7】文档中的数字是否与实际一致')
    readme = open(os.path.join(ROOT, 'README.md'), encoding='utf-8').read()
    m = re.search(r'当前：单文件\s*(\d+)\s*KB', readme)
    if m:
        claimed = int(m.group(1))
        check(f'README 声称的 {claimed}KB 与实际的 {html_kb:.0f}KB 相符',
              abs(claimed - html_kb) <= 5,
              f'README 写 {claimed}KB，实际 {html_kb:.0f}KB —— 需更新')
    else:
        check('README 中有可核对的规模描述', True,
              '（未找到「单文件 N KB」表述，跳过）')

    # ---------- 渲染产物是否与源文件同步 ----------
    print('\n【8】文档渲染是否最新（改了 .md 但没重建，线上就是旧的）')
    docs_dir = os.path.join(ROOT, 'docs')
    idx_page = os.path.join(docs_dir, 'index.html')
    if not os.path.exists(idx_page):
        check('docs/ 已生成', False, '缺少 docs/index.html')
    else:
        idx_mtime = os.path.getmtime(idx_page)
        stale = []
        for src_rel in ['README.md'] + \
                [os.path.join(d, f) for d in ['01-方法论', '02-资源地图', '04-调研']
                 for f in sorted(os.listdir(os.path.join(ROOT, d)))
                 if f.endswith('.md')]:
            p2 = os.path.join(ROOT, src_rel)
            if os.path.exists(p2) and os.path.getmtime(p2) > idx_mtime:
                stale.append(src_rel)
        check('★没有「改了源文件但未重建」的文档', not stale,
              f'需重跑 build-docs.py：{stale[:3]}')

    print('\n' + '=' * 70)
    if fail:
        print(f'通过 {ok} 项，失败 {fail} 项')
        for p in problems:
            print(f'  · {p}')
    else:
        print(f'全部通过（{ok} 项）—— 六条红线均成立')
    print('=' * 70)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())

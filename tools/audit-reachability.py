#!/usr/bin/env python3
"""
可达性审计（Reachability Audit）
==================================
问题背景：这个项目反复出现同一类失误——「东西做了，但用户走不到」。

历史案例：
- .md 渲染成 HTML 了，但首页仍链到 .md（手机上是纯文本）
- 新增了汉字综述，但没加进 build-docs.py 的渲染清单
- 文档都齐了，但 PWA 里没有任何入口指向它们

这类问题功能测试查不出来（页面 200、代码无 bug），
只有站在「用户能不能真的用到」的角度审计才能发现。

本脚本做法：
1. 从入口（index.html、03-PWA/index.html）出发，抓取所有站内链接
2. 做广度优先遍历，得到「可达集合」
3. 与「应该可达的资产清单」对比，报告孤儿

用法：python3 tools/audit-reachability.py
返回码：0 = 全部可达；1 = 存在孤儿
"""
import os
import re
import sys

ROOT = os.path.expanduser('~/教育平权项目')

# 入口页面（用户可能从这里开始）
ENTRIES = ['index.html', '03-PWA/index.html']

# 纯内部工具，不需要被用户走到
INTERNAL = {
    'tools/README.md', 'tools/build-docs.py', 'tools/audit-mobile.py',
    'tools/audit-claims.py', 'tools/audit-reachability.py',
    '05-后端原型/README.md', '05-后端原型/index.html',
    '05-后端原型/contract.js', '05-后端原型/A-仅本地/local-adapter.js',
    '05-后端原型/B-云端D1/http-adapter.js', '05-后端原型/B-云端D1/worker.js',
    '05-后端原型/B-云端D1/schema.sql', '05-后端原型/B-云端D1/wrangler.toml',
    '05-后端原型/B-云端D1/worker.test.cjs',
    '_measure.html',
}

# 源文件（.md 是内容源，用户读的是渲染后的 HTML；不算孤儿，
# 但若一个 .md 既没渲染、也没被任何页面链接，才是问题）
SOURCE_MD_OK = True


def all_files():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in ('.git', 'node_modules')]
        for f in filenames:
            if f.startswith('_'):
                continue
            rel = os.path.relpath(os.path.join(dirpath, f), ROOT)
            out.append(rel.replace(os.sep, '/'))
    return sorted(out)


def extract_links(rel):
    """从 HTML/MD 中抓取站内相对链接"""
    p = os.path.join(ROOT, rel)
    try:
        text = open(p, encoding='utf-8', errors='ignore').read()
    except Exception:
        return set()

    links = set()
    # HTML href / src
    for m in re.finditer(r'(?:href|src)="([^"]+)"', text):
        links.add(m.group(1))
    # Markdown 链接
    for m in re.finditer(r'\]\(([^)\s]+)\)', text):
        links.add(m.group(1))
    return links


def normalize(link, from_rel):
    """把链接解析成相对 ROOT 的路径；站外/锚点返回 None"""
    if not link or link.startswith(('http://', 'https://', 'mailto:', '#', 'data:', 'javascript:')):
        return None
    link = link.split('#')[0].split('?')[0]
    if not link:
        return None
    base = os.path.dirname(from_rel)
    resolved = os.path.normpath(os.path.join(base, link))
    if resolved.startswith('..'):
        return None
    return resolved.replace(os.sep, '/')


def main():
    print('=' * 72)
    print('可达性审计：从入口出发，能否走到每个产出？')
    print('=' * 72)

    # BFS
    seen = set()
    queue = [e for e in ENTRIES if os.path.exists(os.path.join(ROOT, e))]
    missing_entry = [e for e in ENTRIES if not os.path.exists(os.path.join(ROOT, e))]
    for e in missing_entry:
        print(f'⚠️  入口不存在：{e}')

    while queue:
        cur = queue.pop(0)
        if cur in seen:
            continue
        seen.add(cur)
        for link in extract_links(cur):
            nxt = normalize(link, cur)
            if nxt and nxt not in seen:
                queue.append(nxt)

    print(f'\n入口：{", ".join(ENTRIES)}')
    print(f'可达文件：{len(seen)} 个\n')

    # 应该可达的：所有 HTML + 所有 docs/*.html
    files = all_files()
    should_reach = [
        f for f in files
        if (f.endswith('.html') and f not in INTERNAL)
        or f.startswith('docs/')
    ]

    orphans = [f for f in should_reach if f not in seen]

    print('--- 可达的页面 ---')
    for f in sorted(seen):
        if f.endswith('.html'):
            print(f'  ✅ {f}')

    print('\n--- 孤儿（存在但走不到）---')
    if not orphans:
        print('  （无）')
    else:
        for f in orphans:
            print(f'  ❌ {f}')

    # 额外检查：.md 是否被误当作面向用户的链接（手机上会变纯文本）
    print('\n--- 检查：是否有页面直接链到 .md（手机上会是纯文本）---')
    md_links = []
    for f in sorted(seen):
        if not f.endswith('.html'):
            continue
        for link in extract_links(f):
            nxt = normalize(link, f)
            if nxt and nxt.endswith('.md'):
                md_links.append((f, nxt))
    if md_links:
        for src, dst in md_links:
            print(f'  ⚠️  {src} → {dst}')
    else:
        print('  ✅ 没有面向用户的 .md 链接')

    bad = len(orphans) + len(md_links) + len(missing_entry)

    print('\n' + '=' * 72)
    if bad:
        print(f'发现 {len(orphans)} 个孤儿、{len(md_links)} 处 .md 直链')
    else:
        print('全部可达，且没有 .md 直链')
    print('=' * 72)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

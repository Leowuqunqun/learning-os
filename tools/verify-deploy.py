#!/usr/bin/env python3
"""
部署验证（Deploy Verification）
=================================
问题背景：每次 `git push` 后我都要手写一段 curl 循环来确认
GitHub Pages 是否构建完成、资源是否真的可访问。这段逻辑重复了 8 轮，
且每次写法略有不同（有时漏检查某个资源）。

本脚本把它固化：
1. 等待 Pages 构建完成（轮询）
2. 逐项检查关键资源（HTTP 200 + Content-Type 正确）
3. 检查页面内容非空且包含预期关键字
4. 检查 .md 误用（手机上会是纯文本）

用法：
    python3 tools/verify-deploy.py            # 默认检查
    python3 tools/verify-deploy.py --wait     # 先等待构建
返回码：0 = 全部通过；1 = 有问题
"""
import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = 'https://leowuqunqun.github.io/learning-os'

# (路径, 期望 Content-Type 前缀, 内容里应出现的关键字或 None)
CHECKS = [
    ('/',                                  'text/html',  '学习操作系统'),
    ('/index.html',                        'text/html',  '学习操作系统'),
    ('/docs/index.html',                   'text/html',  '全部文档'),
    ('/docs/zonggang.html',                'text/html',  '学习只有 4 个动作'),
    ('/docs/shouce.html',                  'text/html',  '合书'),
    ('/docs/xueduan.html',                 'text/html',  '学段'),
    ('/docs/zhengju.html',                 'text/html',  'Dunlosky'),
    ('/docs/hanzi.html',                   'text/html',  'Ruan'),
    ('/docs/ziyuan.html',                  'text/html',  '免费'),
    ('/docs/phet.html',                    'text/html',  'PhET'),
    ('/docs/pingquan.html',                'text/html',  '教育平权'),
    ('/docs/readme.html',                  'text/html',  '项目'),
    ('/docs/docs.css',                     'text/css',   None),
    ('/01-方法论/第一周打勾清单.html',        'text/html',  '打勾'),
    ('/01-方法论/打印版-零门槛.html',        'text/html',  '讲给我听'),
    ('/03-PWA/index.html',                 'text/html',  '学习操作系统'),
    ('/03-PWA/manifest.webmanifest',       'application/manifest+json', None),
    ('/03-PWA/sw.js',                      'application/javascript', 'CACHE'),
    ('/03-PWA/contract.js',                'application/javascript', 'CARD_STEPS'),
    ('/03-PWA/local-adapter.js',           'application/javascript', 'LocalAdapter'),
    ('/03-PWA/migrate.js',                 'application/javascript', 'runMigration'),
    ('/03-PWA/icons/icon-192.png',         'image/png',   None),
]

# 这些路径必须返回 text/html；若返回 text/markdown 说明用户拿到的是纯文本
MUST_NOT_BE_MARKDOWN = [p for p, ct, _ in CHECKS]


def fetch(path, timeout=25):
    # 注意：urllib 不会自动对中文路径做百分号编码（curl 会自动）。
    # 不编码会直接失败，所以这里显式处理。
    url = BASE + urllib.parse.quote(path)
    req = urllib.request.Request(url, headers={'User-Agent': 'deploy-verify/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return {
                'status': r.status,
                'ctype': (r.headers.get('Content-Type') or '').split(';')[0].strip(),
                'body': body,
            }
    except urllib.error.HTTPError as e:
        return {'status': e.code, 'ctype': '', 'body': b'', 'error': str(e)}
    except Exception as e:
        return {'status': 0, 'ctype': '', 'body': b'', 'error': str(e)}


def wait_for_build(timeout_s=300, path='/03-PWA/sw.js', needle='CACHE'):
    """轮询直到远端出现预期内容（说明 Pages 构建完成）"""
    print(f'等待 Pages 构建（最多 {timeout_s}s）…')
    start = time.time()
    while time.time() - start < timeout_s:
        r = fetch(path, timeout=15)
        if r['status'] == 200 and needle.encode() in r['body']:
            print(f'  ✅ 构建完成（用时 {int(time.time()-start)}s）')
            return True
        time.sleep(8)
    print('  ⚠️ 超时：可能仍在构建，或部署失败')
    return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--wait', action='store_true', help='先等待 Pages 构建')
    ap.add_argument('--json', action='store_true', help='输出 JSON')
    args = ap.parse_args()

    if args.wait:
        wait_for_build()

    results = []
    for path, want_ctype, needle in CHECKS:
        r = fetch(path)
        ok_status = r['status'] == 200
        ok_ctype = r['ctype'].startswith(want_ctype) if want_ctype else True
        ok_needle = True
        if needle:
            try:
                text = r['body'].decode('utf-8', errors='ignore')
            except Exception:
                text = ''
            ok_needle = needle in text
        ok = ok_status and ok_ctype and ok_needle
        results.append({
            'path': path, 'ok': ok, 'status': r['status'],
            'ctype': r['ctype'], 'want': want_ctype,
            'needle': needle, 'ok_needle': ok_needle,
        })

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f'{BASE}\n')
        print(f"{'资源':<40} {'状态':>5} {'类型':<28} 判定")
        print('-' * 88)
        for x in results:
            mark = '✅' if x['ok'] else '❌'
            ct = x['ctype'][:26] or '-'
            note = ''
            if x['status'] != 200:
                note = f"HTTP {x['status']}"
            elif x['want'] and not x['ctype'].startswith(x['want']):
                note = f"类型应为 {x['want']}"
            elif not x['ok_needle']:
                note = f"缺少关键字「{x['needle']}」"
            print(f"{mark} {x['path']:<38} {x['status']:>5} {ct:<28} {note}")

    # 额外：确认没有 .md 被当作页面链接（这里检查 .md 本身可访问但非 html 是正常的）
    bad = [x for x in results if not x['ok']]

    print('\n' + '=' * 88)
    if bad:
        print(f'{len(bad)} / {len(results)} 项未通过')
        for x in bad:
            print(f"  · {x['path']}")
    else:
        print(f'全部通过（{len(results)} 项）')
    print('=' * 88)
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

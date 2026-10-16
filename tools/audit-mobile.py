#!/usr/bin/env python3
"""
全站手机适配审计（可信版）
================================
教训：用 CSS 强制 width:360px **不能**模拟手机视口——
它会改变盒模型（加 margin、改变百分比基准），产生假阳性。
正确做法：把页面放进真实 360px 的 iframe 里测量。

用法：python3 tools/audit-mobile.py
"""
import os
import re
import subprocess
import sys
import glob

ROOT = os.path.expanduser('~/教育平权项目')
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
PORT = int(os.environ.get('AUDIT_PORT', '8150'))

PAGES = [
    'index.html',
    '01-方法论/打印版-零门槛.html',
    '01-方法论/第一周打勾清单.html',
    '03-PWA/index.html',
] + ['docs/' + os.path.basename(p) for p in sorted(glob.glob(os.path.join(ROOT, 'docs', '*.html')))]


def measure(rel):
    """在 360px iframe 中加载并测量"""
    url = f'http://127.0.0.1:{PORT}/_measure.html?p=./{rel}'
    prof = f'/tmp/audit-{abs(hash(rel)) % 99999}'
    try:
        r = subprocess.run(
            [CHROME, '--headless=new', '--disable-gpu', '--no-sandbox',
             f'--user-data-dir={prof}', '--window-size=900,820',
             '--virtual-time-budget=12000', '--dump-dom', url],
            capture_output=True, text=True, timeout=70)
        m = re.search(r'<title>REAL\|vw=(\d+)\|scrollW=(\d+)\|溢出=(\d+)\|([^<]*)</title>', r.stdout)
        if m:
            return {'vw': int(m.group(1)), 'scrollW': int(m.group(2)),
                    'over': int(m.group(3)), 'detail': m.group(4)}
        m2 = re.search(r'<title>(ERR[^<]*)</title>', r.stdout)
        return {'error': m2.group(1) if m2 else '未取到探针结果'}
    except subprocess.TimeoutExpired:
        return {'error': '超时'}
    finally:
        subprocess.run(['rm', '-rf', prof], capture_output=True)


def main():
    if not os.path.exists(os.path.join(ROOT, '_measure.html')):
        print('❌ 缺少 _measure.html（测量夹具）'); sys.exit(1)

    print(f"{'页面':<40} {'视口':>6} {'scrollW':>8} {'溢出':>6}  判定")
    print('-' * 72)
    bad = []
    for rel in PAGES:
        if not os.path.exists(os.path.join(ROOT, rel)):
            print(f"{rel:<40} {'—':>6} {'—':>8} {'—':>6}  ⚠️ 文件不存在")
            continue
        res = measure(rel)
        if 'error' in res:
            print(f"{rel:<40} {'—':>6} {'—':>8} {'—':>6}  ⚠️ {res['error']}")
            bad.append(rel)
            continue
        ok = res['over'] == 0 and res['scrollW'] <= res['vw'] + 2
        mark = '✅' if ok else '❌'
        if not ok:
            bad.append(rel)
        print(f"{mark} {rel:<38} {res['vw']:>6} {res['scrollW']:>8} {res['over']:>6}  "
              f"{res['detail'][:40] if not ok else ''}")
    print('-' * 72)
    print(f"共 {len(PAGES)} 页，{len(bad)} 页有问题")
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

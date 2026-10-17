#!/usr/bin/env python3
"""
资源链接健康检查
==================
为什么需要：资源地图承诺「逐条实测的免费优质资源」，
但**网页会失效**。上次全量验证在 25 轮之前，此后没有复查过。

失效的链接对家长是实际损失：点进去打不开，会怀疑整份清单的可信度。

本脚本：
  ① 从资源地图抽取所有 URL
  ② 并发探测（默认 8 并发，66 个 URL 约 30 秒）
  ③ 区分「真失效」与「反爬拦截」（403/CF 拦截不算失效）
  ④ 带重试，避免网络抖动误报
  ⑤ 输出可直接粘贴进文档的复查日期

用法：
    python3 tools/check-links.py             # 全量检查
    python3 tools/check-links.py --update    # 检查并更新文档里的复查日期
返回码：0 = 全部可达（或仅有反爬）；1 = 存在真失效
"""
import argparse
import concurrent.futures
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.expanduser('~/教育平权项目')
DOC = os.path.join(ROOT, '02-资源地图', 'K12免费教育资源地图.md')
UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
      '(KHTML, like Gecko) Chrome/120.0 Safari/537.36')

# 这些状态码说明「站点存在，只是拒绝机器人」——不是失效
ANTI_BOT = {401, 403, 405, 429, 503}


def extract_urls(path):
    """返回 (url, 是否为「已知反例」)。

    文档里有些 URL 是**故意写的反面教材**（如汉典「用 Unicode 编码会 404」），
    它们本来就该失败，不该被报成链接失效。
    识别方法：该 URL 所在行含 ❌ 或 404 字样。
    """
    text = open(path, encoding='utf-8').read()
    out = {}
    for line in text.split('\n'):
        is_negative = ('❌' in line) or ('404' in line and '→' in line)
        for m in re.finditer(r'https?://[^\s)>"\']+', line):
            u = m.group(0).rstrip('.,;:)）】、`\'"')
            if 'example.com' in u or '<' in u or '>' in u:
                continue
            # 同一 URL 若有一处是正面示例，就不算反例
            out[u] = out.get(u, True) and is_negative
    return sorted(out.items())


def fetch(url, timeout=15, retries=2):
    """返回 (状态码, 说明)。状态码 0 表示连接失败。"""
    last_err = ''
    for attempt in range(retries + 1):
        try:
            # 中文路径（如 zdic.net/hans/笔）必须做百分号编码，
            # 否则 urllib 抛 UnicodeEncodeError
            safe = urllib.parse.quote(url, safe=':/?&=#%[]@!$+,;~*\'()')
            req = urllib.request.Request(safe, headers={'User-Agent': UA})
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                return r.status, ''
        except urllib.error.HTTPError as e:
            return e.code, f'HTTP {e.code}'
        except urllib.error.URLError as e:
            last_err = str(e.reason)[:60]
        except Exception as e:
            last_err = type(e).__name__ + ': ' + str(e)[:50]
        if attempt < retries:
            time.sleep(1.5)
    return 0, last_err


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--update', action='store_true', help='更新文档里的复查日期')
    ap.add_argument('--workers', type=int, default=8)
    args = ap.parse_args()

    if not os.path.exists(DOC):
        print(f'❌ 找不到资源地图：{DOC}')
        return 1

    url_pairs = extract_urls(DOC)
    urls = [u for u, _ in url_pairs]
    known_neg = {u for u, neg in url_pairs if neg}
    print('=' * 74)
    print(f'资源链接健康检查：共 {len(urls)} 个 URL')
    print('=' * 74)

    results = []
    t0 = time.time()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(fetch, u): u for u in urls}
        for fut in concurrent.futures.as_completed(futs):
            u = futs[fut]
            try:
                code, note = fut.result()
            except Exception as e:
                code, note = 0, str(e)[:60]
            results.append((u, code, note))

    elapsed = time.time() - t0
    ok = [r for r in results if r[1] == 200]
    antispider = [r for r in results if r[1] in ANTI_BOT]
    bad_all = [r for r in results if r[1] not in ANTI_BOT and r[1] != 200]
    # 文档里故意写的反例不计为失效
    bad = [r for r in bad_all if r[0] not in known_neg]
    expected_fail = [r for r in bad_all if r[0] in known_neg]

    print(f'\n完成，用时 {elapsed:.0f} 秒\n')
    print(f'  ✅ 正常可达      {len(ok):3d} 个')
    print(f'  🔒 反爬拦截    {len(antispider):3d} 个（站点存在，非失效）')
    print(f'  ❌ 疑似失效    {len(bad):3d} 个')
    if expected_fail:
        print(f'  📌 预期失效    {len(expected_fail):3d} 个（文档中故意写的反例）')

    if antispider:
        print('\n--- 反爬拦截（人工访问通常正常，不计为失效）---')
        for u, c, n in sorted(antispider):
            print(f'  {c}  {u}')

    if bad:
        print('\n--- 疑似失效（需人工确认或替换）---')
        for u, c, n in sorted(bad):
            print(f'  {c:>3}  {u}')
            if n:
                print(f'        ↳ {n}')

    print('\n' + '=' * 74)
    if bad:
        print(f'{len(bad)} 个链接疑似失效，建议人工确认')
    else:
        print(f'全部通过：{len(ok)} 个可达，{len(antispider)} 个反爬（均属正常）')
    print('=' * 74)

    if args.update:
        today = time.strftime('%Y-%m-%d')
        text = open(DOC, encoding='utf-8').read()
        new = re.sub(
            r'(\*\*核查日期\*\*：)[^\n]*',
            rf'\g<1>{today}（`tools/check-links.py` 自动复查）',
            text)
        if new == text:
            # 没有现成的核查日期字段，就补在编制日期后面
            new = re.sub(
                r'(> \*\*编制日期\*\*：[^\n]*)',
                rf'\g<1>\n> **最近链接复查**：{today}（`tools/check-links.py`，'
                rf'{len(ok)} 可达 / {len(antispider)} 反爬 / {len(bad)} 失效）',
                text, count=1)
        if new != text:
            open(DOC, 'w', encoding='utf-8').write(new)
            print(f'✅ 已更新文档中的复查日期为 {today}')

    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())

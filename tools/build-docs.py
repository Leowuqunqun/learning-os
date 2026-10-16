#!/usr/bin/env python3
"""
把项目里的 Markdown 渲染成手机友好的静态 HTML。
零依赖：自己实现所需的 Markdown 子集，不需要 pandoc / markdown-it。

用法：python3 build-docs.py
输出：docs/<name>.html，以及一份 docs/index.html 索引
"""
import html
import os
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'docs'

# 要渲染的文档：(源文件, 输出名, 标题, 一句话说明, 分类)
DOCS = [
    ('01-方法论/学习操作系统-总纲.md', 'zonggang.html',
     '学习操作系统 · 总纲', '核心框架：学习只有 4 个动作', '方法论'),
    ('01-方法论/四动作执行手册.md', 'shouce.html',
     '四动作执行手册', '今天回家怎么做（最实用）', '方法论'),
    ('01-方法论/学段适配指南.md', 'xueduan.html',
     '学段适配指南', '按年级：同一方法怎么改', '方法论'),
    ('01-方法论/学习科学证据简报.md', 'zhengju.html',
     '学习科学证据简报', '40 篇文献 + 证据分级 + 红线', '方法论'),
    ('02-资源地图/K12免费教育资源地图.md', 'ziyuan.html',
     'K12 免费教育资源地图', '逐条实测的免费优质资源', '资源'),
    ('02-资源地图/PhET中文模拟清单.md', 'phet.html',
     'PhET 中文模拟清单', '189 个可离线中文科学模拟', '资源'),
    ('04-调研/教育平权与推广路径.md', 'pingquan.html',
     '教育平权与推广路径', '怎么从"我家"复制到"很多家庭"', '其他'),
    ('04-调研/汉字习得证据综述.md', 'hanzi.html',
     '汉字习得证据综述', '5 项元分析核查：推翻"无证据"的结论', '调研'),
    ('README.md', 'readme.html', '项目说明', '目录、设计红线、当前状态', '其他'),
]


# ---------------- Markdown → HTML（够用即可） ----------------

def slugify(text):
    """给标题生成锚点 id"""
    s = re.sub(r'[^\w\u4e00-\u9fff]+', '-', text).strip('-').lower()
    return s or 'sec'


def inline(text):
    """处理行内标记：代码、粗体、链接、删除线"""
    # 先保护行内代码，避免其中内容被后续规则改写
    codes = []

    def stash(m):
        codes.append(m.group(1))
        return f'\x00CODE{len(codes)-1}\x00'

    text = re.sub(r'`([^`]+)`', stash, text)
    text = html.escape(text, quote=False)
    # 链接 [文字](url)
    text = re.sub(r'\[([^\]]+)\]\(([^)\s]+)\)',
                  lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', text)
    # 粗体：用非贪婪 .+? 而非 [^*]+，否则 **文本含 *斜体* 时匹配失败
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text, flags=re.S)
    # 斜体：避免误伤已转换的标签属性
    text = re.sub(r'(?<![\*\w])\*([^*\n]+)\*(?!\*)', r'<em>\1</em>', text)
    # 还原行内代码
    for i, c in enumerate(codes):
        text = text.replace(f'\x00CODE{i}\x00',
                            f'<code>{html.escape(c, quote=False)}</code>')
    return text


def render_table(lines):
    """渲染表格。首行表头 + 分隔行 + 数据行"""
    rows = []
    for ln in lines:
        cells = [c.strip() for c in ln.strip().strip('|').split('|')]
        rows.append(cells)
    if len(rows) < 2:
        return ''
    head = rows[0]
    body = rows[2:]  # 跳过 |---| 分隔行
    out = ['<div class="tw"><table>', '<thead><tr>']
    out += [f'<th>{inline(c)}</th>' for c in head]
    out += ['</tr></thead><tbody>']
    for r in body:
        out.append('<tr>' + ''.join(f'<td>{inline(c)}</td>' for c in r) + '</tr>')
    out += ['</tbody></table></div>']
    return '\n'.join(out)


def convert(md):
    """把 Markdown 正文转成 HTML 主体"""
    lines = md.replace('\r\n', '\n').split('\n')
    out, i = [], 0
    toc = []

    while i < len(lines):
        ln = lines[i]

        # 代码块
        if ln.strip().startswith('```'):
            lang = ln.strip()[3:].strip()
            buf, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith('```'):
                buf.append(lines[i]); i += 1
            i += 1
            out.append('<pre><code>' +
                       html.escape('\n'.join(buf), quote=False) + '</code></pre>')
            continue

        # 表格
        if ln.strip().startswith('|') and i + 1 < len(lines) and \
           re.match(r'^\s*\|[\s:|-]+\|\s*$', lines[i + 1]):
            buf = []
            while i < len(lines) and lines[i].strip().startswith('|'):
                buf.append(lines[i]); i += 1
            out.append(render_table(buf))
            continue

        # 标题
        m = re.match(r'^(#{1,6})\s+(.*)$', ln)
        if m:
            lvl = len(m.group(1))
            txt = m.group(2).strip()
            sid = slugify(txt)
            if lvl <= 3:
                toc.append((lvl, txt, sid))
            out.append(f'<h{lvl} id="{sid}">{inline(txt)}</h{lvl}>')
            i += 1
            continue

        # 分隔线
        if re.match(r'^\s*---+\s*$', ln):
            out.append('<hr>'); i += 1
            continue

        # 引用块
        if ln.strip().startswith('>'):
            buf = []
            while i < len(lines) and lines[i].strip().startswith('>'):
                buf.append(re.sub(r'^\s*>\s?', '', lines[i])); i += 1
            inner, _ = convert('\n'.join(buf))
            out.append('<blockquote>' + inner + '</blockquote>')
            continue

        # 列表
        if re.match(r'^\s*([-*+]|\d+\.)\s+', ln):
            ordered = bool(re.match(r'^\s*\d+\.\s+', ln))
            tag = 'ol' if ordered else 'ul'
            buf = []
            while i < len(lines) and re.match(r'^\s*([-*+]|\d+\.)\s+', lines[i]):
                item = re.sub(r'^\s*([-*+]|\d+\.)\s+', '', lines[i])
                # 续行（缩进且非列表项）
                i += 1
                while i < len(lines) and lines[i].strip() and \
                        not re.match(r'^\s*([-*+]|\d+\.)\s+', lines[i]) and \
                        lines[i].startswith(('  ', '\t')):
                    item += ' ' + lines[i].strip(); i += 1
                buf.append(f'<li>{inline(item)}</li>')
            out.append(f'<{tag}>' + ''.join(buf) + f'</{tag}>')
            continue

        # 空行
        if not ln.strip():
            i += 1
            continue

        # 普通段落
        buf = []
        while i < len(lines) and lines[i].strip() and \
                not re.match(r'^(#{1,6}\s|\s*[-*+]\s|\s*\d+\.\s|>|\s*```|\s*\|)', lines[i]) and \
                not re.match(r'^\s*---+\s*$', lines[i]):
            buf.append(lines[i].strip()); i += 1
        if buf:
            out.append(f'<p>{inline(" ".join(buf))}</p>')

    return '\n'.join(out), toc


# ---------------- 页面模板 ----------------

PAGE = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title} · 学习操作系统</title>
<meta name="description" content="{desc}">
<meta name="theme-color" content="#2563eb">
<link rel="stylesheet" href="./docs.css">
</head>
<body>
<header>
  <a class="back" href="./index.html">← 全部文档</a>
  <h1>{title}</h1>
  <p class="desc">{desc}</p>
</header>
<main>
{toc}
{body}
</main>
<footer>
  <p>学习操作系统 · 教育平权项目</p>
  <p>免费复制 · 欢迎转发给任何家庭</p>
</footer>
<script>
// 表格横向滚动提示 + 回到顶部
(function(){{
  document.querySelectorAll('.tw').forEach(function(w){{
    if(w.scrollWidth > w.clientWidth + 4) w.classList.add('scrollable');
  }});
}})();
</script>
</body>
</html>
'''

TOC = '''<nav class="toc">
<strong>本页目录</strong>
<ol>{items}</ol>
</nav>'''

CSS = '''/* 学习操作系统 · 文档样式（手机优先） */
:root{--bg:#f8fafc;--fg:#0f172a;--muted:#64748b;--card:#fff;--line:#e2e8f0;
 --brand:#2563eb;--soft:#eff6ff;--code:#f1f5f9}
@media(prefers-color-scheme:dark){:root{--bg:#0b1220;--fg:#e2e8f0;--muted:#94a3b8;
 --card:#131c2e;--line:#1e293b;--brand:#60a5fa;--soft:#1e293b;--code:#1e293b}}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--fg);
 font:16px/1.75 -apple-system,BlinkMacSystemFont,"PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif;
 overflow-x:hidden}
header{background:var(--card);border-bottom:1px solid var(--line);
 padding:calc(14px + env(safe-area-inset-top)) 18px 16px}
.back{display:inline-block;color:var(--brand);text-decoration:none;font-size:14px;
 font-weight:600;margin-bottom:10px}
header h1{margin:0;font-size:21px;line-height:1.35;letter-spacing:.01em}
header .desc{margin:6px 0 0;color:var(--muted);font-size:13.5px}
main{max-width:760px;margin:0 auto;padding:18px 18px 40px;overflow-x:hidden;width:100%}
/* 防止任何子元素把页面撑宽（手机上是致命的） */
main > *{max-width:100%}
footer{max-width:760px;margin:0 auto;padding:22px 18px 50px;
 border-top:1px solid var(--line);color:var(--muted);font-size:12.5px;text-align:center}
footer p{margin:4px 0}

/* 正文排版 */
main h2{font-size:19px;margin:30px 0 12px;padding-bottom:7px;
 border-bottom:2px solid var(--line);line-height:1.4}
main h3{font-size:16.5px;margin:22px 0 8px;line-height:1.45}
main h4{font-size:15px;margin:18px 0 6px;color:var(--muted)}
main p{margin:10px 0}
main strong{font-weight:680}
main a{color:var(--brand);text-decoration:none;border-bottom:1px solid transparent;
 word-break:break-word}
main a:active{border-bottom-color:var(--brand)}
main ul,main ol{padding-left:22px;margin:10px 0}
main li{margin:6px 0}
main hr{border:0;border-top:1px solid var(--line);margin:26px 0}

/* 代码：手机上可横向滚动，不撑破页面
   坑：pre 里的 code 若用 width:max-content，会把祖先的 scrollWidth 一起撑大，
   表现为 body.scrollWidth > 视口宽（页面能左右晃）。
   解法：pre 本身限宽 + overflow 滚动，code 用 width:max-content 但被 pre 裁住。 */
pre{background:var(--code);border:1px solid var(--line);border-radius:10px;
 padding:12px;overflow-x:auto;-webkit-overflow-scrolling:touch;margin:12px 0;
 max-width:100%;width:100%}
pre code{background:none;padding:0;font-size:13px;line-height:1.65;
 font-family:ui-monospace,Menlo,Consolas,monospace;white-space:pre;
 display:block;width:max-content;min-width:0;max-width:none}
code{background:var(--code);padding:1.5px 5px;border-radius:5px;
 font-size:.9em;font-family:ui-monospace,Menlo,Consolas,monospace;
 word-break:break-word;overflow-wrap:anywhere}

/* 引用块 */
blockquote{margin:14px 0;padding:12px 14px;background:var(--soft);
 border-left:3px solid var(--brand);border-radius:0 9px 9px 0;
 max-width:100%;overflow-x:auto;overflow-wrap:anywhere}
blockquote p{margin:6px 0;overflow-wrap:anywhere}
blockquote pre{margin:10px 0}
blockquote p:first-child{margin-top:0}
blockquote p:last-child{margin-bottom:0}

/* 表格：关键——手机上横向滚动而不是压缩变形
   坑1：.tw 必须 max-width:100%，否则被内部 max-content 表格撑开
   坑2：表格用 min-width:max-content，但不设 width:100%（否则窄表被拉宽、
        宽表又溢出）；改为 width:auto + 由内容决定 */
.tw{overflow-x:auto;-webkit-overflow-scrolling:touch;margin:14px 0;
 border:1px solid var(--line);border-radius:10px;position:relative;
 max-width:100%;width:100%}
.tw.scrollable::after{content:"→ 可左右滑动";position:absolute;top:6px;right:8px;
 font-size:10.5px;color:var(--muted);background:var(--card);padding:1px 6px;
 border-radius:99px;pointer-events:none}
table{border-collapse:collapse;font-size:13.5px;
 min-width:max-content;width:auto;max-width:none}
th,td{border-bottom:1px solid var(--line);padding:9px 11px;text-align:left;
 vertical-align:top;white-space:normal;min-width:74px}
th{background:var(--soft);font-weight:680;white-space:nowrap}
tr:last-child td{border-bottom:0}

/* 目录 */
.toc{background:var(--card);border:1px solid var(--line);border-radius:12px;
 padding:14px 16px;margin:0 0 22px}
.toc strong{font-size:13px;color:var(--muted);letter-spacing:.04em}
.toc ol{margin:8px 0 0;padding-left:20px}
.toc li{margin:5px 0;font-size:14px}
.toc a{color:var(--fg);text-decoration:none}
.toc a:active{color:var(--brand)}
.toc .l3{font-size:13px;color:var(--muted);margin-left:2px}

@media(max-width:420px){
  header h1{font-size:19px}
  main{padding:14px 14px 36px}
  main h2{font-size:17.5px}
  table{font-size:13px}
  th,td{padding:8px 9px}
}
'''

INDEX = '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>全部文档 · 学习操作系统</title>
<meta name="theme-color" content="#2563eb">
<link rel="stylesheet" href="./docs.css">
</head>
<body>
<header>
  <a class="back" href="../index.html">← 返回首页</a>
  <h1>全部文档</h1>
  <p class="desc">手机友好的阅读版 · 免费复制 · 欢迎转发</p>
</header>
<main>
{groups}
</main>
<footer>
  <p>学习操作系统 · 教育平权项目</p>
</footer>
</body>
</html>
'''


def build():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    (OUT / 'docs.css').write_text(CSS, encoding='utf-8')

    cards = {}
    built = 0

    for src_rel, out_name, title, desc, group in DOCS:
        src = ROOT / src_rel
        if not src.exists():
            print(f'  ⚠️  跳过（不存在）: {src_rel}')
            continue

        md = src.read_text(encoding='utf-8')
        body, toc = convert(md)

        toc_html = ''
        if len(toc) >= 4:
            items = ''
            for lvl, txt, sid in toc:
                cls = ' class="l3"' if lvl == 3 else ''
                # 目录文字要走 inline()，否则标题里的 **粗体** 会原样显示
                items += f'<li{cls}><a href="#{sid}">{inline(txt)}</a></li>'
            toc_html = TOC.format(items=items)

        page = PAGE.format(title=html.escape(title), desc=html.escape(desc),
                           toc=toc_html, body=body)
        (OUT / out_name).write_text(page, encoding='utf-8')
        cards.setdefault(group, []).append((out_name, title, desc))
        built += 1
        print(f'  ✅ {src_rel}  →  docs/{out_name}  ({len(md)} 字符)')

    groups_html = ''
    for group in ['方法论', '资源', '调研', '其他']:
        if group not in cards:
            continue
        items = ''
        for name, title, desc in cards[group]:
            items += (f'<a class="card" href="./{name}">'
                      f'<h2>{html.escape(title)}</h2>'
                      f'<p>{html.escape(desc)}</p></a>')
        groups_html += f'<div class="sec">{group}</div>{items}'

    (OUT / 'index.html').write_text(INDEX.format(groups=groups_html), encoding='utf-8')
    print(f'\n共生成 {built + 1} 个页面 → {OUT}')


if __name__ == '__main__':
    build()

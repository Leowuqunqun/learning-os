#!/usr/bin/env python3
"""
文档一致性审计
================
目的：确保「面向家长的材料」（打印版、清单、总纲等）不会出现
      「证据简报里已标注为弱/已证伪，但别处仍在夸大」的情况。

背景：证据诚实是本项目的红线。但文档分散在多个文件，
      人工很难保证口径一致。这个脚本把红线变成可自动检查的规则。

用法：python3 tools/audit-claims.py
返回码：0 = 全部通过；1 = 发现不一致
"""
import os
import re
import sys

ROOT = os.path.expanduser('~/教育平权项目')

# 证据简报是唯一事实来源，不参与检查
EVIDENCE = '01-方法论/学习科学证据简报.md'

# 面向家长的材料（这些必须与证据口径一致）
CONSUMER_DOCS = [
    '01-方法论/学习操作系统-总纲.md',
    '01-方法论/四动作执行手册.md',
    '01-方法论/学段适配指南.md',
    '01-方法论/打印版-零门槛.html',
    '01-方法论/第一周打勾清单.html',
    '02-资源地图/K12免费教育资源地图.md',
    '04-调研/教育平权与推广路径.md',
    'README.md',
]

# ============================================================
# 规则：(名称, 触发的正则, 是否要求附近有免责表述, 免责正则, 说明)
# ============================================================
RULES = [
    {
        'name': '交错练习不得无保留推荐',
        'trigger': r'交错|混着练|打乱顺序',
        # 只有在"推荐做法"语境下才要求注释
        'context': r'混着练|打乱顺序|交错练习（',
        'require_note': r'词汇|背单词|单?词|g\s*=\s*0?\.3|小得多|数学.{0,6}理科|理科.{0,6}数学|证据',
        'why': '交错练习数学仅 g=0.34，词汇反向（−0.39）。'
               '无条件推荐会让家长把背单词也混着练。',
    },
    {
        'name': '成长型思维不得宣称能提分',
        'trigger': r'成长型思维|成长心态',
        'require_note': r'不(可|能|要|得)宣称|不显著|d\S*=?\s*0?\.05|辅助|证据',

        'why': 'Macnamara & Burgoyne 2023：d=0.05，发表偏倚校正后不显著。',
    },
    {
        'name': '学习风格不得作为有效方法',
        'trigger': r'视觉型|听觉型|动觉型|学习风格',
        'require_note': r'证伪|无效|没有证据|不成立|误区|不要',
        'why': '学习风格匹配（meshing hypothesis）已被证伪。',
    },
    {
        'name': 'SQ3R 不得宣称有科学依据',
        'trigger': r'SQ3R',
        'require_note': r'缺乏|没有严格|证据(薄弱|不足)|未获|不是.{0,6}研究|练习册',
        'why': 'SQ3R 缺乏严格实验支持；只有其中"回忆+复习"两环有证据。',
    },
    {
        'name': '间隔复习天数不得宣称精确有效',
        'trigger': r'第\s*15\s*天|D15|间隔(表|复习点)',
        # 同义表述都要认：不要相信精确天数 / 参数证据薄弱 / 按需调整
        'require_note': (r'证据(薄弱|不足|混杂)|WEAK|MIXED|儿童.{0,12}(参数|证据)'
                         r'|不要相信.{0,10}精确|保守|想不起来就缩短|按需调整'),
        # 声明可能位于文档其他段落（如"每日流程"框与"② 巩固"节相距较远），
        # 所以用更大的检索窗口——同一文档内有总体声明即可。
        'window': 12000,
        'why': '儿童最优间隔参数证据薄弱（WEAK/MIXED）；'
               '经典研究多为大学生。',
    },
    {
        'name': '汉字识字不得夸大，也不得误称空白',
        # 只在「识字教学/学习方法」语境触发；
        # 排除「家长不识字」「认字就能做」这类描述家长能力的表述
        'trigger': r'识字|汉字|认字',
        'context': r'识字(教学|量|法)|汉字(教学|习得|学)|部件|偏旁|集中识字|随文识字'
                   r'|阅读阈值|手写|打字|声调',
        # 2026-10 已更正：汉字习得**有**元分析级证据（Ruan 2024，28 项 RCT，g=0.68）。
        # 因此要求附近说明「验证到什么程度 / 哪里是空白」，
        # 或明确标注为通用原理而非汉语验证。
        'require_note': r'元分析|Ruan|g\s*=?\s*0?\.6|部件|偏旁|声旁|外推|空白'
                        r'|通用学习科学|未.{0,8}验证|证据(不足|薄弱)|港台|简繁|繁体',
        'why': '汉字习得**有**元分析级证据（Ruan 2024，28 项 RCT，总体 g=0.68），'
               '早期「无元分析」的判断已推翻；但间隔/交错练习、阅读阈值、'
               '手写vs打字在汉语中仍是空白。既不可声称「无证据」，'
               '也不可声称「已在汉字学习中验证」。',
    },
]


def read(rel):
    p = os.path.join(ROOT, rel)
    if not os.path.exists(p):
        return None
    return open(p, encoding='utf-8').read()


def strip_html(text):
    """粗略去标签，保留文本用于匹配"""
    t = re.sub(r'<script[\s\S]*?</script>', '', text)
    t = re.sub(r'<style[\s\S]*?</style>', '', t)
    t = re.sub(r'<[^>]+>', ' ', t)
    return t


def check_rule(text, rule, window=260):
    """返回违规片段列表（trigger 命中但附近无免责表述）"""
    hits = []
    for m in re.finditer(rule['trigger'], text):
        # 若规则定义了 context，则必须同时命中 context 才算
        if 'context' in rule:
            lo = max(0, m.start() - 160)
            hi = min(len(text), m.end() + 160)
            if not re.search(rule['context'], text[lo:hi]):
                continue
        w = rule.get('window', window)
        lo = max(0, m.start() - w)
        hi = min(len(text), m.end() + w)
        if not re.search(rule['require_note'], text[lo:hi]):
            snippet = text[max(0, m.start() - 40):m.end() + 60].replace('\n', ' ')
            hits.append(snippet.strip())
    return hits


def main():
    print('=' * 74)
    print('文档一致性审计（对照证据简报的诚实红线）')
    print('=' * 74)

    ev = read(EVIDENCE)
    if not ev:
        print(f'❌ 找不到证据简报：{EVIDENCE}')
        return 1
    print(f'事实来源：{EVIDENCE}（{len(ev)} 字符）\n')

    total_bad = 0
    for rel in CONSUMER_DOCS:
        raw = read(rel)
        if raw is None:
            print(f'⚠️  {rel} 不存在，跳过')
            continue
        text = strip_html(raw)
        problems = []
        for rule in RULES:
            hits = check_rule(text, rule)
            if hits:
                problems.append((rule, hits))
        if not problems:
            print(f'✅ {rel}')
        else:
            total_bad += len(problems)
            print(f'❌ {rel}')
            for rule, hits in problems:
                print(f'     · {rule["name"]}（{len(hits)} 处）')
                print(f'       为什么：{rule["why"]}')
                for h in hits[:2]:
                    print(f'       ↳ {h[:88]}')

    print('\n' + '=' * 74)
    if total_bad:
        print(f'发现 {total_bad} 处口径不一致——需补免责表述或改写')
    else:
        print('全部通过：面向家长的材料与证据口径一致')
    print('=' * 74)
    return 1 if total_bad else 0


if __name__ == '__main__':
    sys.exit(main())

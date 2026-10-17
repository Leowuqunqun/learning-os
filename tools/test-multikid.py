#!/usr/bin/env python3
"""
多孩隔离与「没时间」效率测试
==============================
为什么单独成文件：
目标里明确点名「多孩家庭」和「无时间家庭」，
但此前的证据只有「功能存在」——
· 多孩：只测过 2 个孩子、简单切换
· 无时间：只有文案写着「3 分钟」，从未测量过实际操作成本

本文件把这两条从"声称"变成"测量"：
  ① 3 个孩子交叉操作，验证数据完全不串
  ② 删除中间的孩子，验证无孤儿数据残留
  ③ 测量「从打开 App 到复习完 3 张卡」的点击次数

用法：
    python3 -m http.server 8150 &
    python3 tools/test-multikid.py
返回码：0 = 通过；1 = 失败
"""
import json
import os
import sys
import time
from datetime import date, timedelta

BASE = os.environ.get('MK_BASE', 'http://127.0.0.1:8150')
APP = f'{BASE}/03-PWA/index.html'
MAX_TAPS_FOR_3_CARDS = 8      # 超过则认为对"没时间"的家长负担过重

ok = fail = 0
problems = []


def check(name, cond, extra=''):
    global ok, fail
    if cond:
        print(f'  ✅ {name}')
        ok += 1
    else:
        print(f'  ❌ {name} {extra}')
        fail += 1
        problems.append(name)


def main():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print('❌ 需要 playwright：pip install playwright && python3 -m playwright install webkit')
        return 1

    def iso(n):
        return (date.today() - timedelta(days=n)).isoformat()

    try:
        with sync_playwright() as p:
            b = p.webkit.launch()

            # ========== ① 多孩隔离 ==========
            print('=' * 62)
            print('多孩隔离与「没时间」效率测试')
            print('=' * 62)
            print('\n【1】3 个孩子交叉操作')
            ctx = b.new_context(viewport={'width': 390, 'height': 844},
                                is_mobile=True, has_touch=True)
            pg = ctx.new_page()
            errs = []
            pg.on('pageerror', lambda e: errs.append(str(e)))
            pg.on('dialog', lambda d: d.accept())
            pg.goto(APP, wait_until='networkidle')
            pg.wait_for_timeout(2200)
            for _ in range(3):
                pg.get_by_role('button', name='下一步').click()
                pg.wait_for_timeout(180)
            pg.get_by_role('button', name='开始使用').click()
            pg.wait_for_timeout(500)

            def add_kid(name, stage):
                pg.locator('nav button', has_text='更多').click()
                pg.wait_for_timeout(400)
                pg.locator('#kidFormBtn').click()
                pg.wait_for_timeout(300)
                pg.fill('#kidName', name)
                pg.select_option('#kidStage', stage)
                pg.locator('button', has_text='保存').first.click()
                pg.wait_for_timeout(800)

            def add_card(text):
                pg.locator('nav button', has_text='知识卡').click()
                pg.wait_for_timeout(400)
                pg.fill('#cFront', text)
                pg.fill('#cBack', text + '-答案')
                pg.get_by_role('button', name='添加').click()
                pg.wait_for_timeout(700)
                return pg.locator('#cardCount').inner_text()

            def switch_to(name):
                pg.locator('nav button', has_text='更多').click()
                pg.wait_for_timeout(500)
                row = pg.locator('#kidList .item').filter(has_text=name)
                btn = row.locator('button', has_text='切换')
                if btn.count() > 0:
                    btn.first.click()
                    pg.wait_for_timeout(700)
                    return True
                return False

            add_kid('老大', 'senior'); add_kid('老二', 'mid'); add_kid('老三', 'low')
            check('3 个档案都存在', pg.locator('#kidList .item').count() == 3)

            r = add_card('老三卡A')
            check('老三 1 张', r == '1', r)
            switch_to('老大')
            add_card('老大卡A'); r = add_card('老大卡B')
            check('老大 2 张', r == '2', r)
            switch_to('老二')
            add_card('老二卡A'); add_card('老二卡B'); r = add_card('老二卡C')
            check('老二 3 张', r == '3', r)

            for name, expect, mark in [('老大', '2', '老大卡'),
                                       ('老二', '3', '老二卡'),
                                       ('老三', '1', '老三卡')]:
                switch_to(name)
                pg.locator('nav button', has_text='知识卡').click()
                pg.wait_for_timeout(500)
                cnt = pg.locator('#cardCount').inner_text()
                fronts = pg.locator('#cardList .t').all_inner_texts()
                check(f'{name}：卡片数 {expect}', cnt == expect, cnt)
                check(f'{name}：内容不串',
                      bool(fronts) and all(mark in f for f in fronts), fronts[:3])

            # ========== ② 删除中间孩子 ==========
            print('\n【2】删除中间的老二')
            pg.locator('nav button', has_text='更多').click()
            pg.wait_for_timeout(500)
            row = pg.locator('#kidList .item').filter(has_text='老二')
            row.locator('button', has_text='删').first.click()
            pg.wait_for_timeout(1200)
            check('删后剩 2 个档案', pg.locator('#kidList .item').count() == 2)

            for name, expect in [('老大', '2'), ('老三', '1')]:
                switch_to(name)
                pg.locator('nav button', has_text='知识卡').click()
                pg.wait_for_timeout(500)
                check(f'删除后 {name} 数据完好（{expect} 张）',
                      pg.locator('#cardCount').inner_text() == expect)

            db = json.loads(pg.evaluate(
                "localStorage.getItem('learnos.adapter.local.v1')"))
            orphan = [c for c in db['cards'].values() if c['kidId'] not in db['kids']]
            check('★无孤儿卡片残留', len(orphan) == 0, f'{len(orphan)} 张')
            check('知识卡总数 = 3', len(db['cards']) == 3, len(db['cards']))
            check('无 JS 错误', not errs, errs[:2])
            ctx.close()

            # ========== ③ 「没时间」的点击成本 ==========
            print('\n【3】「没时间」家庭的点击成本（3 张待复习卡）')
            cards = {f'c{i}': {"id": f'c{i}', "kidId": "k1", "front": f"问题{i}",
                              "back": f"答案{i}", "subject": "数学", "step": 0,
                              "okCount": 0, "due": iso(1), "createdAt": iso(3)}
                     for i in range(1, 4)}
            data = {"kids": {"k1": {"id": "k1", "nickname": "娃", "stage": "high",
                                    "createdAt": iso(5)}},
                    "cards": cards, "errors": {}}
            ctx2 = b.new_context(viewport={'width': 390, 'height': 844},
                                 is_mobile=True, has_touch=True)
            pg2 = ctx2.new_page()
            pg2.add_init_script(
                "localStorage.setItem('learnos.onboarded','1');"
                "localStorage.setItem('learnos.currentKid','k1');"
                "localStorage.setItem('learnos.adapter.local.v1', " +
                json.dumps(json.dumps(data, ensure_ascii=False)) + ");")
            pg2.goto(APP, wait_until='networkidle')
            pg2.wait_for_timeout(2200)

            taps = 0
            t0 = time.time()
            pg2.get_by_role('button', name='开始自测复习').click()
            taps += 1
            pg2.wait_for_timeout(600)
            for _ in range(3):
                pg2.get_by_role('button', name='看答案').click()
                taps += 1
                pg2.wait_for_timeout(400)
                pg2.get_by_role('button', name='想起来了').click()
                taps += 1
                pg2.wait_for_timeout(500)
            elapsed = time.time() - t0

            print(f'     共 {taps} 次点击，机器耗时 {elapsed:.1f} 秒'
                  f'（平均 {taps/3:.1f} 次/张）')
            check(f'★3 张卡的操作次数 ≤ {MAX_TAPS_FOR_3_CARDS} 次',
                  taps <= MAX_TAPS_FOR_3_CARDS, f'{taps} 次')
            check('复习完成后待复习归零',
                  pg2.locator('#sDue').inner_text() == '0',
                  pg2.locator('#sDue').inner_text())
            ctx2.close()
            b.close()
    except Exception as e:
        print(f'❌ 测试异常: {e}')
        return 1

    print('\n' + '=' * 62)
    if fail:
        print(f'通过 {ok} 项，失败 {fail} 项')
        for x in problems:
            print(f'  · {x}')
    else:
        print(f'全部通过（{ok} 项）—— 多孩隔离可靠，操作成本可接受')
    print('=' * 62)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())

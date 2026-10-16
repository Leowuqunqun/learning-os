#!/usr/bin/env python3
"""
Safari/WebKit 引擎测试
========================
为什么需要：
本项目的目标设备是 **iPad**，而 iPad 上所有浏览器都用 WebKit 引擎
（Safari 以及「添加到主屏幕」后的 PWA）。
但此前所有浏览器测试都只在 Chromium 上跑 —— 
**验证的引擎和目标设备的引擎根本不是同一个**。

这个盲区有多严重：Chromium 与 WebKit 在以下方面差异明显
  · speechSynthesis 语音列表（Chromium headless 永远报 0）
  · PWA/Service Worker 生命周期
  · localStorage 在隐私模式下的行为
  · CSS 渲染细节

还有一个额外收获：**WebKit 能报告真实语音**，
所以「不识字的家长能否用语音」这个功能，只有在这里才能验证。

用法：
    python3 -m http.server 8150 &
    python3 -m playwright install webkit     # 首次
    python3 tools/test-safari.py
返回码：0 = 通过；1 = 失败
"""
import json
import os
import sys

BASE = os.environ.get('SAFARI_BASE', 'http://127.0.0.1:8150')
APP = f'{BASE}/03-PWA/index.html'

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

    try:
        with sync_playwright() as p:
            b = p.webkit.launch()
            ctx = b.new_context(
                viewport={'width': 390, 'height': 844},
                device_scale_factor=3, is_mobile=True, has_touch=True,
                user_agent=('Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) '
                            'AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 '
                            'Mobile/15E148 Safari/604.1'))
            page = ctx.new_page()
            errs = []
            page.on('pageerror', lambda e: errs.append(str(e)))
            page.on('console', lambda m: errs.append('console: ' + m.text)
                    if m.type == 'error' else None)

            print('=' * 62)
            print('Safari / WebKit 引擎测试（iPad 实际使用的引擎）')
            print('=' * 62)

            print('\n【1】加载与应用启动')
            page.goto(APP, wait_until='networkidle')
            page.wait_for_timeout(2500)
            check('★无 JS 运行时错误', len(errs) == 0, f'{errs[:2]}')
            check('标题正确', page.title() == '学习操作系统', page.title())
            check('导航渲染（6 标签）', page.locator('nav button').count() == 6,
                  page.locator('nav button').count())

            print('\n【2】冷启动旅程')
            check('新用户看到引导', page.locator('#guide').is_visible())
            for _ in range(3):
                page.get_by_role('button', name='下一步').click()
                page.wait_for_timeout(200)
            check('引导可走完', page.locator('#gStep').inner_text() == '4 / 4',
                  page.locator('#gStep').inner_text())
            page.get_by_role('button', name='开始使用').click()
            page.wait_for_timeout(500)

            page.locator('nav button', has_text='更多').click()
            page.wait_for_timeout(400)
            page.get_by_role('button', name='＋ 添加孩子').click()
            page.wait_for_timeout(400)
            page.fill('#kidName', 'Safari娃')
            page.select_option('#kidStage', 'high')
            page.get_by_role('button', name='保存').click()
            page.wait_for_timeout(800)
            check('★能建孩子档案', page.locator('#kidList .item').count() == 1)

            page.locator('nav button', has_text='知识卡').click()
            page.wait_for_timeout(400)
            page.fill('#cFront', 'Safari 卡')
            page.fill('#cBack', 'Safari 答')
            page.get_by_role('button', name='添加').click()
            page.wait_for_timeout(800)
            check('★能添加知识卡', page.locator('#cardCount').inner_text() == '1')

            print('\n【3】语音朗读（只有真实 WebKit 才能验证）')
            tts = json.loads(page.evaluate("""(() => {
              const vs = speechSynthesis.getVoices() || [];
              const zhCN = vs.filter(v => /zh[-_]CN/i.test(v.lang));
              return JSON.stringify({
                supported: 'speechSynthesis' in window,
                total: vs.length,
                zhCN: zhCN.length,
                sample: zhCN.slice(0,1).map(v => v.name)
              });
            })()"""))
            print(f'     语音总数 {tts["total"]}，中文 {tts["zhCN"]} 个 {tts["sample"]}')
            check('语音合成 API 存在', tts['supported'] is True)
            check('★有中文语音可用', tts['zhCN'] >= 1, tts)

            spoken = page.evaluate("""(async () => {
              return await new Promise(resolve => {
                try {
                  const u = new SpeechSynthesisUtterance('测试');
                  u.lang = 'zh-CN';
                  u.onstart = () => resolve('started');
                  u.onerror = e => resolve('error:' + e.error);
                  speechSynthesis.speak(u);
                  setTimeout(() => resolve('silent'), 1500);
                } catch (e) { resolve('throw:' + e.message); }
              });
            })()""")
            check('★实际能触发朗读', spoken == 'started', spoken)

            print('\n【4】存储与离线能力')
            check('数据写入 localStorage',
                  bool(page.evaluate("localStorage.getItem('learnos.adapter.local.v1')")))
            check('Service Worker 可用',
                  page.evaluate("('serviceWorker' in navigator)") is True)


            print('\n【6】低配设备兼容性（模拟旧安卓/旧 WebView）')
            # 项目红线之一是「低配设备可用」。
            # structuredClone 是 2022 年才普及的 API，
            # 旧设备上直接调用会让整个应用无法启动。
            # 用**独立 context**，避免复用上一个页面的 localStorage
            # （否则断言「档案数==1」会因残留数据而误判）
            ctx2 = b.new_context(
                viewport={'width': 390, 'height': 844},
                device_scale_factor=3, is_mobile=True, has_touch=True)
            page2 = ctx2.new_page()
            errs2 = []
            page2.on('pageerror', lambda e: errs2.append(str(e)))
            page2.add_init_script("delete window.structuredClone;")
            page2.goto(APP, wait_until='networkidle')
            page2.wait_for_timeout(2500)
            # 新页面同样会弹引导，先关掉再操作
            if page2.locator('#guide').is_visible():
                for _ in range(3):
                    page2.get_by_role('button', name='下一步').click()
                    page2.wait_for_timeout(200)
                page2.get_by_role('button', name='开始使用').click()
                page2.wait_for_timeout(500)
            nav2 = page2.locator('nav button').count()
            check('★无 structuredClone 时应用仍可启动', nav2 == 6 and not errs2,
                  f'导航 {nav2}，错误 {errs2[:1]}')
            if nav2 == 6 and not errs2:
                # 进一步确认存储功能可用（这是 structuredClone 降级的关键路径）
                page2.locator('nav button', has_text='更多').click()
                page2.wait_for_timeout(500)
                page2.locator('button', has_text='添加孩子').click()
                page2.wait_for_timeout(500)
                page2.fill('#kidName', '旧机娃')
                page2.locator('button', has_text='保存').first.click()
                page2.wait_for_timeout(1200)
                cnt = page2.locator('#kidList .item').count()
                saved = page2.evaluate(
                    "!!localStorage.getItem('learnos.adapter.local.v1')")
                check('★旧设备上仍能保存数据', cnt == 1 and saved,
                      f'档案 {cnt}，已存储 {saved}')
            ctx2.close()

            print('\n【5】布局')
            d = json.loads(page.evaluate(
                "JSON.stringify({vw:document.documentElement.clientWidth,"
                "sw:document.body.scrollWidth})"))
            print(f'     视口 {d["vw"]} / 内容 {d["sw"]}')
            check('★无横向溢出', d['sw'] <= d['vw'] + 4, d)
            check('全程无 JS 错误', len(errs) == 0, errs[:3])

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
        print(f'全部通过（{ok} 项）—— Safari 引擎下可正常使用')
    print('=' * 62)
    return 1 if fail else 0


if __name__ == '__main__':
    sys.exit(main())

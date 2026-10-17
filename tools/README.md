# tools

## build-docs.py

把 Markdown 渲染成手机友好的静态 HTML。

```bash
python3 tools/build-docs.py
```

- **零依赖**：自己实现所需的 Markdown 子集，不需要 pandoc / markdown-it
- 输出到 `docs/`，并生成索引页 `docs/index.html`
- 改动任何 `.md` 后**必须重跑**，否则网页还是旧的

### 为什么需要它

GitHub Pages 对 `.md` 返回 `Content-Type: text/markdown`，
手机浏览器会直接下载或显示成纯文本，表格和标题全乱。

### 已处理的坑

| 坑 | 处理 |
|---|---|
| 表格在手机上撑破页面 | 包一层 `.tw`，可横向滚动 + 提示"→ 可左右滑动" |
| 代码块超宽 | `pre` 设 `overflow-x:auto` + `max-width:100%` |
| `**粗体**` 内含 `*斜体*` 时匹配失败 | 用 `.+?` 非贪婪而非 `[^*]+` |
| 目录里的 `**粗体**` 原样显示 | 目录文字也要走 `inline()` |
| 引用块嵌套调用返回 tuple | `convert()` 返回 `(html, toc)`，递归时解包 |

## audit-mobile.py

全站手机适配审计：把每个页面放进真实 360px iframe，检测横向溢出。

```bash
python3 -m http.server 8150          # 先起服务
python3 tools/audit-mobile.py
```

### 血的教训：不要用 CSS 模拟手机

我第一版审计用 `<style>body{width:360px !important}</style>` 强制宽度，
结果**报了 10 个假阳性**——它会改变盒模型（加 margin、改百分比基准），
页面表现和真实手机完全不同。

正确做法：`_measure.html` 把目标页放进 `width:360px` 的 iframe。
只有 iframe 才能真正约束视口。

同理，headless Chrome 的 `--window-size` 有 ~485px 下限，
低于此值不生效——所以截图看起来"被切掉"往往是假象。

## audit-reachability.py

可达性审计：从入口出发能否走到每个产出。

```bash
python3 tools/audit-reachability.py
```

### 为什么需要它

这个项目反复出现同一类失误——**东西做了，但用户走不到**：

| 轮次 | 失误 |
|---|---|
| 3 | 文档渲染成 HTML 了，但首页仍链到 `.md`（手机上是纯文本） |
| 6 | 新增了汉字综述，但没加进 `build-docs.py` 的渲染清单 |
| 6 | 文档都齐了，但 PWA 里没有任何入口指向它们 |
| 7 | `.md` 源里的链接按仓库根写，渲染到 `docs/` 后全部断链 |

这类问题**功能测试查不出来**（页面 200、代码无 bug、无 JS 报错），
只有站在「用户能不能真的用到」的角度审计才能发现。

### 它检查什么

1. 从 `index.html` 和 `03-PWA/index.html` 出发做 BFS，得到可达集合
2. 与应可达资产对比，报告**孤儿**（存在但走不到）
3. 检查是否有页面直接链到 `.md`（手机上会变纯文本）

## verify-deploy.py

部署验证：push 之后确认 GitHub Pages 真的构建好、资源真的能访问。

```bash
python3 tools/verify-deploy.py          # 直接检查
python3 tools/verify-deploy.py --wait   # 先等构建完成
python3 tools/verify-deploy.py --json   # 机器可读
```

检查 22 项资源的：HTTP 状态、Content-Type、内容关键字。

### 两个踩过的坑

1. **urllib 不会自动编码中文路径**（curl 会）。不显式 `quote()` 会直接失败，
   表现为 HTTP 0——看起来像部署问题，其实是脚本问题。
2. **JS 的 MIME 是 `application/javascript`**，不是 `text/javascript`。
   写错期望值会产生假失败。

## smoke-test.py

**冒烟测试** —— 防「静默炸掉」。这是最重要的一套，建议每次改动后先跑它。

```bash
cd ~/教育平权项目 && python3 -m http.server 8150 &
python3 tools/smoke-test.py
```

断言三件事：
1. **无 JS 运行时错误**（含模块解析错误）
2. **关键函数全部挂在 window**（少一个，对应按钮就是死的）
3. **应用完成初始化**（数据加载 + DOM 渲染 + 核心交互可触发）

### 为什么必须有它

2026-10 出过一次致命 bug：重写复习流程时删掉 `showAnswer`，
但 `Object.assign(window, {... showAnswer ...})` 的引用没清理。
那行在**模块加载时执行**，抛 ReferenceError 中断整个模块，
`bootStore`/`loadDB`/`renderAll` 全不执行。

表现极具迷惑性：**localStorage 里数据完好，但界面显示「知识卡 0」**——
像数据丢了，其实是代码没跑。

当时四套审计全部漏掉：

| 审计 | 盲区 |
|---|---|
| migrate.test.mjs | Node 环境，不加载 index.html |
| audit-mobile.py | 只测布局，页面能渲染即通过 |
| audit-reachability.py | 只测链接可达 |
| verify-deploy.py | 只测 HTTP 200 + 内容关键字 |

共同盲区：**都在验证「改动本身」，没有验证「改动有没有破坏别的」**。

冒烟测试已通过反向验证：故意重新引入该 bug，它能准确捕获
（报出 ReferenceError、24 个函数缺失、数据加载为 0）。

## test-safari.py

**Safari / WebKit 引擎测试** —— 目标设备是 iPad，而 iPad 上所有浏览器都用 WebKit。

```bash
python3 -m http.server 8150 &
python3 -m playwright install webkit    # 首次
python3 tools/test-safari.py
```

### 为什么必须有它

项目文档明确写「iPad Safari → 添加到主屏幕」，
但此前**所有浏览器测试都只在 Chromium 上跑** ——
验证的引擎和目标设备的引擎根本不是同一个。

Chromium 与 WebKit 的差异点：speechSynthesis 语音列表、
Service Worker 生命周期、隐私模式下的 localStorage、CSS 渲染细节。

### 一个意外收获：只有这里能验证语音

Chromium headless **永远报告 0 个语音**（无音频子系统），
所以「不识字的家长能否用语音」这个功能一直无法验证。

WebKit 报告 **68 个语音，其中 1 个中文（Tingting/zh-CN）**，
并且实测朗读能真正触发（`onstart` 回调触发，返回 `started`）。

这条验证补上了一个长期缺口：语音功能从「不报错」升级为「确实能用」。

## audit-redlines.py

**设计红线审计** —— 检查文档里的承诺是否与实现一致。

```bash
python3 tools/audit-redlines.py
```

### 为什么需要

README 里长期写着「单文件 20KB」，但实际早已是 **67KB / 4 个模块**。
承诺写下来之后没人再核对——**写在文档里的承诺，往往正是最没被验证的**。

本脚本把六条红线变成可执行断言：

| 红线 | 检查方式 |
|---|---|
| ① 零成本 | 无 package.json、无外部 CDN/字体资源 |
| ② 离线可用 | SW 存在、预缓存清单里的文件真实存在 |
| ③ 低配可用 | 规模上限、**未直接使用旧设备缺失的 API** |
| ④ 低文化门槛 | 有语音朗读、有打印版 |
| ⑤ 数据自主 | **业务代码零网络上报**、有导出/删除 |
| ⑥ 可复制 | 有说明文档与推广路径 |

外加第 7 项：**文档中的数字与实际是否一致**。

### 已反向验证

· 把 README 数字改回 20KB → ❌ 报「写 20KB，实际 67KB」
· 注入一个外部 CDN 样式 → ❌ 报「无外部资源依赖」

两项均准确捕获，说明断言有真实区分力。

## check-all.sh

**一条命令跑完所有检查。**

```bash
bash tools/check-all.sh            # 完整（约 3 分钟，含浏览器）
bash tools/check-all.sh --quick    # 仅静态（约 5 秒，无需服务）
```

### 为什么需要

到第 24 轮已有 10 套测试，前置条件各不相同：
有的要本地服务、有的要 CDP 调试端口、有的纯静态。
每轮手动逐个跑既费时又容易漏。

`check-all.sh` 自动处理：启动/回收本地服务、起停调试版 Chrome、
按可用性决定跳过（如未装 playwright 就跳过 Safari 测试）。

### 覆盖的 10 套

| 类别 | 测试 |
|---|---|
| 静态（--quick 也跑） | 设计红线、证据口径、可达性、数据迁移 |
| 需本地服务 | 冒烟、手机适配、Safari 引擎 |
| 需 CDP | 离线可用性、低带宽加载 |
| 需联网 | 线上部署验证 |

### 退出码约定

- `0` = 全部通过
- `1` = 有失败（并列出失败项名称）

**这一点做过反向验证**：注入缺陷后退出码为 1，恢复后为 0。
（最初实现有个 bug：失败分支打印错误后仍 `exit 0`，
导致 CI 会误判为成功——已修复。）

## test-multikid.py

**多孩隔离 + 「没时间」效率测试。**

```bash
python3 -m http.server 8150 &
python3 tools/test-multikid.py
```

### 为什么单独成文件

目标里点名了「多孩家庭」和「无时间家庭」，但此前证据只有「功能存在」：

| 条款 | 此前的证据 | 现在的证据 |
|---|---|---|
| 多孩家庭 | 测过 2 个孩子、简单切换 | 3 个孩子交叉操作、删除中间孩子、**无孤儿数据** |
| 无时间家庭 | 文案写着「3 分钟」 | **实测 7 次点击完成 3 张卡**（平均 2.3 次/张） |

第 3 节把「没时间」从**声称**变成**测量**：
断言 3 张卡的操作次数 ≤ 8 次。若将来加功能导致流程变长，会立刻发现。

## check-links.py

**资源地图的链接健康检查** —— 网页会失效，承诺必须定期复查。

```bash
python3 tools/check-links.py            # 检查（约 10 秒）
python3 tools/check-links.py --update   # 检查并更新文档里的复查日期
```

### 为什么需要

资源地图承诺「逐条实测的免费优质资源」，但**上次全量验证在 25 轮之前**。
失效链接对家长是实际损失：点进去打不开，会怀疑整份清单。

### 三类结果，区分对待

| 分类 | 含义 | 处理 |
|---|---|---|
| ✅ 可达 | HTTP 200 | 正常 |
| 🔒 反爬 | 403/429/503 | **站点存在，只是拒绝机器人**，不计失效 |
| ❌ 失效 | 404 / 连接失败 | 需人工确认或替换 |
| 📌 预期失效 | 文档里**故意写的反例** | 如汉典「用 Unicode 编码会 404」，本就该失败 |

### 两个实现上的坑

1. **中文 URL 必须百分号编码**：`zdic.net/hans/笔` 直接请求会抛
   `UnicodeEncodeError`，需 `urllib.parse.quote`
2. **Markdown 反引号会粘进 URL**：`https://x.com` 后面常跟一个 `` ` ``，
   不剥离会拼出错误地址

### 首次全量结果（2026-10-18）

65 个 URL：**59 可达 / 3 反爬 / 0 失效 / 1 预期反例** —— 全部健康。

## 离线外链行为的边界（03-PWA/offline-links.test.mjs）

**Service Worker 的 scope 只到 `03-PWA/`**，管不到 `../docs/` 与 `../01-方法论/`。

因此：

| 内容 | 离线可用？ |
|---|---|
| App 内的记录 / 复习 / 统计 / 档案 | ✅ 完全可用（SW 预缓存 8 个文件） |
| `docs/*.html`（9 个链接指向） | ❌ 打不开 |
| 打印材料 2 个页面 | ❌ 打不开 |

**这不是 bug，是架构取舍**：把 docs 全量缓存会让体积从 88KB 涨到约 300KB，
对低带宽家庭是真实负担，而这些页面并非常用功能。

**所以做了友好降级**：离线时这 9 个链接置灰、悬停有说明，
点击弹提示「这个页面需要联网。你的学习记录不受影响，离线也能正常记 ✅」，
而不是让用户撞白屏。

`offline-links.test.mjs` 有 9 项断言守护这个行为。

### 超时必须给足：慢站会造成假警报

首次跑 check-links.py 时 `ebama.net` 报「SSL 握手超时」，
手工重试 3 次：**20 秒失败 / 12.8 秒成功 / 7.7 秒成功**。

它是**慢**，不是失效。原来设 15 秒超时 + 2 次重试，
正好卡在它的响应时间附近 → 假警报。

已改为 **30 秒超时 + 3 次重试**，并在资源地图里标注该站很慢。

> 假警报比漏报更有害：会让人逐渐不信任检查结果，
> 真出问题时反而被忽略。（部署验证那次也是同一类问题。）

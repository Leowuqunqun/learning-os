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

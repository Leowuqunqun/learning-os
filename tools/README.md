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

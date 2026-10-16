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

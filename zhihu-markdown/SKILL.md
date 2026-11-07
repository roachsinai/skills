---
name: zhihu-markdown
description: 抓取知乎回答/专栏文章并转为离线 Markdown 文档（图片本地化、代码块、公式），内置反爬方法链与失效自更新协议。用户给出 zhihu.com 或 zhuanlan.zhihu.com 链接要求保存/下载/转 Markdown，或知乎抓取失败需要换方法时使用。
whenToUse: 用户提供知乎链接（问题/回答/专栏文章）并希望保存为 Markdown；或知乎抓取遇到 403/风控/验证码需要诊断并尝试新方法。
---

# 知乎 → Markdown 抓取转换

把知乎页面（回答 / 专栏文章）保存为离线可用的 Markdown 文档：
正文 + 元信息头（作者/时间/赞同数/原文链接）+ 图片本地下载（绕过防盗链）
+ 代码块（语言识别）+ LaTeX 公式（`$...$`）+ 完整性校验。

## 快速流程

1. **定位脚本目录**：本 skill 所在目录的 `scripts/` 子目录
   （本环境的实际位置：`<workspace>/.dsh/skills/zhihu-markdown/scripts/`，
    workspace 即会话工作目录；用 `ls` 或 glob 确认）。
2. **抓取 DOM**：
   ```bash
   NODE_BIN=<node路径> bash <skill目录>/scripts/fetch.sh '<知乎URL>' /tmp/zhihu_page.html
   ```
   - 需要可用的 `node`（DSH 环境先用 load_workspace_dependencies 拿到路径并 export NODE_BIN）
   - 需要本机装有 Chrome/Chromium/Edge（自动探测，可用 CHROME_BIN 指定）
   - 会短暂打开一个**可见的 Chrome 窗口**，这是绕过无头检测的关键，属正常现象
3. **转换 + 下载图片 + 校验**：
   ```bash
   <python3> <skill目录>/scripts/convert.py /tmp/zhihu_page.html --out-dir <目标目录> [--slug 文件名] [--answer-id 回答ID]
   ```
   - python 需要 lxml（DSH 自带的 python 有）
   - URL 形如 `.../answer/<id>` 时从 URL 提取；问题页（不带 answer）会取第一个回答
   - 脚本输出校验报告，`verify: PASS` 才算成功
4. **交付**：`<slug>.md` + `<slug>.assets/` 图片目录，用 present 展示。
5. **记录**：按下方「自动更新协议」更新本文件的「方法记录」表。

## 方法链（按序尝试，状态随验证更新）

| # | 方法 | 状态 | 最近验证 |
|---|------|------|----------|
| 1 | **有头 Chrome + CDP**（fetch.sh：先开首页种 cookie，再 location.href 跳目标页，带 Referer 和真实视口） | ✅ 首选 | 2026-11-07 |
| 2 | 无头 Chrome `--headless=new --dump-dom`（能过 zse-ck JS 挑战，但问题/文章页被风控拦，仅首页可用） | ⚠️ 受限 | 2026-11-07 |
| 3 | web_fetch 工具 / curl 带浏览器头直接抓 | ❌ 403 + zse-ck JS 挑战 | 2026-11-07 |
| 4 | API `www.zhihu.com/api/v4/answers/<id>?include=content` | ❌ 需登录 | 2026-11-07 |
| 5 | 存档/代理站（web.archive.org、archive.ph、r.jina.ai） | ❌ 大陆网络不可达 | 2026-11-07 |

### 方法 1 失效时的变体梯度（逐个尝试，每个都记录）

- a. 直接重试 2-3 次（zhihu_cdp.mjs 内置重试；风控提示是"**暂时**限制本次访问"）
- b. 删除 profile 目录重来：`rm -rf /tmp/zhihu-skill-chrome-profile`
- c. 换调试端口：`CDP_PORT=19223`
- d. 加长等待：改 zhihu_cdp.mjs 中的 sleep / waitForContent 超时
- e. 预热页面换成 `https://www.zhihu.com/explore` 或先访问问题页再进回答页
- f. 换浏览器：`CHROME_BIN=</Applications/Microsoft Edge.app/...>` 等
- g. 清 DNS 缓存 / 换网络
- h. **请用户协助**（永远可行的兜底）：
  - 用户在自己浏览器打开页面 → `Cmd+S` 保存 HTML 到 workspace → `convert.py` 直接转换
  - 或用户直接复制粘贴正文文字

## 自动更新协议（每次使用本 skill 必须执行）

这是本 skill 的核心机制：**方法会失效，skill 必须跟着演化**。

### 每次运行后（无论成败）

编辑本文件的「方法记录」表，追加一行：`日期 | 页面类型 | 方法/变体 | 结果`。

### 成功时

- 更新所用方法的「最近验证」日期。
- 如果用了新的变体/新方法（不在上表中的），把它写进方法链或变体梯度，注明原理和日期。

### 失败时

1. 重试当前方法 1-2 次（间隔 10s+）。
2. 按方法链顺序换下一个方法；方法 1 的变体按 a→h 顺序试。
3. 每个尝试都记录到「试验记录」（含失败症状，如 HTTP 码/错误 JSON code）。
4. 某方法**连续失败 ≥2 次**（不同日期）→ 在方法链中标记 ❌ 并把症状写入「失效档案」。
5. 创造新变体时优先考虑：浏览器指纹（UA/sec-ch-ua/WebGL）、行为链路（导航路径/滚动/等待）、
   cookie 状态（profile 复用 vs 重置）、网络路径（直连/代理）。
6. 新方法成功 → 写入方法链顶部为新的首选，旧的降级，注明日期。

### 修改本文件的注意事项

- 直接用 edit 工具改本文件（SKILL.md 正文每次加载都会重新读取，无需重启）。
- 本 skill 的规范位置是 `<workspace>/.dsh/skills/zhihu-markdown/`（workspace 内可免审批编辑，
  这是自更新机制的前提）。如需全局可用（其他 workspace 也能用），可把整个目录复制到
  `~/.dsh/skills/`（需审批），但要注意两处副本会按 rank 优先级取 workspace 份，避免分叉。
- 脚本（scripts/）的改进同样直接改，脚本在执行时读取，改完立即生效。

## 已知坑（排查手册）

- **Chrome 必须带 `--no-sandbox --disable-crashpad --use-mock-keychain`**：
  DSH bash 文件沙箱会阻止 Chrome 自身沙箱初始化（Trace/BPT trap 崩溃）。fetch.sh 已内置。
- **无头模式必被识别**：`sec-ch-ua` 品牌含 `HeadlessChrome`，知乎服务端直接返回
  `{"code":40362,"message":"您当前请求存在异常，暂时限制本次访问"}`。首页能开，问题/文章页全拦。
- **风控是页级 + 指纹级**：同一 profile 首页正常、问题页被拦，说明不是 IP 封禁而是指纹检测。
- **图片防盗链**：`*.zhimg.com` 必须带 `Referer: https://www.zhihu.com/` 才能下载（convert.py 已内置）。
- **大陆网络**：google.com / web.archive.org / archive.ph / r.jina.ai 不可达；bing 可达。
- **折叠态不影响**：回答页 `RichContent-inner--collapsed` 只是视觉折叠，完整正文在 DOM 里。
- **blockquote 常为纯文本节点**（无子元素），转换时必须取元素自身文本，不能只递归子元素。
- **嵌套列表是平铺的**：知乎编辑器把子 `<ul>` 作为 `<ul>` 的直接子元素（不在 `<li>` 内）。
- **公式**：`span.ztext-math` 的 `data-tex` 属性是 LaTeX 源；`MathJax_Preview/MathJax_SVG/
  MJX_Assistive_MathML` 是渲染内部节点，必须跳过（否则文字重复）。
- **链接噪声**：`zhida.zhihu.com/search?...` 是知乎自动实体链接（删）；`link.zhihu.com/?target=...`
  是外链跳转包装（解包还原直链）。
- **图注占位符**：`figcaption` 为"在这里插入图片描述"时跳过。
- **代码块语言**：知乎不保留（全是 language-text），按内容启发式识别（python/cpp）。
- **未登录视角**：目前游客可看回答/文章正文；若未来出现登录墙，走变体 h 请用户协助
  （用户同意后也可尝试 `ZHIHU_PROFILE_DIR` 指向用户真实 Chrome profile 目录抓取）。

## 方法记录（每次使用后追加）

| 日期 | 页面类型 | 方法/变体 | 结果 |
|---|---|---|---|
| 2026-11-07 | 回答 + 专栏 | 方法 1 有头 Chrome + CDP | ✅ 成功（Hyperkernel 回答 / CUDA 笔记文章） |
| 2026-11-07 | 回答 + 专栏 | 方法 1（skill 化后端到端复测） | ✅ 成功（fetch.sh + convert.py 全链路） |

## 试验记录（失败尝试，供诊断参考）

| 日期 | 尝试 | 症状 |
|---|---|---|
| 2026-11-07 | web_fetch / curl 直接抓 | HTTP 403，返回 zse-ck JS 挑战页（650B） |
| 2026-11-07 | 无头 Chrome --dump-dom | 首页 200；问题/文章页返回 `{"code":40362}` JSON（378B） |
| 2026-11-07 | API v4 | `{"code":40353,"message":"请您登录后查看更多专业优质内容"}` |
| 2026-11-07 | web.archive.org / archive.ph / r.jina.ai | 连接超时（HTTP 000，大陆网络不可达） |

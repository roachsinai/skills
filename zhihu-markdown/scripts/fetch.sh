#!/usr/bin/env bash
# fetch.sh — 抓取知乎页面 DOM（有头 Chrome + CDP，绕过反爬）
# 用法: fetch.sh <url> <out.html>
# 环境变量:
#   CHROME_BIN  Chrome/Chromium/Edge 可执行文件路径（默认自动探测）
#   NODE_BIN    node 可执行文件路径（默认 PATH 或 DSH 运行时）
#   CDP_PORT    调试端口（默认 19222）
#   ZHIHU_PROFILE_DIR  Chrome 用户数据目录（默认 /tmp/zhihu-skill-chrome-profile，保留可复用 cookie）
#   CDP_TRIES   失败重试次数（默认 3，传给 zhihu_cdp.mjs）
#
# 注意: 会短暂打开一个可见的 Chrome 窗口（有头模式是绕过知乎无头检测的关键），结束自动关闭。
# Chrome 必须带 --no-sandbox 等参数: DSH bash 文件沙箱会阻止 Chrome 自身沙箱初始化导致崩溃。

set -uo pipefail

URL="${1:?usage: fetch.sh <url> <out.html>}"
OUT="${2:?usage: fetch.sh <url> <out.html>}"
PORT="${CDP_PORT:-19222}"
PROFILE="${ZHIHU_PROFILE_DIR:-/tmp/zhihu-skill-chrome-profile}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# --- 定位浏览器 ---
CHROME_BIN="${CHROME_BIN:-}"
if [[ -z "$CHROME_BIN" ]]; then
  for c in \
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
    "/Applications/Chromium.app/Contents/MacOS/Chromium" \
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge" \
    "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser"; do
    [[ -x "$c" ]] && CHROME_BIN="$c" && break
  done
fi
if [[ -z "$CHROME_BIN" ]] || [[ ! -x "$CHROME_BIN" ]]; then
  echo "ERROR: 未找到 Chrome/Chromium/Edge，请设置 CHROME_BIN" >&2
  exit 1
fi

# --- 定位 node ---
NODE_BIN="${NODE_BIN:-}"
if [[ -z "$NODE_BIN" ]]; then
  if command -v node >/dev/null 2>&1; then
    NODE_BIN="$(command -v node)"
  else
    NODE_BIN="$(ls -t "$HOME"/.dsh/dsh-runtimes/*/dependencies/node/bin/node 2>/dev/null | head -1 || true)"
  fi
fi
if [[ -z "$NODE_BIN" ]] || [[ ! -x "$NODE_BIN" ]]; then
  echo "ERROR: 未找到 node，请设置 NODE_BIN（DSH 环境可用 load_workspace_dependencies 获取）" >&2
  exit 1
fi

mkdir -p "$PROFILE"

# 清理可能残留的旧实例
pkill -f "remote-debugging-port=$PORT" 2>/dev/null || true
sleep 1

# --- 启动有头 Chrome ---
"$CHROME_BIN" --no-sandbox --disable-crashpad --use-mock-keychain \
  --disable-blink-features=AutomationControlled --no-first-run \
  --remote-allow-origins='*' --remote-debugging-port="$PORT" \
  --user-data-dir="$PROFILE" about:blank >/dev/null 2>&1 &
CHROME_PID=$!
trap 'kill $CHROME_PID 2>/dev/null; pkill -f "remote-debugging-port=$PORT" 2>/dev/null' EXIT

sleep 3

# --- CDP 抓取 ---
"$NODE_BIN" "$SCRIPT_DIR/zhihu_cdp.mjs" "$URL" "$OUT" "$PORT"
rc=$?

if [[ $rc -eq 0 ]] && [[ -s "$OUT" ]]; then
  echo "fetch OK: $OUT ($(wc -c < "$OUT") bytes)" >&2
else
  echo "fetch FAILED (exit=$rc)" >&2
fi
exit $rc

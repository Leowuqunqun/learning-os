#!/usr/bin/env bash
# 全量检查 —— 一条命令跑完所有审计
#
# 为什么需要：到第 24 轮已经有 10 套测试，每套前置条件不同
# （有的要本地服务、有的要 CDP 端口、有的纯静态）。
# 每轮手动逐个跑既费时又容易漏。
#
# 用法：
#   bash tools/check-all.sh            # 全量（含需要浏览器的）
#   bash tools/check-all.sh --quick    # 只跑静态检查（秒级，无需服务）
set -u
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
PORT="${CHECK_PORT:-8150}"
QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

PASS=0; FAIL=0; SKIP=0
FAILED_NAMES=()

hr() { printf '─%.0s' {1..68}; echo; }

run() {
  local name="$1"; shift
  printf '\n'
  hr
  echo "▶ $name"
  hr
  if "$@"; then
    PASS=$((PASS+1))
  else
    FAIL=$((FAIL+1)); FAILED_NAMES+=("$name")
  fi
}

skip() {
  echo "  ⏭  $1（$2）"
  SKIP=$((SKIP+1))
}

echo "════════════════════════════════════════════════════════════════════"
echo " 教育平权项目 · 全量检查"
echo " 模式：$([ $QUICK -eq 1 ] && echo '快速（仅静态）' || echo '完整（含浏览器）')"
echo "════════════════════════════════════════════════════════════════════"

# ---------- 静态检查（无需服务） ----------
run "设计红线审计"        python3 tools/audit-redlines.py
run "证据口径审计"        python3 tools/audit-claims.py
run "可达性审计"          python3 tools/audit-reachability.py
run "数据迁移测试"        node 03-PWA/migrate.test.mjs

if [ $QUICK -eq 1 ]; then
  hr
  echo "快速模式：跳过需要本地服务/浏览器的检查"
  echo "（完整检查：bash tools/check-all.sh）"
  hr
  echo
  echo "通过 $PASS · 跳过 $SKIP · 失败 $FAIL"
  if [ $FAIL -gt 0 ]; then
    echo "❌ 失败：${FAILED_NAMES[*]}"
    exit 1
  fi
  echo "✅ 静态检查全部通过"
  exit 0
fi

# ---------- 需要本地服务的检查 ----------
STARTED_SRV=0
if ! curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/03-PWA/index.html"; then
  echo
  echo "启动本地服务（端口 $PORT）…"
  ( cd "$ROOT" && python3 -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1 & )
  STARTED_SRV=1
  sleep 2
fi

run "冒烟测试（应用可用性）"  python3 tools/smoke-test.py
run "手机适配审计"            python3 tools/audit-mobile.py

# Safari/WebKit —— 需要 playwright + webkit
if python3 -c "import playwright" 2>/dev/null; then
  run "Safari 引擎测试"       python3 tools/test-safari.py
else
  skip "Safari 引擎测试" "未安装 playwright"
fi

# 离线与慢网 —— 需要 CDP 调试端口
if [ "${SKIP_CDP:-0}" = "1" ]; then
  skip "离线可用性测试" "显式跳过"
  skip "低带宽测试"     "显式跳过"
else
  CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
  CDP_PORT="${CHECK_CDP_PORT:-9350}"
  if [ -x "$CHROME" ]; then
    PROF="/tmp/checkall-chrome-$$"
    "$CHROME" --headless=new --disable-gpu --no-sandbox \
      --user-data-dir="$PROF" --remote-debugging-port="$CDP_PORT" \
      about:blank >/dev/null 2>&1 &
    CHROME_PID=$!
    sleep 3
    if curl -s --max-time 3 "http://127.0.0.1:$CDP_PORT/json/version" >/dev/null; then
      CDP_PORT="$CDP_PORT" APP_URL="http://127.0.0.1:$PORT/03-PWA/index.html" \
        run "离线可用性测试" node 03-PWA/offline.test.mjs
      CDP_PORT="$CDP_PORT" APP_URL="http://127.0.0.1:$PORT/03-PWA/index.html" \
        run "低带宽加载测试" node 03-PWA/slow-network.test.mjs
    else
      skip "离线可用性测试" "CDP 端口未就绪"
      skip "低带宽测试"     "CDP 端口未就绪"
    fi
    kill $CHROME_PID 2>/dev/null
    rm -rf "$PROF"
  else
    skip "离线可用性测试" "未找到 Chrome"
    skip "低带宽测试"     "未找到 Chrome"
  fi
fi

# 线上部署验证（可选，默认开）
if [ "${SKIP_DEPLOY:-0}" != "1" ]; then
  run "线上部署验证" python3 tools/verify-deploy.py
else
  skip "线上部署验证" "显式跳过"
fi

# 回收本次启动的服务（disown 避免 shell 打印 Terminated）
if [ $STARTED_SRV -eq 1 ]; then
  pkill -f "http.server $PORT" 2>/dev/null || true
  wait 2>/dev/null || true
fi

hr
echo
echo "════════════════════════════════════════════════════════════════════"
echo " 通过 $PASS · 跳过 $SKIP · 失败 $FAIL"
if [ $FAIL -gt 0 ]; then
  echo " 失败项："
  for n in "${FAILED_NAMES[@]}"; do echo "   · $n"; done
  echo "════════════════════════════════════════════════════════════════════"
  exit 1
fi
echo " ✅ 全部通过"
echo "════════════════════════════════════════════════════════════════════"

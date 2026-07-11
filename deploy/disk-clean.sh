#!/usr/bin/env bash
# disk-clean.sh (2026-07-11) — EC2 29G root 反覆被吃滿的對策。
#
# 吃空間的慣犯：/tmp/builder-traces（每次 build 10-16MB）、npm _cacache、
# journald、Next build cache。
#
# 用法：
#   sudo bash deploy/disk-clean.sh                # 無條件清
#   sudo bash deploy/disk-clean.sh --if-above 80  # 使用率 >= 80% 才清
#
# 掛載點：
#   - update.sh / java-update.sh build 前呼叫（--if-above 80）
#   - /etc/cron.d/aiops-disk-clean 每小時跑（--if-above 80）
set -euo pipefail

THRESHOLD=0
if [[ "${1:-}" == "--if-above" ]]; then
  THRESHOLD="${2:-80}"
fi

USAGE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if (( USAGE < THRESHOLD )); then
  echo "disk ${USAGE}% < ${THRESHOLD}% — skip"
  exit 0
fi
echo "disk at ${USAGE}% (threshold ${THRESHOLD}%) — cleaning…"

# 1. builder traces：48 小時前的刪（近期 trace 要留著 debug — 驗 build 先看 trace）
find /tmp/builder-traces -type f -mmin +2880 -delete 2>/dev/null || true

# 2. npm 下載快取（可再生）
rm -rf /root/.npm/_cacache /home/ubuntu/.npm/_cacache 2>/dev/null || true

# 3. journald 上限 200M
journalctl --vacuum-size=200M -q 2>/dev/null || true

# 4. Next build cache（可再生，重建會慢一點）
rm -rf /opt/aiops/aiops-app/.next/cache 2>/dev/null || true

# 5. apt 快取
apt-get clean 2>/dev/null || true

# 還是很滿（>=90%）→ trace 只留 24 小時
USAGE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if (( USAGE >= 90 )); then
  echo "still ${USAGE}% — trimming traces to last 24h"
  find /tmp/builder-traces -type f -mmin +1440 -delete 2>/dev/null || true
fi

echo "done:"
df -h / | tail -1

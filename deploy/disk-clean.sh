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

# 6. DB：execution_logs 的執行 payload（llm_readable_data/event_context）
#    只留 7 天 — 這張表曾長到 7.4GB（磁碟 98% 的真兇）。列與統計欄位保留
#    （patrol 漏斗/追溯不受影響），只清肥欄位；plain VACUUM 讓空間可重用
#    （檔案縮小需手動 VACUUM FULL，日常不需要）。
ENV_FILE=/opt/aiops/java-backend/.env
if [[ -f "$ENV_FILE" ]]; then
  DBU=$(grep '^DB_USER' "$ENV_FILE" | cut -d= -f2)
  export PGPASSWORD=$(grep '^DB_PASSWORD' "$ENV_FILE" | cut -d= -f2)
  psql -h localhost -U "$DBU" -d aiops_db -q -c \
    "UPDATE execution_logs SET llm_readable_data = NULL, event_context = NULL
     WHERE started_at < now() - interval '7 days' AND llm_readable_data IS NOT NULL;" \
    2>/dev/null || true
  psql -h localhost -U "$DBU" -d aiops_db -q -c "VACUUM execution_logs;" 2>/dev/null || true
  # 7. 對話保留 30 天（session 管理裁決 2026-07-12）：連 rich_history blob 一起走
  psql -h localhost -U "$DBU" -d aiops_db -q -c \
    "DELETE FROM agent_tasks WHERE created_at < now() - interval '30 days';
     DELETE FROM agent_sessions WHERE COALESCE(updated_at, created_at) < now() - interval '30 days';" \
    2>/dev/null || true
  unset PGPASSWORD
fi

# 還是很滿（>=90%）→ trace 只留 24 小時
USAGE=$(df --output=pcent / | tail -1 | tr -dc '0-9')
if (( USAGE >= 90 )); then
  echo "still ${USAGE}% — trimming traces to last 24h"
  find /tmp/builder-traces -type f -mmin +1440 -delete 2>/dev/null || true
fi

echo "done:"
df -h / | tail -1

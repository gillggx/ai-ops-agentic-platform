#!/usr/bin/env bash
# deploy/setup.sh — Ubuntu 22.04 LTS 一鍵部署腳本
# 用法：sudo bash setup.sh YOUR_DOMAIN YOUR_EMAIL
# 例如：sudo bash setup.sh aiops.example.com admin@example.com
#
# 本腳本會（針對 4 個 active 服務）：
#   1. 系統依賴（Python 3.11, Node.js 20, Java 21, MongoDB, PostgreSQL, Redis, Nginx, Certbot）
#   2. 建立 /opt/aiops 目錄
#   3. Python virtualenv (sidecar / ontology)
#   4. 建置 ontology_simulator Next.js 前端
#   5. PostgreSQL DB + user
#   6. systemd 服務（aiops-app + aiops-java-api + aiops-python-sidecar + ontology-simulator）
#   7. Nginx + SSL + UFW
#
# 後續更新走 deploy/update.sh + deploy/java-update.sh，不再跑這個腳本。
#
# 2026-05-09 · P1 cleanup: removed fastapi-backend bootstrap (service retired
# 2026-04-25). Java is now the sole DB owner and uses Flyway, not Alembic.

set -euo pipefail
DOMAIN="${1:?用法: bash setup.sh YOUR_DOMAIN YOUR_EMAIL}"
EMAIL="${2:?用法: bash setup.sh YOUR_DOMAIN YOUR_EMAIL}"
APP_DIR="/opt/aiops"
REPO_URL="git@github.com:gillggx/ai-ops-agentic-platform.git"
DEPLOY_KEY="/home/ubuntu/.ssh/github_deploy"

if [ "$EUID" -ne 0 ]; then
  echo "❌  請用 sudo 執行：sudo bash setup.sh $DOMAIN $EMAIL"
  exit 1
fi

# ── 1. 系統依賴 ──────────────────────────────────────────────────
echo "📦  安裝系統依賴..."
apt update -y
apt install -y software-properties-common curl gnupg

# Python 3.11
add-apt-repository -y ppa:deadsnakes/ppa
apt update -y
apt install -y python3.11 python3.11-venv python3.11-dev python3-pip

# Node.js 20
curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
apt install -y nodejs

# Java 21 (Temurin)
apt install -y wget apt-transport-https
mkdir -p /etc/apt/keyrings
wget -O - https://packages.adoptium.net/artifactory/api/gpg/key/public \
  | gpg --dearmor > /etc/apt/keyrings/adoptium.gpg
echo "deb [signed-by=/etc/apt/keyrings/adoptium.gpg] https://packages.adoptium.net/artifactory/deb $(awk -F= '/^VERSION_CODENAME/{print$2}' /etc/os-release) main" \
  > /etc/apt/sources.list.d/adoptium.list
apt update -y
apt install -y temurin-21-jdk

# MongoDB 7.0
apt install -y mongodb-org || {
  curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc \
    | gpg -o /usr/share/keyrings/mongodb-server-7.0.gpg --dearmor
  echo "deb [signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg] https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list
  apt update -y
  apt install -y mongodb-org
}
systemctl enable --now mongod

# PostgreSQL + Nginx + Certbot
apt install -y postgresql postgresql-contrib nginx certbot python3-certbot-nginx

# ── 2. 建立 /opt/aiops 目錄 ─────────────────────────────────────
echo ""
echo "📂  建立 $APP_DIR..."
mkdir -p "$APP_DIR"
if [ ! -d "$APP_DIR/.git" ]; then
  if [ -f "$DEPLOY_KEY" ]; then
    GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=no" \
      git clone "$REPO_URL" "$APP_DIR"
  else
    echo "⚠️   $DEPLOY_KEY 不存在；請手動 git clone $REPO_URL 到 $APP_DIR 後重跑"
    exit 1
  fi
fi

# ── 3. Python virtualenv (sidecar) ──────────────────────────────
echo ""
echo "🐍  設定 Python sidecar virtualenv..."
python3.11 -m venv /opt/aiops/venv_sidecar
/opt/aiops/venv_sidecar/bin/pip install -q --upgrade pip
/opt/aiops/venv_sidecar/bin/pip install -q \
  -r "$APP_DIR/python_ai_sidecar/requirements.txt"

# ── 4. Python virtualenv (ontology) ─────────────────────────────
echo ""
echo "🐍  設定 OntologySimulator virtualenv..."
python3.11 -m venv /opt/aiops/venv_ontology
/opt/aiops/venv_ontology/bin/pip install -q --upgrade pip
/opt/aiops/venv_ontology/bin/pip install -q \
  -r "$APP_DIR/ontology_simulator/requirements.txt"

# ── 5. 建置 ontology_simulator Next.js 前端 ─────────────────────
echo ""
echo "🔨  建置 ontology_simulator/frontend..."
cd "$APP_DIR/ontology_simulator/frontend"
npm ci --silent
npm run build
echo "✅  Next.js build 完成 → ontology_simulator/frontend/out/"

# ── 6. 環境變數檔案（範本提示） ─────────────────────────────────
echo ""
echo "⚙️   檢查環境變數檔案..."
JAVA_ENV="$APP_DIR/java-backend/.env"
SIDECAR_ENV="$APP_DIR/python_ai_sidecar/.env"
ONTOLOGY_ENV="$APP_DIR/ontology_simulator/.env"

for env_file in "$JAVA_ENV" "$SIDECAR_ENV" "$ONTOLOGY_ENV"; do
  if [ ! -f "$env_file" ]; then
    template="${env_file%/.env}/.env.example"
    if [ -f "$template" ]; then
      cp "$template" "$env_file"
      echo "    ✅  建立 $env_file（從 .env.example）"
    else
      echo "    ⚠️   缺少 $env_file 且無 .env.example — 請手動建立"
    fi
  fi
done

# ── 7. PostgreSQL DB / user ─────────────────────────────────────
echo ""
echo "🐘  設定 PostgreSQL..."
PG_USER="aiops"
PG_DB="aiops_db"
PG_PASS=$(grep -oP '(?<=DB_PASSWORD=)\S+' "$JAVA_ENV" 2>/dev/null || true)
if [ -z "$PG_PASS" ]; then
  PG_PASS=$(openssl rand -hex 16)
  if [ -f "$JAVA_ENV" ]; then
    if grep -q "^DB_PASSWORD=" "$JAVA_ENV"; then
      sed -i "s|^DB_PASSWORD=.*|DB_PASSWORD=$PG_PASS|" "$JAVA_ENV"
    else
      echo "DB_PASSWORD=$PG_PASS" >> "$JAVA_ENV"
    fi
    echo "    ✅  自動產生 PostgreSQL 密碼並寫入 java-backend/.env"
  else
    echo "    ⚠️   $JAVA_ENV 不存在，密碼僅暫存於本次 setup：$PG_PASS"
  fi
fi

sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename='$PG_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE USER $PG_USER WITH PASSWORD '$PG_PASS';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE $PG_DB OWNER $PG_USER;"
echo "    ✅  PostgreSQL DB: $PG_DB / user: $PG_USER"
echo "    ℹ️   Java 使用 Flyway 管 schema（application-prod.yml flyway.enabled=false 時要手動 psql -f V*.sql）"

# ── 8. systemd 服務 ─────────────────────────────────────────────
echo ""
echo "⚙️   安裝 systemd 服務..."
REAL_USER="${SUDO_USER:-ubuntu}"

# 4 個 active 服務 + ontology
for unit in aiops-app aiops-java-api aiops-python-sidecar ontology-simulator; do
  if [ -f "$APP_DIR/deploy/$unit.service" ]; then
    install -m 644 "$APP_DIR/deploy/$unit.service" /etc/systemd/system/
    sed -i "s/User=ubuntu/User=$REAL_USER/g; s/Group=ubuntu/Group=$REAL_USER/g" \
      "/etc/systemd/system/$unit.service"
  else
    echo "    ⚠️   missing $APP_DIR/deploy/$unit.service — 跳過"
  fi
done

chown -R "$REAL_USER:$REAL_USER" "$APP_DIR"
systemctl daemon-reload

# Java + sidecar 需要先 build/install — 不在這裡 enable，由首次跑 java-update.sh 接手
# Ontology simulator 可以直接啟
systemctl enable ontology-simulator
systemctl restart ontology-simulator
echo "    ✅  ontology-simulator 已啟動"
echo "    ℹ️   Java + sidecar + frontend 請執行 bash deploy/java-update.sh + bash deploy/update.sh"

# ── 9. Nginx 設定 ───────────────────────────────────────────────
echo ""
echo "🌐  設定 Nginx..."
sed "s/YOUR_DOMAIN/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" \
  > /etc/nginx/sites-available/aiops
ln -sf /etc/nginx/sites-available/aiops /etc/nginx/sites-enabled/aiops
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "$DOMAIN" > "$APP_DIR/.nginx_domain"
echo "    ✅  Nginx 設定完成（domain saved to .nginx_domain）"

# ── 10. SSL (Let's Encrypt) ─────────────────────────────────────
echo ""
echo "🔒  取得 SSL 憑證..."
mkdir -p /var/www/certbot
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --redirect
echo "    ✅  SSL 憑證安裝完成"

# ── 11. 防火牆 ──────────────────────────────────────────────────
echo ""
echo "🔥  設定 UFW 防火牆..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
echo "    ✅  UFW: SSH + HTTP + HTTPS 開放；8000/8002/8050/8012 不對外"

# ── 完成 ────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo "  🎉  系統依賴 + 基礎服務就緒！"
echo ""
echo "  🌐  前端          https://$DOMAIN"
echo "  📊  MES 模擬器    https://$DOMAIN/simulator/"
echo ""
echo "  📋  下一步："
echo "      cd $APP_DIR"
echo "      bash deploy/java-update.sh   # Java + Python sidecar"
echo "      bash deploy/update.sh        # aiops-app + ontology-simulator"
echo ""
echo "  🔍  狀態檢查："
echo "      systemctl status aiops-app aiops-java-api aiops-python-sidecar ontology-simulator"
echo ""
echo "  📝  Log："
echo "      journalctl -u aiops-java-api -f"
echo "      journalctl -u aiops-python-sidecar -f"
echo "════════════════════════════════════════════════"

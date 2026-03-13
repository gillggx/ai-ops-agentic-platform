#!/usr/bin/env bash
# deploy/setup.sh — Ubuntu 22.04 LTS 一鍵部署腳本
# 用法：sudo bash setup.sh YOUR_DOMAIN YOUR_EMAIL
# 例如：sudo bash setup.sh aiops.example.com admin@example.com
#
# 本腳本會：
#   1. 安裝系統依賴（Python 3.11, Node.js 20, MongoDB, PostgreSQL, Nginx, Certbot）
#   2. 建立 /opt/aiops 目錄結構
#   3. 設定 Python virtualenv + 安裝 pip 依賴
#   4. 建置 Next.js 靜態資產
#   5. 初始化 PostgreSQL DB + 執行 Alembic migration
#   6. 安裝 systemd 服務
#   7. 設定 Nginx + 取得 SSL 憑證

set -euo pipefail
DOMAIN="${1:?用法: bash setup.sh YOUR_DOMAIN YOUR_EMAIL}"
EMAIL="${2:?用法: bash setup.sh YOUR_DOMAIN YOUR_EMAIL}"
APP_DIR="/opt/aiops"
REPO_URL="https://github.com/gillggx/ai-ops-agentic-platform.git"

echo "════════════════════════════════════════════════"
echo "  AI-Ops Agentic Platform — Production Deploy"
echo "  Domain : $DOMAIN"
echo "  Email  : $EMAIL"
echo "════════════════════════════════════════════════"

# ── 0. 確認以 root 執行 ──────────────────────────────────────────
[[ $EUID -eq 0 ]] || { echo "❌  請以 root 或 sudo 執行"; exit 1; }

# ── 1. 系統套件 ──────────────────────────────────────────────────
echo ""
echo "📦  安裝系統套件..."
apt-get update -qq
apt-get install -y -qq \
  python3.11 python3.11-venv python3.11-dev python3-pip \
  build-essential libpq-dev \
  postgresql postgresql-contrib \
  nginx certbot python3-certbot-nginx \
  git curl gnupg lsof ufw

# Node.js 20
if ! command -v node &>/dev/null; then
  echo "📦  安裝 Node.js 20..."
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

# MongoDB 7
if ! command -v mongod &>/dev/null; then
  echo "📦  安裝 MongoDB 7..."
  curl -fsSL https://www.mongodb.org/static/pgp/server-7.0.asc | \
    gpg --dearmor -o /usr/share/keyrings/mongodb-server-7.0.gpg
  echo "deb [ arch=amd64,arm64 signed-by=/usr/share/keyrings/mongodb-server-7.0.gpg ] \
    https://repo.mongodb.org/apt/ubuntu jammy/mongodb-org/7.0 multiverse" \
    > /etc/apt/sources.list.d/mongodb-org-7.0.list
  apt-get update -qq
  apt-get install -y -qq mongodb-org
  systemctl enable mongod --now
fi

echo "✅  系統套件安裝完成"

# ── 2. 拉取程式碼 ────────────────────────────────────────────────
echo ""
echo "📥  拉取程式碼 → $APP_DIR ..."
if [ -d "$APP_DIR/.git" ]; then
  git -C "$APP_DIR" pull --ff-only
else
  git clone "$REPO_URL" "$APP_DIR"
fi

# ── 3. Python virtualenv — FastAPI Backend ───────────────────────
echo ""
echo "🐍  設定 FastAPI Backend virtualenv..."
python3.11 -m venv /opt/aiops/venv_backend
/opt/aiops/venv_backend/bin/pip install -q --upgrade pip
/opt/aiops/venv_backend/bin/pip install -q \
  -r "$APP_DIR/fastapi_backend_service/requirements.txt" \
  asyncpg  # PostgreSQL async driver

# ── 4. Python virtualenv — OntologySimulator ────────────────────
echo ""
echo "🐍  設定 OntologySimulator virtualenv..."
python3.11 -m venv /opt/aiops/venv_ontology
/opt/aiops/venv_ontology/bin/pip install -q --upgrade pip
/opt/aiops/venv_ontology/bin/pip install -q \
  -r "$APP_DIR/ontology_simulator/requirements.txt"

# ── 5. 建置 Next.js 靜態資產 ─────────────────────────────────────
echo ""
echo "🔨  建置 Next.js 靜態資產..."
cd "$APP_DIR/ontology_simulator/frontend"
npm ci --silent
npm run build
echo "✅  Next.js build 完成 → ontology_simulator/frontend/out/"

# ── 6. 設定環境變數檔案 ──────────────────────────────────────────
echo ""
echo "⚙️   檢查環境變數檔案..."
BACKEND_ENV="$APP_DIR/fastapi_backend_service/.env"
ONTOLOGY_ENV="$APP_DIR/ontology_simulator/.env"

if [ ! -f "$BACKEND_ENV" ]; then
  cp "$APP_DIR/deploy/.env.backend.template" "$BACKEND_ENV"
  echo "⚠️   請編輯 $BACKEND_ENV 填入真實值，然後重新執行本腳本的後半段（或 systemctl restart fastapi-backend）"
  echo "    nano $BACKEND_ENV"
  echo ""
  echo "    至少需要填寫："
  echo "      DATABASE_URL   — PostgreSQL 連線字串"
  echo "      SECRET_KEY     — 隨機 64 字元字串（openssl rand -hex 32）"
  echo "      ANTHROPIC_API_KEY"
  echo "      SERVER_BASE_URL=https://$DOMAIN"
  echo ""
fi

if [ ! -f "$ONTOLOGY_ENV" ]; then
  cp "$APP_DIR/deploy/.env.ontology.template" "$ONTOLOGY_ENV"
  echo "✅  建立 $ONTOLOGY_ENV（預設值可直接用）"
fi

# ── 7. 設定 PostgreSQL ───────────────────────────────────────────
echo ""
echo "🐘  設定 PostgreSQL..."
PG_USER="aiops"
PG_DB="aiops_db"
# 讀取現有密碼或產生新的
if grep -q "YOUR_PG_PASSWORD" "$BACKEND_ENV" 2>/dev/null; then
  PG_PASS=$(openssl rand -hex 16)
  sed -i "s/YOUR_PG_PASSWORD/$PG_PASS/g" "$BACKEND_ENV"
  sed -i "s/YOUR_DOMAIN/$DOMAIN/g" "$BACKEND_ENV"
  echo "    ✅  自動產生 PostgreSQL 密碼並寫入 .env"
else
  PG_PASS=$(grep DATABASE_URL "$BACKEND_ENV" | grep -oP '(?<=:)[^@]+(?=@)' || echo "")
fi

sudo -u postgres psql -tc "SELECT 1 FROM pg_user WHERE usename='$PG_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE USER $PG_USER WITH PASSWORD '$PG_PASS';"
sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$PG_DB'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE $PG_DB OWNER $PG_USER;"
echo "    ✅  PostgreSQL DB: $PG_DB / user: $PG_USER"

# ── 8. Alembic Migrations ────────────────────────────────────────
echo ""
echo "🗃️   執行 Alembic migrations..."
cd "$APP_DIR/fastapi_backend_service"
/opt/aiops/venv_backend/bin/alembic upgrade head && echo "✅  Migrations 完成"

# ── 9. systemd 服務 ──────────────────────────────────────────────
echo ""
echo "⚙️   安裝 systemd 服務..."
# 把 WorkingDirectory / ExecStart 裡的 /opt/aiops 指向實際目錄
install -m 644 "$APP_DIR/deploy/fastapi-backend.service"  /etc/systemd/system/
install -m 644 "$APP_DIR/deploy/ontology-simulator.service" /etc/systemd/system/

# 如果 ubuntu user 不存在，嘗試用當前 sudo 使用者
REAL_USER="${SUDO_USER:-ubuntu}"
sed -i "s/User=ubuntu/User=$REAL_USER/g" /etc/systemd/system/fastapi-backend.service
sed -i "s/Group=ubuntu/Group=$REAL_USER/g" /etc/systemd/system/fastapi-backend.service
sed -i "s/User=ubuntu/User=$REAL_USER/g" /etc/systemd/system/ontology-simulator.service
sed -i "s/Group=ubuntu/Group=$REAL_USER/g" /etc/systemd/system/ontology-simulator.service
# 確保 ReadWritePaths 包含正確目錄
chown -R "$REAL_USER:$REAL_USER" "$APP_DIR"

systemctl daemon-reload
systemctl enable fastapi-backend ontology-simulator
systemctl restart fastapi-backend ontology-simulator
echo "    ✅  fastapi-backend.service + ontology-simulator.service 已啟動"

# ── 10. Nginx 設定 ───────────────────────────────────────────────
echo ""
echo "🌐  設定 Nginx..."
sed "s/YOUR_DOMAIN/$DOMAIN/g" "$APP_DIR/deploy/nginx.conf" \
  > /etc/nginx/sites-available/aiops
ln -sf /etc/nginx/sites-available/aiops /etc/nginx/sites-enabled/aiops
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx
echo "    ✅  Nginx 設定完成"

# ── 11. SSL (Let's Encrypt) ──────────────────────────────────────
echo ""
echo "🔒  取得 SSL 憑證..."
mkdir -p /var/www/certbot
certbot --nginx -d "$DOMAIN" --email "$EMAIL" --agree-tos --non-interactive --redirect
echo "    ✅  SSL 憑證安裝完成"

# ── 12. 防火牆 ───────────────────────────────────────────────────
echo ""
echo "🔥  設定 UFW 防火牆..."
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
echo "    ✅  UFW: SSH + HTTP + HTTPS 開放，8000/8001 對外封閉"

# ── 完成 ────────────────────────────────────────────────────────
echo ""
echo "════════════════════════════════════════════════"
echo "  🎉  部署完成！"
echo ""
echo "  🌐  前端          https://$DOMAIN"
echo "  📊  MES 模擬器    https://$DOMAIN/simulator/"
echo "  📡  API Docs      https://$DOMAIN/docs"
echo ""
echo "  📋  服務狀態："
echo "      systemctl status fastapi-backend"
echo "      systemctl status ontology-simulator"
echo ""
echo "  📝  Log："
echo "      journalctl -u fastapi-backend -f"
echo "      journalctl -u ontology-simulator -f"
echo ""
echo "  🔄  更新部署："
echo "      cd $APP_DIR && git pull && bash deploy/update.sh"
echo "════════════════════════════════════════════════"

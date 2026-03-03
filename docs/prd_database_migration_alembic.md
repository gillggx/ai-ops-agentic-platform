# Database Migration Architecture (資料庫遷移架構導入)

## 1. 核心哲學 (Architecture Philosophy)
* **Code vs. Data Separation**：絕對禁止將實體資料庫檔案 (`*.db`, `*.sqlite`) 加入版本控制。
* **Automated Schema Evolution**：透過 Alembic 建立資料庫版控機制，確保 Local、Staging 與 Production 環境的資料庫結構 (Schema) 能透過自動化腳本無損升級。

## 2. 工具與套件 (Tech Stack)
* **ORM**: SQLAlchemy (維持現有)
* **Migration Tool**: Alembic

## 3. CI/CD 佈署流程變更 (Pipeline Update)
必須修改 GitHub Actions 的 `.github/workflows/deploy.yml`。
在執行 `git pull` 之後、`systemctl restart uvicorn` 之前，必須插入執行 `alembic upgrade head` 的指令，讓資料庫結構在系統重啟前自動升級到最新版。
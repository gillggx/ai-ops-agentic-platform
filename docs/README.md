# Glass Box AI Ops Platform — Docs

## 現行有效文件（Active）

| 文件 | 說明 | 狀態 |
|------|------|------|
| [master_prd_v12_ui.md](master_prd_v12_ui.md) | **最高指導規格書** — v12 UI/UX 全面解耦、巢狀架構、MCP 執行規範 | ✅ 現行版本 |
| [master_prd_template.md](master_prd_template.md) | PRD 撰寫模板，供新版本參考使用 | ✅ 維護中 |
| [coding_guidelines_and_sop.md](coding_guidelines_and_sop.md) | 程式碼撰寫規範與 SOP | ✅ 維護中 |
| [system_spec_latest.md](system_spec_latest.md) | 系統技術規格（從程式碼反推，含所有 endpoints、DB schema、設定） | ✅ 維護中 |
| [user_manual.md](user_manual.md) | 使用者操作手冊（v1.1.0，繁體中文） | ✅ 維護中 |

---

## 關鍵規範快速參照

### MCP 執行規範（每次工作前必讀）
> **位置：** `master_prd_v12_ui.md` § 5

**黃金法則：只有「MCP Builder 建立全新」才呼叫 LLM (try-run)，其餘一律 run-with-data（直接跑 Python）。**

```
建立全新 MCP   → POST /mcp-definitions/try-run          (LLM 生成腳本)
所有其他場景   → POST /mcp-definitions/{id}/run-with-data (直接跑 Python)
```

### Skill 執行流程（5 步驟，Python 優先）
```
1. DS data fetch         → 失敗 → LLM explain_failure()
2. MCP execute_script()  → 失敗 → LLM explain_failure()
3. Validate dataset ≠ ∅  → 空值 → LLM explain_failure()
4. Skill execute_diagnose_fn() (強制 Python，無 LLM fallback)
5. LLM summarize_diagnosis() → 潤飾輸出
```

---

## 歸檔（history_archive/）

| 類別 | 內容 |
|------|------|
| 舊版 PRD（Phase 1–11） | `prd_phase3_*`, `prd_phase4_*`, ..., `prd_database_migration_alembic.md` 等 |
| 舊版產品規格 | `prod_spec_3.5.md`, `prod_spec_v5.md`, `prod_spec_v7.md`, `master_prd_v11.md` |
| 舊版產品規格資料夾 | `Product_spec_V8/`, `Product_spec_V10/`（含 PRODUCT_SPEC.md、introduction、user-manual） |
| HTML/PDF 舊版文件 | `introduction_v5.html` 〜 `introduction_v8.pdf`, `user_manual_v5.html` 〜 `user_manual_v8.pdf` |
| 開發工具目錄 | `class_view/`, `code_plan_and_change/`, `code_summary/`, `graph_repo/`, `screenshots/` 等 |

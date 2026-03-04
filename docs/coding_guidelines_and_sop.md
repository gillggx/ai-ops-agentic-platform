# 系統開發紀律與架構維護規範 (Coding Guidelines & SOP)

## 1. 程式碼風格與品質控管 (Coding Style)
- **Python (FastAPI 後端)**：
  - 嚴格遵守 PEP 8 規範。
  - 所有 Function 與 Class 必須補上清晰的 Docstring (說明用途、參數與回傳型態)。
  - 強制使用 Type Hinting (型別提示)，確保 Pydantic 模型驗證精準。
- **React (前端)**：
  - 變數與函式命名必須具備語意 (Semantic Naming)，禁止使用 `temp`, `data1` 等模糊名稱。
  - 元件(Components) 必須模組化，避免單一檔案超過 300 行。

## 2. 動態文件維護機制 (Living Documentation)
- **核心原則**：**「以 Code 為尊」**。文件不可憑空想像，必須透過讀取最新的程式碼來反向更新規格。
- **維護目標**：在 `docs/` 目錄下建立並維護一份 `system_spec_latest.md`。
- **更新時機**：每次完成新功能 (Feature) 或架構重構後，必須自動比對程式碼，並在文件頂部標註版本號 (如 `v11.x`) 與變更日誌 (Changelog)。

## 3. 系統設定與偏好抽離 (Configuration Management)
- **絕對禁止 Hard-code (寫死)**：程式碼中不得出現寫死的 IP 位址、Port 號、API 金鑰、檔案路徑或排程預設時間。
- **層級化設定存放策略**：
  1. **系統級設定 (System Configuration)**：
     - 包含：資料庫連線字串、外部 API 密鑰、環境變數。
     - 存放位置：必須抽離至 `.env` 檔案，並在程式碼中使用 `pydantic-settings` 或 `os.environ` 讀取。
  2. **使用者/業務偏好設定 (User Preferences / Business Rules)**：
     - 包含：Routine Check 的預設間隔時間、Event 的觸發閥值 (Threshold)、前端顯示語系。
     - 存放位置：必須存入資料庫的 `UserPreference` 或 `SystemConfig` 資料表，並提供 API 供前端讀取。
- **未知處理**：當遇到不確定該歸類為「系統設定」還是「使用者偏好」的參數時，暫停執行並主動向總舵手確認。
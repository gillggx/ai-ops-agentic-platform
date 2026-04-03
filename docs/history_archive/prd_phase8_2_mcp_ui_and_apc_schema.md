# Phase 8.2 急件補丁：MCP 介面體驗優化與 APC 資料結構升級

## 1. MCP Builder UI 體驗優化 (解決空白畫布)
在前端 `/skills` (或 MCP 建立介面) 的「新增 MCP」抽屜中，必須解決使用者不知道有哪些欄位可用的問題。

**UI 規則修改：**
- 當使用者在下拉選單選定 `DATA SUBJECT` 後，必須立刻在其下方、**「加工意圖」輸入框的上方**，動態展開一個唯讀的「資料欄位參考區 (Data Schema Reference)」。
- 該區塊需優雅地條列出該 Data Subject 的 `output_schema` 中的所有欄位名稱 (Name)、資料型態 (Type) 以及最關鍵的**欄位說明 (Description)**。
- 建議使用 Tailwind 的 `bg-slate-800 p-4 rounded-md text-sm text-slate-300` 等樣式，讓它看起來像是一個清晰的參考字典。

---

## 2. APC Data Subject 與 Mock API 結構重構 (Domain Accuracy)
老闆指出目前的 APC 資料結構不符合半導體真實場景。請重構 `routers/mock_data_router.py` 中的 `/apc` 端點，以及資料庫中預設的 `DS_APC` Data Subject 定義。

**全新的 APC Output Schema 必須包含：**
- `apc_name` (String): 控制器的名稱 (e.g., "Etch_Poly_APC")
- `apc_model_name` (String): 使用的模型版本名稱 (e.g., "EWMA_CD_Controller_v2.1")
- `model_update_time` (DateTime): 模型最後發布/更新的時間
- `parameters` (Array of Objects): 該次補償具體下達的參數陣列。每個物件必須包含：
  - `name` (String): 參數名稱 (e.g., "Gas_Flow_Offset", "RF_Power_Delta")
  - `value` (Number): 參數數值
  - `update_time` (DateTime): 該參數本次被計算/更新的時間

**Mock API 回傳範例 (需實作於 `/api/v1/mock/apc`)：**
```json
{
  "lot_id": "L12345.00",
  "operation_number": "3200",
  "apc_name": "TETCH01_CD_Control",
  "apc_model_name": "Etch_CD_EWMA_v2.1",
  "model_update_time": "2026-02-15T08:00:00Z",
  "parameters": [
    {
      "name": "CHF3_Gas_Offset",
      "value": 2.5,
      "update_time": "2026-02-28T10:15:30Z"
    },
    {
      "name": "RF_Power_Delta",
      "value": -10,
      "update_time": "2026-02-28T10:15:30Z"
    }
  ]
}
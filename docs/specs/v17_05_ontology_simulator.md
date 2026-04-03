# Spec: ontology-simulator

> 開發用工具 — Mirror ontology 服務介面，提供模擬資料

---

## Context & Objective

`ontology-simulator` 是純開發工具，mirror `ontology` 的 API 介面，讓開發者在沒有生產資料的情況下開發和測試 aiops-app 與 aiops-agent。

**核心原則：**
- 僅供開發環境使用，不進入 production
- 嚴格 mirror ontology 的 API 介面，介面一致是最高優先級
- 提供可配置的模擬場景（正常、OOC、設備異常等）

---

## Tech Stack

- **Framework:** Python (FastAPI)
- **模擬資料:** 靜態 JSON fixtures + 動態場景生成
- **Port:** 8099（開發環境）

---

## Project Structure

```
ontology-simulator/
├── app/
│   ├── api/
│   │   └── v1/                  ← 完全 mirror ontology 的 API 路徑
│   │       ├── equipment.py
│   │       ├── dc_data.py
│   │       ├── events.py
│   │       ├── lots.py
│   │       └── spc.py
│   ├── scenarios/               ← 模擬場景定義
│   │   ├── normal.json
│   │   ├── ooc_temperature.json
│   │   └── equipment_down.json
│   ├── data_generator.py        ← 動態時序資料生成
│   └── main.py
├── frontend/                    ← 場景控制 UI（Next.js，現有）
└── pyproject.toml
```

---

## 與 ontology 的介面同步規則

1. `ontology` 的 API 介面是 source of truth
2. `ontology-simulator` 必須實作相同的 path、query params、response schema
3. aiops-app 只需切換 `ONTOLOGY_BASE_URL` 環境變數即可在真實/模擬間切換：

```bash
# 開發環境
ONTOLOGY_BASE_URL=http://localhost:8099

# 生產環境
ONTOLOGY_BASE_URL=http://ontology-service
```

---

## 模擬場景

| 場景 | 說明 | 觸發用途 |
|---|---|---|
| `normal` | 所有機台正常運作 | 基本功能測試 |
| `ooc_temperature` | EQP-01 溫度 OOC | RCA 流程測試 |
| `equipment_down` | EQP-03 停機 | 告警流程測試 |
| `lot_yield_drop` | 某批次良率下降 | Lot 追蹤測試 |

場景可透過 simulator 的 frontend UI 切換，也可透過 API 設定：
```
POST /api/v1/simulator/scenario { "name": "ooc_temperature" }
```

---

## 現有 Frontend

`frontend/` 目錄已有 Next.js 場景控制 UI（現有功能保留），將遷移至此 project。

---

## Edge Cases & Risks

| 風險 | 處理方式 |
|---|---|
| ontology 介面更新但 simulator 未同步 | 在 ontology spec 文件加入 "simulator 必須同步" 提醒 |
| 模擬資料被 production 程式碼引用 | 嚴格的環境變數隔離，production 不設定 simulator URL |

---

*最後更新：2026-03-21*

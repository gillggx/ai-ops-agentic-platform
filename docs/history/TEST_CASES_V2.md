# Test Cases V2 — 預期行為對齊

**Date:** 2026-04-15
**Purpose:** 對齊每個 test case 的預期行為，確保 response + console + UI 都正確

---

## 預期行為定義

| 符號 | 意義 |
|------|------|
| 📊 Explorer | 中央 DataExplorer（互動圖表） |
| 💬 Text | Copilot 文字回答 |
| ❓ Ask | 正確反問（缺關鍵資訊） |
| 🚫 Cannot | 超出系統能力，應誠實說「目前無法」 |

---

## 20 Test Cases

### TC01: EQP-01 的 APC etch_time_offset 趨勢
**預期：** 📊 Explorer
- pipeline: Retrieval(get_process_info, equipment_id=EQP-01) → Flatten → Present(apc_data, filter: etch_time_offset)
- Explorer 開在中央，APC tab，filter=etch_time_offset
- 看得到 trend chart，資料 ~200 筆
- Console: S3✅ S4✅ S5⏭ S6✅

### TC02: STEP_001 的 xbar_chart trend chart
**預期：** 📊 Explorer
- pipeline: Retrieval(get_process_info, step=STEP_001) → Flatten → Present(spc_data, filter: xbar_chart)
- Explorer 開在中央，SPC tab，filter=xbar_chart
- 看得到 trend chart，資料 ~200 筆
- Console: S3✅ S4✅ S5⏭ S6✅

### TC03: EQP-05 列出OOC站點和SPC charts
**預期：** 📊 Explorer + 💬 Text
- pipeline: Retrieval(get_process_info, equipment_id=EQP-05, limit=200) → Flatten → Present(spc_data)
- 文字列出 OOC 站點清單（by_step breakdown）
- Explorer 開在中央，SPC tab
- Console: S3✅ S4✅ S5⏭ S6✅

### TC04: 比較EQP-01和EQP-02的SPC xbar趨勢
**預期：** 📊 Explorer (overlay tab)
- pipeline: Retrieval(get_process_info, 不帶 equipment_id 或分兩次) → Flatten → Present(overlay or spc_data)
- Explorer 用 Overlay tab 或 filter 切換機台看 xbar
- Console: S3✅ S4✅ S5⏭ S6✅

### TC05: 我想看EQP-02今天的製程資訊
**預期：** 📊 Explorer（不只是文字）
- pipeline: Retrieval(get_process_info, equipment_id=EQP-02, since=24h) → Flatten → Present(spc_data 或任一 tab)
- Explorer 開在中央，使用者可以自由切換 SPC/APC/DC/... 看各種資料
- Console: S3✅ S4✅ S5⏭ S6✅

### TC06: 目前有哪些機台
**預期：** 💬 Text
- pipeline: Retrieval(list_tools) → 文字列出 10 台機台 + 狀態
- 不開 Explorer
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC07: 全廠OOC率是多少
**改：** 10個機台今天有多少OOC
**預期：** 💬 Text
- pipeline: Retrieval(get_process_summary) → 文字回答 OOC rate + by_tool breakdown
- 不開 Explorer
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC08: EQP-01 最近有沒有OOC
**預期：** 💬 Text
- pipeline: Retrieval(get_process_info, equipment_id=EQP-01, since=24h) → Flatten
- 文字回答：有 X 次 OOC（24h）
- 列出 OOC process 基本資訊（eventTime, lotID, step, spc_status）
- 不開 Explorer（除非使用者要看圖）
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC09: 今天有什麼異常嗎
**備註：** 目前沒有 alarm MCP
**預期：** 💬 Text
- pipeline: Retrieval(get_process_summary) → 文字回答全廠 OOC 狀況
- 如果系統沒有 alarm API，就用 OOC 統計代替，不要幻覺
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC10: EQP-03 剛OOC了幫我看一下
**預期：** 📊 Explorer + 💬 Text
- pipeline: Retrieval(get_process_info, equipment_id=EQP-03, limit=50) → Flatten → Present(spc_data)
- 文字列出最近的 OOC process 資訊
- Explorer 可看 SPC/APC/DC 等
- ⚠️ 不該用 5 個 SPC chart skill — 應該用 plan_pipeline
- Console: S3✅ S4✅ S5⏭ S6✅

### TC11: 為什麼這台一直OOC
**預期：** ❓ Ask
- 缺機台 ID → 正確反問「哪台機台？」
- 如果有歷史 context（上一輪提過某機台）→ 用那台
- Console: 不呼叫工具

### TC12: 為什麼EQP-01的OOC比EQP-02高這麼多
**預期：** 💬 Text（誠實回答）
- pipeline: Retrieval(get_process_summary) → 比較兩台的 OOC count
- 只能統計比較，不能回答「為什麼」→ 誠實說「根據統計，EQP-01 OOC X 筆 vs EQP-02 Y 筆，但無法判斷根因」
- 🚫 不要幻覺根因分析
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC13: 哪台機台最需要關注
**預期：** 💬 Text
- pipeline: Retrieval(get_process_summary) → 按 OOC count 排名
- 文字回答「EQP-XX OOC 最多（Y 次），建議優先關注」
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC14: 今天有沒有需要停機檢查的
**預期：** 🚫 Cannot + 💬 Text
- 沒有 PM schedule MCP → 誠實說「目前系統無法查詢停機排程」
- 但可以補充：「根據 OOC 統計，EQP-XX 異常最多，建議排查」
- Console: S3✅ S4✅ S5⏭ S6⏭

### TC15: STEP_001 7天 SPC all charts
**預期：** 📊 Explorer
- pipeline: Retrieval(get_process_info, step=STEP_001, since=7d) → Flatten → Present(spc_data)
- Explorer SPC tab，filter 可切 5 種 chart
- 資料是 STEP_001 的 7 天資料
- Console: S3✅ S4✅ S5⏭ S6✅

### TC16: EQP-07 xbar + APC rf_power_bias 同張圖
**預期：** 📊 Explorer (overlay)
- pipeline: Retrieval(get_process_info, equipment_id=EQP-07) → Flatten → Present(overlay, left=spc xbar, right=apc rf_power_bias)
- Explorer Overlay tab，雙 Y 軸
- Console: S3✅ S4✅ S5⏭ S6✅

### TC17: STEP_001 多 APC params trend
**預期：** 📊 Explorer
- pipeline: Retrieval(get_process_info, step=STEP_001) → Flatten → Present(apc_data)
- Explorer APC tab，可用 filter 切換 rf_power_bias / gas_flow_comp / uniformity_pct
- ~200 筆資料
- Console: S3✅ S4✅ S5⏭ S6✅

### TC18: STEP_007 所有 SPC charts + 5點2OOC check
**預期：** 📊 Explorer + 💬 Text（統計結果）
- pipeline: Retrieval(get_process_info, step=STEP_007, limit=5) → Flatten → Compute(5pt OOC check) → Present(spc_data)
- 文字列出每個 chart_type 的 5pt OOC check 結果
- Explorer SPC tab
- Console: S3✅ S4✅ S5✅ S6✅

### TC19: STEP_007 SPC vs APC rf_power_bias 線性回歸 R²
**預期：** 💬 Text（R² table）+ 📊 Explorer（可選 scatter）
- pipeline: Retrieval(get_process_info, step=STEP_007) → Flatten → Transform(join spc+apc by eventTime) → Compute(regression per chart_type) → Present(scatter or processed_data)
- **及格：** 文字列出 5 個 chart_type 的 R² 值
- **滿分：** 加上 scatter chart
- Console: S3✅ S4✅ S5✅ S6✅

### TC20: STEP_001 xbar 常態分佈 + 1~4σ 標記
**預期：** 💬 Text（統計結果）+ 📊 Explorer
- pipeline: Retrieval(get_process_info, step=STEP_001) → Flatten → Compute(normal dist stats) → Present
- 文字列出 μ、σ、各 σ 區間的點數/百分比
- Console: S3✅ S4✅ S5✅ S6✅

---

## Quick Actions（對話輸入框上方 3 個按鈕）

替換現有的 3 個按鈕為：

| 按鈕 | 對應 TC |
|------|--------|
| EQP-01 的 APC etch_time_offset 趨勢 | TC01 |
| STEP_001 的 xbar_chart trend chart | TC02 |
| EQP-05 列出OOC站點和SPC charts | TC03 |

---

## 驗證方式

每個 case 驗證：
1. **Console stages** — 是否顯示 9 stages dots（1~9），pipeline stages 是否正確
2. **Response message** — 文字是否包含預期的統計/資訊
3. **UI** — DataExplorer 是否正確開啟（或不開啟），初始 tab/filter 是否正確
4. **幻覺** — 是否說了「已渲染」「無法判斷但還是判斷了」
5. **反問** — 該反問的反問，不該反問的不反問

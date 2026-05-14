# Spec: Skill Description 自動生成

**Version:** 1.0
**Date:** 2026-04-13
**Author:** Gill + Claude
**Status:** Draft — 待確認後開始開發

---

## 1. Context & Objective

### 問題

目前 Skill 的 `description` 欄位由人工填寫（Auto-Patrol、Diagnostic Rule、My Skill 建立時）。實際觀察到的問題：

| 問題 | 影響 | 案例 |
|------|------|------|
| **Description 太模糊** | Agent 無法區分相似 Skill，呼叫錯誤 | skill#39 (APC trend) vs skill#41 (Recipe trend) 都叫 `Chart capability test:...` → Agent 選錯 |
| **人寫的不一致** | 有的寫中文、有的寫英文、有的只寫標題不寫用途 | 6 個 Chart-Test skills 的 description 完全沒區分度 |
| **缺少關鍵區分資訊** | 相似名稱的 Skill 無法靠 description 區分 | `etch_time_offset`（APC 參數）vs `etch_time_s`（Recipe 參數）— description 沒標明差異 |

### 目標

在 Auto-Patrol / Diagnostic Rule / My Skill 的 **code 生成階段（Phase 2b）完成後**，自動從 `steps_mapping` + `output_schema` + `input_schema` 產生一份結構化的 `description`，取代人工填寫。

---

## 2. Architecture & Design

### 2.1 觸發時機

```
使用者填寫 name + description（自然語言）
  → Phase 0: Clarification check
  → Phase 1: Step plan
  → Phase 2a: NL segments
  → Phase 2b: Python code generation
  → 【NEW】Phase 3: Description auto-generation ← 這裡
  → 儲存到 DB
```

**Phase 3** 在所有 code 生成完成後、儲存前執行。此時系統已經有完整的：
- `steps_mapping`（每個 step 的 `nl_segment` + `python_code`）
- `output_schema`（輸出欄位定義：type, label, key）
- `input_schema`（輸入參數定義）
- 使用者原始的 `name` + `description`

### 2.2 Description 結構

自動生成的 description 應包含以下區塊：

```
== 用途 ==
一句話說明這個 Skill 做什麼。

== 使用場景 ==
什麼時候應該用這個 Skill（而不是其他類似的）。

== 輸入 ==
- equipment_id (string, required): 目標機台 ID

== 輸出 ==
- etch_trend (line_chart): APC etch_time_offset 時間趨勢
- sample_count (scalar): 樣本數

== 區分 ==
⚠️ 這是 APC 參數趨勢（etch_time_offset），不是 Recipe 參數（etch_time_s）。
若要查 Recipe 參數趨勢，請用 skill#41。

== 資料來源 ==
呼叫 get_process_info (limit=50)，從 events[].APC.parameters 提取。
```

### 2.3 生成方式

**Option A：LLM 生成（推薦）**

在 Phase 2b 完成後，用一次額外的 LLM call：

```python
prompt = f"""
你是 Skill Description 生成器。根據以下 Skill 的完整資訊，生成一份結構化的 description。

Name: {name}
User description: {user_description}
Input schema: {json.dumps(input_schema)}
Output schema: {json.dumps(output_schema)}
Steps: {steps_summary}  # 每個 step 的 nl_segment

生成格式：
== 用途 ==
...
== 使用場景 ==
...
== 輸入 ==
...
== 輸出 ==
...
== 區分 ==
（如果 output_schema 的欄位名容易與其他常見參數混淆，標明區分）
== 資料來源 ==
（從 steps 的 execute_mcp 呼叫中提取）
"""
```

**Option B：Rule-based 模板（備選）**

不用 LLM，直接從 `input_schema` + `output_schema` + `steps_mapping` 拼裝：

```python
def auto_generate_description(name, input_schema, output_schema, steps_mapping):
    parts = [f"== 用途 ==\n{name}\n"]
    
    # Input
    if input_schema:
        parts.append("== 輸入 ==")
        for f in input_schema:
            parts.append(f"- {f['key']} ({f['type']}): {f.get('description','')}")
    
    # Output
    if output_schema:
        parts.append("== 輸出 ==")
        for f in output_schema:
            parts.append(f"- {f['key']} ({f['type']}): {f.get('label','')}")
    
    # Data source (extract MCP calls from code)
    mcp_calls = extract_mcp_calls(steps_mapping)
    if mcp_calls:
        parts.append(f"== 資料來源 ==\n呼叫 {', '.join(mcp_calls)}")
    
    return "\n".join(parts)
```

**推薦 Option A** — LLM 能產生更精準的「使用場景」和「區分」描述，Rule-based 做不到。

### 2.4 適用範圍

| 來源 | 觸發時機 | 行為 |
|------|---------|------|
| **Auto-Patrol** (`/admin/auto-patrols`) | generate-steps 完成後 | 自動覆蓋 description |
| **Diagnostic Rule** (`/admin/skills`) | generate-steps 完成後 | 自動覆蓋 description |
| **My Skill** (`/admin/my-skills`) | generate-steps 完成後 | 自動覆蓋 description |
| **Agent promote** (execute_analysis → 儲存為 Skill) | promote 時 | 自動生成 description |
| **手動建立 Skill** (admin 直接編輯) | 不觸發 | 保留人工 description |

### 2.5 前端變化

- Description 欄位改為 **唯讀顯示**（code 生成後自動填入）
- 使用者填寫的原始 description 保留在 `user_description` 欄位（作為 LLM 生成的 input）
- 可以手動編輯覆蓋（但建議用「重新生成」按鈕而非手改）

---

## 3. Step-by-Step Execution Plan

1. **Backend `DiagnosticRuleService`**：在 `generate_steps_stream()` 的 Phase 2b 完成後，加入 Phase 3 LLM call 生成 description
2. **DB schema**：`skill_definitions` 新增 `user_description` 欄位（保留使用者原始輸入）
3. **API**：generate-steps response 新增 `auto_description` 欄位
4. **Frontend**：3 個 admin 頁面在 generate 完成後，自動填入 `auto_description` 到 description 欄位
5. **Promote flow**：`analysis.py` promote endpoint 也呼叫 Phase 3 生成 description

---

## 4. Edge Cases & Risks

| 風險 | 對策 |
|------|------|
| LLM 生成的 description 不準確 | 使用者可以手動編輯覆蓋 |
| 額外的 LLM call 增加延遲 | Phase 3 用小 model（haiku）或 short prompt，預估 < 2 秒 |
| 舊 Skill 沒有 auto description | 提供 batch migration script，一次性重新生成所有 Skill 的 description |
| 「區分」資訊需要看其他 Skill | Phase 3 prompt 可帶入同 category 的其他 Skill name + description 供比較 |

---

## 5. Verification Plan

測試案例：

| # | 場景 | 預期結果 |
|---|------|---------|
| 1 | 建立 APC etch_time_offset trend skill | description 包含「APC 參數」「不是 Recipe」 |
| 2 | 建立 SPC OOC check Auto-Patrol | description 包含觸發條件、使用的 MCP、判斷邏輯 |
| 3 | Agent promote ad-hoc 分析為 Skill | auto_description 自動填入 |
| 4 | 兩個相似 Skill（APC vs Recipe）同時存在 | description 的「區分」段落明確標出差異 |
| 5 | LLM 選 Skill 時 | 用更新後的 description，Agent 不再選錯 |

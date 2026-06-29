# AIOps Skill API — by-method reference（標準版）

> 給「沒有 connector」的情境用。claude.ai 網頁版 Claude **不能自己發 HTTP**，所以它的
> 工作是：照下面規格**幫使用者產出 curl / 程式碼**，使用者自己去跑。
> 每個 method 都有：endpoint / HTTP method / headers / request / response / curl 範例。

---

## 0. 共通設定

- **Base URL**：`https://aiops-gill.com`
- **認證**：所有 `/api/v2/skills/*` 都要
  `Authorization: Bearer <AIOPS_TOKEN>`。
  - `<AIOPS_TOKEN>` 是**佔位符** —— 不要寫死任何實際值。
  - 取得方式：登入 web app 後，由管理員核發一把 service token（或從已登入
    session 取 JWT）。**絕不要把實際 token 貼進對話或文件。**
  - 產 curl 時用環境變數：`-H "Authorization: Bearer $AIOPS_TOKEN"`。
- **Content-Type**：所有 POST/PUT 都送 `Content-Type: application/json`。
- **回傳信封**：成功 `{"ok":true,"data":<payload>,"error":null,"timestamp":"..."}`；
  失敗 `{"ok":false,"data":null,"error":{"code":"...","message":"..."}}`。
- **wire 格式**：JSON 欄位一律 **snake_case**（`pipeline_id` 不是 `pipelineId`）。
- ⚠️ **build 類工具（list_blocks / preview / execute）不在這份** —— 它們走平台
  **內部** endpoint（service-to-service，外部 curl 打不到）。要建 pipeline 請用
  connector（模式 A）或網頁 `https://aiops-gill.com/skills/new` 讓平台 agent 建。

---

## SkillDto（多數 method 回傳的 skill 物件）
```
id             number   skill 數字 id（URL 用 /skills/<id>）
slug           string   內部 key（auto-gen，使用者不需看）
name           string   顯示名稱
sub            string   一句副標
nl             string   自然語言描述
pipeline_id    number?  綁的 pipeline id（null = 未綁）
pipeline_nodes string   壓縮版 node 列表 JSON（Editor 顯示用）
has_alarm      bool     pipeline 是否含 block_step_check（→ 可當 patrol）
in_type        string   輸入型別描述
out_type       string   輸出型別描述
role           string   "tool" | "patrol" | "datacheck"
trigger_config string?  自動化設定 JSON（null = 無自動化）
alarm_gate     string?  patrol gate
outcome        string?  patrol outcome
status         string   "draft" | "active"
test_cases     string   JSON
```

---

## 1. list_skills_v2 — 列出所有 Skill
- **GET** `/api/v2/skills`
- Headers: `Authorization: Bearer $AIOPS_TOKEN`
- Request body: 無
- Response: `data` = `SkillDto[]`
```bash
curl -s -H "Authorization: Bearer $AIOPS_TOKEN" \
  https://aiops-gill.com/api/v2/skills
```

## 2. get_skill_v2 — 取單一 Skill
- **GET** `/api/v2/skills/{idOrSlug}`
- Response: `data` = `SkillDto`
```bash
curl -s -H "Authorization: Bearer $AIOPS_TOKEN" \
  https://aiops-gill.com/api/v2/skills/11
```

## 3. get_skill_with_pipeline — Skill + 綁定的 pipeline_json
- **GET** `/api/v2/skills/{idOrSlug}/full`
- Response: `data` = `{ "skill": SkillDto, "pipeline_json": "<JSON string 或 null>" }`
```bash
curl -s -H "Authorization: Bearer $AIOPS_TOKEN" \
  https://aiops-gill.com/api/v2/skills/11/full
```

## 4. create_skill_v2 — 建空 Skill（純 tool，無 pipeline）
- **POST** `/api/v2/skills`
- Body: `{ "slug": "<auto>", "name": "...", "sub": "...", "nl": "..." }`
  （slug 自己產：name 小寫、非 ASCII 去掉、空白換 `-`、加 4 碼亂數尾）
- Response: `data` = `SkillDto`（status=draft, role=tool）
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"slug":"eqp01-spc-trend-ab12","name":"EQP-01 SPC 趨勢","sub":"","nl":"查 EQP-01 最近 7 天 SPC xbar 趨勢"}'
```

## 5. create_skill_with_pipeline — 建 pipeline + skill + 綁（一次原子完成）
- **POST** `/api/v2/skills/with-pipeline`
- Body: `{ "slug","name","sub","nl","pipeline_json": <object>, "pipeline_kind":"skill" }`
- Response: `data` = `{ "skill": SkillDto, "pipeline_json": "..." }`（status=draft）
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills/with-pipeline \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"slug":"eqp01-5in2-ab12","name":"5取2 OOC","sub":"","nl":"近5次process≥2次OOC告警",
       "pipeline_json":{"version":"1.0","name":"5in2","inputs":[],"nodes":[...],"edges":[...]}}'
```

## 6. update_skill_v2 — 改文字欄位（不動 pipeline）
- **PUT** `/api/v2/skills/{idOrSlug}`
- Body（只傳要改的）: `{ "nl"?, "name"?, "sub"?, "in_type"?, "out_type"? }`
- Response: `data` = 更新後 `SkillDto`
```bash
curl -s -X PUT https://aiops-gill.com/api/v2/skills/11 \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"nl":"改成查 chamber pressure 異常"}'
```

## 7. bind_skill_pipeline — 把既有 pipeline 綁到 Skill
- **POST** `/api/v2/skills/{idOrSlug}/bind-pipeline`
- Body: `{ "pipeline_id": <number> }`
- Response: `data` = `SkillDto`（server 重新推導 pipeline_nodes / has_alarm / in_type / out_type）
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills/11/bind-pipeline \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"pipeline_id":176}'
```

## 8. check_skill_ready_for_role — 升級角色前的預檢
- **GET** `/api/v2/skills/{idOrSlug}/role-readiness?role=<patrol|datacheck|tool>`
- Response: `data` = `{ "ok": bool, "reason": "<失敗原因或 null>" }`
- 用途：automate_* 前必呼。patrol 沒 block_step_check verdict 會 ok=false。
```bash
curl -s -H "Authorization: Bearer $AIOPS_TOKEN" \
  "https://aiops-gill.com/api/v2/skills/11/role-readiness?role=patrol"
```

## 9. list_event_sources — 可訂閱的上游 patrol（給 event 自動化用）
- **GET** `/api/v2/skills/alarm-sources?excludeSlug=<可選>`
- Response: `data` = `[{ "slug","name","sub" }]`（role=patrol 且 has_alarm 的）
```bash
curl -s -H "Authorization: Bearer $AIOPS_TOKEN" \
  https://aiops-gill.com/api/v2/skills/alarm-sources
```

## 10. automate_skill_patrol — 設成排程 Auto Patrol
- **POST** `/api/v2/skills/{idOrSlug}/automation`
- Body:
  ```json
  {"role":"patrol",
   "trigger":{"kind":"schedule","schedule":"每 1 小時","target":"所有機台"},
   "alarm_gate":"任一符合 → alarm",
   "outcome":"raise alarm · 可被下游接"}
  ```
- 目錄值（傳錯會被拒）:
  - `schedule`：`每 30 分鐘` | `每 1 小時` | `每 2 小時` | `每日 08:00`
  - `target`：`所有機台`（或機台清單字串）
  - `outcome`：`raise alarm · 可被下游接` | `advisory only · 只通知` | `接 action / workflow`
- 前提：skill `has_alarm=true`（pipeline 含 block_step_check）。
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills/11/automation \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"role":"patrol","trigger":{"kind":"schedule","schedule":"每 1 小時","target":"所有機台"},"alarm_gate":"任一符合 → alarm","outcome":"raise alarm · 可被下游接"}'
```

## 11. automate_skill_event — 設成事件觸發（上游 patrol alarm 時跑）
- **POST** `/api/v2/skills/{idOrSlug}/automation`
- Body:
  ```json
  {"role":"patrol",
   "trigger":{"kind":"event","source":"<上游 patrol 的 slug>"},
   "alarm_gate":"任一符合 → alarm",
   "outcome":"raise alarm · 可被下游接"}
  ```
- `source` 用 list_event_sources（method 9）拿到的 slug。前提同上 `has_alarm=true`。
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills/18/automation \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"role":"patrol","trigger":{"kind":"event","source":"process-5-in-2-out-jf2a"},"alarm_gate":"任一符合 → alarm","outcome":"raise alarm · 可被下游接"}'
```

## 12. automate_skill_datacheck — 設成排程 Data Check（永不告警）
- **POST** `/api/v2/skills/{idOrSlug}/automation`
- Body: `{"role":"datacheck","trigger":{"kind":"schedule","schedule":"每日 08:00","target":"所有機台"},"alarm_gate":null,"outcome":"data only"}`
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills/18/automation \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"role":"datacheck","trigger":{"kind":"schedule","schedule":"每日 08:00","target":"所有機台"},"alarm_gate":null,"outcome":"data only"}'
```

## 13. remove_skill_automation — 收回自動化（回 tool）
- **DELETE** `/api/v2/skills/{idOrSlug}/automation`
- Response: `data` = `SkillDto`（role=tool, trigger/gate/outcome 清空）
```bash
curl -s -X DELETE https://aiops-gill.com/api/v2/skills/11/automation \
  -H "Authorization: Bearer $AIOPS_TOKEN"
```

## 14. activate / deactivate — 啟用 / 停用（draft ↔ active）
- 啟用：**POST** `/api/v2/skills/{idOrSlug}/activate`
- 停用：**POST** `/api/v2/skills/{idOrSlug}/deactivate`
- Response: `data` = `SkillDto`（status 切換）
- 注意：scheduler 只跑 `status=active` 的 skill；建好預設 draft，要 activate 才生效。
```bash
curl -s -X POST https://aiops-gill.com/api/v2/skills/11/activate \
  -H "Authorization: Bearer $AIOPS_TOKEN"
```

## 15. delete_skill_v2 — 刪除 Skill
- **DELETE** `/api/v2/skills/{idOrSlug}`
- 綁定的 pipeline **不會**被刪（其他地方可能引用）。
```bash
curl -s -X DELETE https://aiops-gill.com/api/v2/skills/18 \
  -H "Authorization: Bearer $AIOPS_TOKEN"
```

---

## 典型流程（curl 串起來）
```bash
# 1) 建一個帶 pipeline 的 skill（draft）
SID=$(curl -s -X POST https://aiops-gill.com/api/v2/skills/with-pipeline \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"slug":"...","name":"...","nl":"...","pipeline_json":{...}}' \
  | jq -r '.data.skill.id')

# 2) 預檢能不能當 patrol
curl -s -H "Authorization: Bearer $AIOPS_TOKEN" \
  "https://aiops-gill.com/api/v2/skills/$SID/role-readiness?role=patrol"

# 3) 設排程巡檢
curl -s -X POST https://aiops-gill.com/api/v2/skills/$SID/automation \
  -H "Authorization: Bearer $AIOPS_TOKEN" -H "Content-Type: application/json" \
  -d '{"role":"patrol","trigger":{"kind":"schedule","schedule":"每 1 小時","target":"所有機台"},"alarm_gate":"任一符合 → alarm","outcome":"raise alarm · 可被下游接"}'

# 4) 啟用
curl -s -X POST https://aiops-gill.com/api/v2/skills/$SID/activate \
  -H "Authorization: Bearer $AIOPS_TOKEN"
```

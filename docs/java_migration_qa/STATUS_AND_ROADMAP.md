# Status + Roadmap — 2026-04-22 後半段

## 目前 production 實際狀態（EC2 43.213.71.239）

| 面向 | 狀態 | 備註 |
|---|---|---|
| Frontend `FASTAPI_BASE_URL` | `http://localhost:8001`（舊 Python）| 先前切 Java 的 cutover 已 rollback |
| Alarm 產生 engine | **舊 Skill-based**（event_poller → skill.steps_mapping）| 現行 baseline，正常運作中 |
| Diagnostic rule engine | **舊 Skill-based**（poller DR fan-out → skill.steps_mapping source='rule'）| 現行 baseline |
| Java API `:8002` | ✅ 運作中（shadow）| 沒人打它 |
| Python sidecar `:8050` | ✅ 運作中（shadow）| 沒人打它 |
| 舊 Python `:8001` | ✅ **所有真實流量** | Frontend / Poller / DR 全走這 |

## 已做但目前未啟用的 engine 級成果（Phase 7c-v1 殘留）

| 項目 | 狀態 | 在 DB / Code 裡？ |
|---|---|---|
| `block_compute` engine feature | ✅ shipped + seeded | `pb_blocks` 有 row，code 在 repo |
| 7 個 auto_patrol pipelines 語意修正 | ✅ pipeline_json 已重寫 | `pb_pipelines` id 1,2,4,5,6,16,17 |
| `event_poller` → pipeline 路由 patch | ✅ shipped | 老 Python 已跑著這份 code |
| `registry.load_from_db` bug fix | ✅ shipped | 同上 |
| `execution_logs.skill_id` nullable | ✅ schema migrated | DDL 已改 |
| 7 個 pipeline `status=active` | ✅ 但沒人用 | `auto_patrols.pipeline_id=NULL` |
| **22 個 diagnostic rule pipelines** | 🔴 **從沒 parity-diff** | 全 draft，沒 wire |

## 已知的 pipeline engine 未解問題

| 問題 | 影響 |
|---|---|
| **Silent failure**：patrol 綁 pipeline 後 2 分鐘 2 個 OOC 事件沒產生任何 execution_log / error log | pipeline path 在 prod 規模從沒跑成功過 |
| **22 個 DR pipeline 沒 parity-diff** | 很可能跟 7 個 auto_patrol 一樣混著 inverted / skeleton / narrower bugs |
| **DR routing 機制沒 patch**（`_run_diagnostic_rules_for_alarm` 還只跑 skill path）| 即使 DR pipeline 沒問題，舊 Python 目前也不會用它 |

## 跟 Java 切換失敗的 root causes（上次）

| 問題 | 影響 |
|---|---|
| **Envelope mismatch**：Java `/api/v1/alarms` 回 `{total, items}`，Frontend 預期直接 array | Alarm Center 空 |
| **Path mismatch**：Frontend 很多 route 打 `/api/v1/admin/*`，Java 路徑是 `/api/v1/*` | 多個頁面 404/500 |
| **Auth token format**：Frontend `INTERNAL_API_TOKEN` 是舊 Python 的 48-char hex shared-secret，Java 只吃 JWT | Pipeline Builder 頁 401 unauthorized |

---

## 優先級 Roadmap

### P1 — 下架舊 Skill engine（alarm + DR 全走 pipeline）

**為什麼**：使用者說要下架舊的。完成這個之後，舊 Python 的 Skill engine code 才能真正淘汰；pipeline engine 才是單一事實。

**工作分解**：

| # | 工作 | 工時估 | 備註 |
|---|---|---|---|
| P1-1 | Debug pipeline path silent failure | 1-3 小時 | 加詳細 log、trace 一次 OOC → pipeline → DB 的完整執行；找出是哪段吞掉 exception |
| P1-2 | 22 個 DR pipeline 做 parity diff | 1 天 | 類似之前對 7 個 auto_patrol 做的，但量大；會發現 X 個 bug |
| P1-3 | 修 DR pipeline_json 的 bugs | 1-2 天 | 視 parity diff 結果 |
| P1-4 | 補 DR routing patch（`_run_diagnostic_rules_for_alarm` → 檢查 `skill.trigger_patrol_id` 對應的 patrol.pipeline_id，或其他機制）| 半天-1 天 | 需要先搞清楚 DR 的 wire-up 邏輯 |
| P1-5 | 統一 activation：7 auto_patrol + N DR 一起切 | 半天 | SQL 批次 |
| P1-6 | 30 min parity watch：新 alarm / DR 跟舊 1h 的內容 diff | 半天 | 人眼 / 腳本都要 |
| P1-7 | 下架：5 auto_patrol Skill + 24 rule Skill 設 `is_active=False` | trivial | 最後一步 |
| | **總計** | **4-7 人日** | 不含卡住的 debug 時間 |

**風險**：pipeline engine 本身還有未解的 silent bug。如果 P1-1 debug 花很久（甚至發現 pipeline_executor 在 prod 規模本質上壞掉），**整個 P1 會被阻擋**。

### P2 — 切 Java cutover（修 envelope + path + auth）

**為什麼**：使用者說第二順位。

**工作分解**：

| # | 工作 | 工時估 | 備註 |
|---|---|---|---|
| P2-1 | **Parity probe script**：把 40+ Frontend `/api/*` 逐一打 `:8001` vs `:8002` 比對 status + body shape | 半天 | 自動化 diff report |
| P2-2 | Java 加 **envelope compat layer**：`/api/v1/alarms` 等回 direct array（跟 Python 一致），paginated 版改 `/api/v1/alarms?paginated=true` 或獨立 endpoint | 1 天 | 改 6-10 個 Controller |
| P2-3 | Java 加 **path aliases**：`/api/v1/admin/alarms` → 內部 forward 到 `/api/v1/alarms` | 半天 | Spring MVC forward 或新 controller |
| P2-4 | Java 加 **dual-auth filter**：接受 JWT **或** 長字串 shared-secret token（env 設）| 半天 | 改 SecurityFilter |
| P2-5 | Re-run probe：目標 100% identical | 1 小時 | 循環到綠 |
| P2-6 | 每頁 manual smoke（11 頁）| 1 小時 | |
| P2-7 | Flip `FASTAPI_BASE_URL` + restart + 1h watch | 1 小時 | |
| | **總計** | **2.5-3.5 人日** | Java 端包得很明確 |

**風險**：parity probe 可能掃出比想像多的差異（30+？）。可以漸進 shim — 每掃到一個就補一個，不是一口氣做。

---

## 順序建議

**走 P1 → P2**（你提的）：
- ✅ 乾淨 — 切 Java 時 alarm engine 已經是 pipeline 了
- ❌ 慢 — P1 很可能卡在 debug（已知 silent failure）
- 估 **6-10 人日** 全完成

**走 P2 → P1**（另一可能）：
- ✅ 快 — P2 面相明確、風險可控，2-3 天內 Java cutover 穩定
- ✅ P1 可以從容做 — 不會影響 Java 切換
- ❌ 短期「舊 Skill 還在跑」的混亂狀態（但其實已經這樣了）
- 估 **6-10 人日** 全完成（總時差不多，但早期價值更快兌現）

**混合（我推薦）**：
1. **先** P2-1 parity probe + P2-2/3/4 envelope/path/auth fix → Java cutover 穩（**3 天內看得到 UI 在 Java 上跑**）
2. **同時** P1-1 debug silent failure 在 side track（不阻擋主線）
3. P2 完成後，回頭做 P1-2/3/4 — parity diff + DR routing
4. **最後** P1-5/6/7 統一切換 + 下架舊 Skills

---

## 如果選第 3 條（混合）這一輪 Session 能做到的

考量 context budget，這一輪最多推進到：
- 寫 parity probe script + 跑一次 + 寫 diff report
- Java 加 1-2 個最明顯的 shim（envelope + 最多路徑的 path alias）
- 不做 cutover — 等 probe 100% identical 再切

剩下的下一個 session 繼續。

---

**你決定順序 + 起手做哪個**：
- A. P1 → P2（按你原提的）
- B. P2 → P1
- C. 混合（先 P2 穩 Java，side track 偵測 P1 silent bug）
- D. 其它

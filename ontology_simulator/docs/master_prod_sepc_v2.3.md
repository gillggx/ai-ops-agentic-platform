Agentic OS v2.0: AIOps Skill Library & API Mapping Spec

發布目標：本規格書旨在定義 Agentic OS 上層 AI Agent 的「技能庫 (Skill Library)」。透過底層 Ontology 提供的 4 大視角 API (Process, Tool, Lot, Object)，系統將能自動執行過去需要資深工程師耗費數小時才能完成的複雜診斷。

▍回顧：Ontology 的四大視角 API (The 4 Pillars)

為了保持 RESTful API 的對稱性與一致性，API 路由已於本版次進行統一收斂：

Pillar 1 (Point-in-Time): GET /api/v2/ontology/context?lot_id={lot}&step={step}

Pillar 2 (Tool-Centric): GET /api/v2/ontology/trajectory/tool/{tool_id} (v2.3 實作處理歷史；v2.4 擴充狀態機)

Pillar 3 (Lot-Centric): GET /api/v2/ontology/trajectory/lot/{lot_id} (自舊版 URL 遷移統一)

Pillar 4 (Object-Centric): GET /api/v2/ontology/history/{object_type}/{object_id} (必須回傳 Joined Data，包含關聯的 SPC 結果)

▍AIOps 技能庫矩陣 (Skill Library Matrix)

以下列出 Agent 基於上述 4 支 API 所能執行的 12 大廠務核心 Use Cases。部分技能依賴底層 Simulator 的擴充，將依據文末的「交付藍圖」分階段實作。

類別一：基於單點現場還原 (Pillar 1: Point-in-Time Context)

專注於「當下那一秒鐘」發生了什麼事，通常由 Alarm 或 OOC 觸發。

AIOps 技能 (Skill)

廠務痛點 (Pain Point)

API 呼叫路徑

Agent 自動診斷邏輯 (Diagnostic Logic)

OOC_Root_Cause

SPC 圖表亮紅燈，不知道是機台飄移還是配方設錯。

呼叫 Pillar 1 取得該 Lot 該 Step 的完整拓樸圖。

檢查 APC 補償是否達極限 (Hit Limit) ➔ 檢查 DC 壓力/溫度是否偏離歷史 Baseline ➔ 產出根因結論。

Alarm_Correlation



(v2.4)

機台噴出 "He Flow Error" Alarm，不確定當下有沒有傷到晶圓。

呼叫 Pillar 1 傳入 (tool_id, event_time)。

反查當時正在跑哪批 Lot、哪個 Recipe ➔ 擷取該毫秒的 DC Sensor 數值，判斷是否需要將該批 Lot HOLD。

Defect_Review_Sync

缺陷檢測機 (KLA) 掃出晶圓邊緣有刮傷，想看上一站的機台參數。

呼叫 Pillar 1 傳入 (lot_id, 前一站step)。

調閱前一站機台的 DC 靜電夾頭 (ESC) 電壓與溫度，判斷是否為夾爪異常造成刮傷。

類別二：基於機台生命週期 (Pillar 2: Tool-Centric Trajectory)

專注於機台的「歷史穩定度」，通常用於評估保養 (PM) 或老化 (Aging)。

AIOps 技能 (Skill)

廠務痛點 (Pain Point)

API 呼叫路徑

Agent 自動診斷邏輯 (Diagnostic Logic)

First_Wafer_Effect



(v2.4)

機台閒置 (IDLE) 太久後，第一批貨的溫度總是不準，導致良率下降。

呼叫 Pillar 2 拉出該機台軌跡。

篩選出所有「IDLE 超過 4 小時後的第一筆 Process Event」➔ 分析其 DC 溫度起伏，自動建議是否需加長暖機 (Dummy Wafer) 時間。

PM_Recovery_Check



(v2.4)

機台洗完 Chamber (PM) 復機後，不知道狀態有沒有回到 Baseline。

呼叫 Pillar 2 尋找 PM_DONE 錨點。

自動抓取 PM 前 10 批與 PM 後 5 批的 DC 參數 ➔ 進行 T-Test 檢定，若差異過大則自動發信警告 EE 工程師。

Chamber_Matching

雙子星機台 (Chamber A vs B) 跑同一個 Recipe，產出卻不一樣。

呼叫 Pillar 2 取得 Tool A 與 Tool B 的歷史。

過濾出相同的 Recipe ID ➔ 將兩者的 DC (如 RF Power) 與 SPC (如 CD 值) 進行重疊比對，抓出硬體差異。

類別三：基於批次生產軌跡 (Pillar 3: Lot-Centric Trajectory)

專注於晶圓的「旅行履歷」，通常用於客訴 (RMA) 或良率驟降分析。

AIOps 技能 (Skill)

廠務痛點 (Pain Point)

API 呼叫路徑

Agent 自動診斷邏輯 (Diagnostic Logic)

Scrap_Genealogy

一批貨在第 45 站破片報廢，需追溯它前面經歷了哪些風險機台。

呼叫 Pillar 3 拉出該 Lot 的垂直時間軸。

掃描前 44 站的所有 DC 快照，尋找是否有「應力異常」或「未觸發 Alarm 但數值偏高」的隱性異常點。

Q_Time_Violation

晶圓在蝕刻後、清洗前等太久 (Queue Time)，長出氧化層導致電性失效。

呼叫 Pillar 3 拉出時間軸。

計算相鄰 Step 之間的 time_delta ➔ 若超過規範的 Q-Time 且下一站的 SPC 異常，自動標記為 Q-Time Issue。

Rework_Analysis

某批貨重工 (Rework) 洗掉重做 2 次，不知道是哪一次參數有問題。

呼叫 Pillar 3 拉出時間軸。

找出相同 Step 出現 2 次的紀錄 (Pass 1 vs Pass 2) ➔ 比對兩次的 Recipe 版本與 DC 差異。

類別四：基於全知物件效能 (Pillar 4: Object-Centric Performance) ⭐ 殺手級應用

打破機台與批次的界線，讓 Agent 對特定「配方」或「演算法」進行跨維度體檢。
(技術要求：此 Pillar 回傳資料必須為 Joined Data，將 Object 快照與其參與事件的 spc_status 進行聚合)

AIOps 技能 (Skill)

廠務痛點 (Pain Point)

API 呼叫路徑

Agent 自動診斷邏輯 (Diagnostic Logic)

APC_Model_Audit

R2R (Run-to-Run) 演算法給的補償值可能在震盪，導致連續批次良率不穩。

呼叫 Pillar 4 傳入 (APC, APC-0042)

取出過去 500 次該 APC 介入的紀錄 ➔ 比對 bias (給定的補償) 與 SPC (最終量測值)，計算 MSE 誤差，若模型發散則自動建議 Freeze APC。

Recipe_Drift_Detect

工程師微調了配方 (V4.1 -> V4.2)，老闆想看新版到底有沒有比較好。

呼叫 Pillar 4 傳入 (RECIPE, RCP-OX-V4.2)

拉出 V4.2 的所有生產 SPC 結果 ➔ 與 V4.1 的歷史結果進行 A/B Testing ➔ 產出新舊版本 Cpk (製程能力指數) 差異報告。

Hardware_Aging_Track

某個氣體流量計 (MFC) 慢慢老化，但尚未觸發機台硬體 Alarm。

呼叫 Pillar 4 傳入 (DC_SENSOR, MFC_01)

無視 Lot 與 Recipe，將該 Sensor 過去一個月的數值畫成線性回歸圖 ➔ 若發現緩慢上升趨勢 (Drift)，自動開立預防性維護工單 (PM WO)。

▍開發與交付藍圖 (Phased Roadmap)

為確保系統穩定演進，AIOps 的底層資料支援將分為以下三個 Sprint 階段進行交付：

Sprint v2.3a (優先 MVP)

實作 Pillar 4 (/history/{type}/{id})，並確保回傳資料已 Join spc_status。

實作 Pillar 2 (選項 A：僅回傳機台歷史處理批次紀錄)。

交付 verify_apc_audit_skill.py 測試腳本，於 Local 環境驗證上述兩支 API。

Sprint v2.3b (路由重構)

統一 Pillar 3 URL 為 /trajectory/lot/{lot_id}。

更新前端 OBJECT_API_REGISTRY 對應設定。

Sprint v2.4 (狀態機擴充)

升級底層 Simulator，補齊機台 PM_START, PM_DONE, ALARM 等狀態機事件。

升級 Pillar 2 支援上述狀態時間軸，並正式啟用 First_Wafer_Effect, PM_Recovery_Check 技能。

▍底層驗證規範 (Test Script Requirements)

依照團隊 [2026-02-27] 制定的規範，提供給架構師或維運人員的驗證腳本定位為 Local Troubleshooting / Demo Script，主要用於本機開發時快速確認資料庫關聯邏輯，無須掛載於強制阻擋的 CI 流程中。

開發者行動 (Action Item)：
請撰寫 verify_apc_audit_skill.py 腳本，模擬 Agent 執行 APC_Model_Audit 技能：

呼叫 GET /api/v2/ontology/history/APC/APC-0042。

腳本需模擬 Agent 的思維，從回傳的歷史清單中提取每次的 etch_time_offset (補償值) 與其對應的 spc_status。

若連續 3 筆發生 OOC 且 offset 變動劇烈，腳本必須在 Terminal 印出：[Agent 決策] 警告：APC-0042 模型發生震盪發散，建議立即停止補償。
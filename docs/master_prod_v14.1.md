Agentic OS v14.0 - Master Engineering Spec (Hybrid Memory Edition)
1. 核心願景 (Core Vision)
打造一個具備 Glass Box (玻璃盒) 架構、微型反饋閉環 (Micro-Feedback Loop)，以及 高精準混合記憶系統 (Hybrid Memory System) 的工業級 Agentic OS。 系統遵循 「先學會走（避開錯誤指令），再學會跑（吸收人類偏好）」 的原則。透過 Metadata Indexing 的嚴格隔離，確保 Agent 在海量機台與複雜任務中，能精準提取「同任務、同工具」的歷史經驗，徹底杜絕跨任務的記憶污染（幻覺），實現越用越聰明的工廠大腦。
2. 五階段透明化日誌 (5-Stage Status Tracking)
Agent 的每一次運作必須明確經歷以下階段，並透過 SSE (stage_update) 同步輸出至 Glass-box Console：
Stage 1: 情境感知與精準提取 (Context Load & Hybrid Retrieval)：載入 Soul、RAG 通用知識。透過當前任務的 Metadata (任務類型、機台、工具) 對 Mem0 / pgvector 進行「預先過濾 (Pre-filtering)」，精準提取 User Profile 與 Trap 避坑指南並注入 Prompt。
Stage 2: 意圖解析與規劃 (Intent & Planning)：強制覆誦（Acknowledge）檢索到的記憶約束後，生成並輸出 <plan> 步驟標籤（降階版 DAG）。
Stage 3: 工具調用與安全審查 (Tool Execution & Security)：執行 Tool，並進行 Token 蒸餾與權限檢查。(若發生 API Error，觸發微型 Feedback 擷取)
Stage 4: 邏輯推理與反思 (Reasoning & Reflection)：擔任 Evaluator（評估者）。若驗證失敗，啟動「現場修正」；若成功，結合蒸餾數據進行最終分析。
Stage 5: 回覆與記憶寫入 (Output & Indexing Memory)：輸出回覆，並將本次的「修正經驗 (Trap/Rule)」與「操作偏好」，綁定嚴格的 Metadata 標籤後寫入 Mem0 與 Workspace。
3. 情境注入與混合記憶應用 (Hybrid Memory Injection)
為了解決傳統向量搜尋「張冠李戴」的記憶污染問題，系統在寫入與讀取記憶時，必須嚴格遵守 Metadata Indexing 與混合搜尋機制：
結構化記憶標籤 (Metadata Indexing)：所有存入 Mem0 的記憶都必須強制夾帶以下 JSON 標籤：
task_type: 當前任務屬性（如：draw_chart, troubleshooting, data_cleaning）
data_subject: 關聯的主體或機台（如：TETCH01, OOC_logs）
tool_name: 使用的具體工具（如：draw_spc_chart, search_logs）
混合搜尋與預先過濾 (Hybrid Search & Pre-filtering)：在 Stage 1 讀取記憶時，底層 (如 pgvector) 必須先執行 Metadata 條件過濾 (WHERE metadata->>'tool_name' = '...')，再進行向量相似度排序 (ORDER BY embedding <=> query)。確保「畫圖表」的任務只會喚醒「畫圖表」的經驗。
Prompt 區塊化組裝：在 System Prompt 頂端開闢專屬區塊。
4. Token 效能防護網 (Token Efficiency Strategy)
為確保 Mem0 等記憶系統能穩定運作，必須嚴格控管 Context 消耗：
Layer 1: 語義蒸餾 (Semantic Distillation)：Stage 3 工具執行完成後，嚴禁傳送原始大型 JSON。必須透過沙盒代碼過濾為「統計摘要 + 關鍵異常點」。
Layer 2: 動態摘要 (Dynamic History Compaction)：當 Session 預估 Token 超過 60k 時，同步壓縮前半段對話為單一 <summary>。
Layer 3: 緩存優化 (Prompt Caching)：對 System Prompt 加上 cache_control: {"type": "ephemeral"}。
5. 「先走再跑」：微型反饋與記憶閉環 (The Feedback & Learning Loop)
5.1 階段一：指令自動修復與 Negative Index (Learning to Walk)
機制：當 MCP 工具回傳錯誤（如：參數缺失）時，Agent 不准向用戶報錯。
動作 (Micro-Reflexion)：
診斷與修正：擷取 Error Traceback，自動修正指令並重新執行。
精準沉澱 (Indexed Trap)：將「Trap + Rule」寫入 Negative Index，並強制綁定引發報錯的 tool_name 作為 Metadata。
5.2 階段二：HITL 參數覆寫與偏好記憶 (Learning to Run)
機制 (Human-in-the-Loop Feedback)：當系統將結果擴展至工作區後，賦予用戶最高權重的修改權。
動作：
UI State Sync：用戶在介面手動調整參數時，前端自動將 canvas_overrides 作為隱形 Feedback 同步回 Context。
微型評估與精準沉澱 (Indexed Profile)：Agent 反思參數差異，並將偏好寫入 User Profile，同時綁定 task_type 與 data_subject 作為 Metadata。
6. Glass Box 與雙向協作介面 (Workspace Interface)
Console 透明化：將 Agent 的「內心戲」（包含 Metadata 過濾條件、失敗重試、Feedback 反思）實時推送。
雙向狀態同步：具備 workspace_state (JSONB)，前端修改直接觸發 Event workspace_update 與 stage_update。
安全預演 (Dry-Run)：針對破壞性操作 (is_destructive: true)，強制觸發 SSE approval_required，等待人類點擊 Approve。
--------------------------------------------------------------------------------

🧪 7. 給 Claude Code (小柯) 的實作腳本 (包含 Metadata Indexing)
請要求小柯執行以下腳本，驗證「Pre-filtering 讀取 → 報錯 → 帶有 Metadata 的寫入 → 帶有條件的再應用」完整生命週期：
# v14_core_logic_test_hybrid_memory.py

def v14_execution_loop_test():
    current_context = {
        "task_type": "draw_chart",
        "data_subject": "A1",
        "tool_name": "draw_spc_chart"
    }
    
    print(f"🚀 [Stage 1] Context Load & Hybrid Retrieval: Fetching from Mem0 with PRE-FILTERS: {current_context}...")
    
    # 模擬 Stage 1: 預先過濾後沒有找到經驗
    learned_experience = {"trap": "None", "preference": "None"}
    print("📝 [Stage 2] Intent & Planning: Generating <plan> tags...")
    
    # 模擬 Stage 3: Agent 第一次嘗試 (缺少必要參數)
    prompt = "draw_spc_chart(machine_id='A1')"
    render_result = {"status": "error", "message": "Missing required field: sigma_level"}
    
    # 🌟 5.1 階段一：自動修復與建立 Indexed Trap
    if render_result["status"] == "error":
        print(f"\n👁️ [Glass Box] Detected Error: {render_result['message']}")
        print("🧠 [Micro-Reflexion] Agent evaluates the failure...")
        
        # 模擬 Agent 自動修正
        fixed_prompt = "draw_spc_chart(machine_id='A1', sigma_level=3)"
        print(f"✅ [Self-Correction] Re-executing: {fixed_prompt}")
        
        # 寫入 Negative Index 並綁定 Metadata
        lesson = f"[TRAP AVOIDED] Tool rejected {prompt} -> [RULE] Always include sigma_level."
        print(f"💾 [Stage 5] Memory Write: Saving to Negative Index with METADATA {current_context}")
        print(f"   -> Content: '{lesson}'")

    print("\n🏁 [Success] Chart Rendered and output to Workspace.")
    
    # 🌟 5.2 階段二：HITL 參數覆寫與 Indexed Preference
    print("\n🧑‍💻 [Human-in-the-Loop] User manually changes sigma_level to 2 on the UI Dashboard...")
    human_feedback = "User prefers sigma_level=2 over default 3 for machine A1."
    print(f"💾 [Stage 5] Preference Memory Write with METADATA {current_context}")
    print(f"   -> Content: '{human_feedback}'")
    
    # 🌟 驗證 Hybrid Search 的精準再應用機制 (Next Session)
    print("\n--- ⏭️ Next Session (Same Task) ---")
    print(f"🚀 [Stage 1] Context Load & Retrieval using PRE-FILTERS: {current_context}...")
    print(f"📥 [Hybrid Search Result] Found matching experience: {human_feedback} | {lesson}")
    print("📝 [Stage 2] Intent & Planning: Agent explicitly acknowledges constraints in <plan>...")
    print("✅ Agent correctly formulates plan using sigma_level=2 directly on the first try.")
    print("✨ Agentic OS successfully completed the Hybrid Memory Lifecycle.")

if __name__ == "__main__":
    v14_execution_loop_test()
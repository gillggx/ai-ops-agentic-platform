┌─────────────────────────────────────────────────────────────────────┐
│  1. load_context                                                    │
│     • 讀 user_preference / system_parameter / agent_session         │
│     • 抽 experience_memory（pgvector cosine top-K）                  │
│     • 組 system_prompt：blocks 目錄 + skills 目錄 + 當下 alarms +    │
│       focus equipment + pipeline_snapshot（如果在 builder mode）    │
│     • 寫 system_blocks（含 cache_control breakpoints）              │
└─────────────────────────────────────────────────────────────────────┘
                            ↓
┌─────────────────────────────────────────────────────────────────────┐
│  2. intent_classifier (haiku)                                       │
│     5 buckets：                                                      │
│       clear_chart   想看圖（給我 X chart / 趨勢圖）                    │
│       clear_rca     想知道為什麼（為何 EQP-07 OOC）                   │
│       clear_status  想知道現況（現在多少 alarm / OOC 機台清單）         │
│       knowledge     概念題（WECO R5 是什麼？Cpk 怎麼算？）              │
│       vague         開放式（最近怎樣？狀況如何？） → 出 clarify card    │
│                                                                      │
│     ⚠ 目前 builder mode 一律 bypass 成 clear_chart（這就是 bug）       │
│                                                                      │
│     Re-submit 機制：user 從 clarify card 選一個 → message 帶 prefix   │
│       `[intent=spc_chart] ...` → bypass classifier、直走 llm_call    │
└─────────────────────────────────────────────────────────────────────┘
            ↓                            ↓                       ↓
        vague                       clear_*                   clarified/knowledge
        (force_synthesis)           ↓                              ↓
            ↓               ┌──────────────┐                       │
            │               │ 3. intent_completeness               │
            │               │    (haiku gate)                       │
            │               │  判斷需求是否「inputs+logic+         │
            │               │  presentation 三齊全」                │
            │               │                                       │
            │               │  不全 → 出 design_intent_confirm     │
            │               │       SSE event + force_synthesis   │
            │               │  齊全 → llm_call                     │
            │               │                                       │
            │               │  ⚠ 這個 gate 是 2026-05-02 加的       │
            │               │   防 LLM 自由意志違抗 prompt rule     │
            │               └──────────────┘                       │
            │                       ↓                              │
            │                  incomplete   complete               │
            │                       ↓           ↓                  │
            └──→ synthesis ←────────┘           └──→ llm_call ←────┘
                                                       │
                                                       ↓
                              ┌──────────────────────────────────────┐
                              │ 4. llm_call (sonnet)                 │
                              │    • 拿 system_blocks + tools list   │
                              │    • LLM 決定：寫文字 OR 呼叫 tool    │
                              │    • Tools: search_published_skills, │
                              │      execute_skill, execute_mcp,     │
                              │      build_pipeline_live, ...        │
                              └──────────────────────────────────────┘
                                          ↓
                                  ┌───────┴───────┐
                              has tool_calls?     no tool_calls
                                  ↓                       ↓
                  ┌────────────────────────────────┐    │
                  │ 5. tool_execute                │    │
                  │    • 跑 LLM 點名的 tool         │    │
                  │    • 結果以 ToolMessage 寫回    │    │
                  │      messages                  │    │
                  │    • Loop guard：同 tool 同     │    │
                  │      args 連 3 次 → inject     │    │
                  │      _loop_warning              │    │
                  └────────────────────────────────┘    │
                          ↓                              │
                  back to llm_call                       │
                  (LLM 看 tool result → 決定下一步)       │
                                                         │
                                          所有 path 最後 → synthesis
                                                         ↓
                              ┌──────────────────────────────────────┐
                              │ 6. synthesis                         │
                              │    • 把 messages + render_cards 組成  │
                              │      最終 AIOpsReportContract        │
                              │    • Emit final markdown SSE         │
                              └──────────────────────────────────────┘
                                          ↓
                              ┌──────────────────────────────────────┐
                              │ 7. self_critique                     │
                              │    • 二次 LLM call 看自己這次答得對嗎  │
                              │    • 寫 reflection_result            │
                              └──────────────────────────────────────┘
                                          ↓
                              ┌──────────────────────────────────────┐
                              │ 8. memory_lifecycle                  │
                              │    • 寫 experience_memory（成功 ops）  │
                              │    • feedback 到引用過的 memory ids   │
                              └──────────────────────────────────────┘
                                          ↓
                                         END

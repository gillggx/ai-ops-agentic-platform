import json
import uuid

# 模擬實作 mcp_event_triage 邏輯
def execute_mcp_event_triage(user_symptom: str) -> str:
    print(f"🛠️ [分診執行中] 分析症狀: '{user_symptom}'")
    if "慢" in user_symptom:
        result = {
            "event_id": f"EVT-{uuid.uuid4().hex[:8]}",
            "event_type": "Performance_Issue",
            "attributes": {"symptom": "latency"},
            "recommended_skills": ["mcp_mock_cpu_check"]
        }
    else:
        result = {
            "event_id": f"EVT-{uuid.uuid4().hex[:8]}",
            "event_type": "Unknown",
            "attributes": {},
            "recommended_skills": ["ask_user_recent_changes"]
        }
    return json.dumps(result, ensure_ascii=False)

def test_triage():
    print("🚀 啟動 Event Triage 底層測試...\n")
    user_input = "系統首頁跑得好慢"
    output = json.loads(execute_mcp_event_triage(user_input))
    
    print("📦 產生的 Event Object:")
    print(json.dumps(output, indent=2, ensure_ascii=False))
    
    assert "mcp_mock_cpu_check" in output["recommended_skills"], "❌ 路由錯誤"
    print("\n✅ 分診邏輯測試通過！")

if __name__ == "__main__":
    test_triage()
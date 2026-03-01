import requests
import json

def test_combined_sse_and_triage():
    url = "[http://127.0.0.1:8000/api/v1/diagnose](http://127.0.0.1:8000/api/v1/diagnose)"
    # 若有 JWT，請自行替換；若開發環境暫時關閉 Auth，請保持空白
    headers = {"Authorization": "Bearer <YOUR_TOKEN>", "Accept": "text/event-stream"}
    payload = {"issue_description": "網站首頁載入超級慢。"}
    
    print("🚀 啟動 SSE 實況與分診邏輯整合測試...\n")
    first_tool_called = None
    
    try:
        with requests.post(url, json=payload, headers=headers, stream=True) as response:
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    decoded = line.decode('utf-8')
                    if decoded.startswith("event: tool_call"):
                        print(f"\n[TOOL_CALL 觸發]")
                    elif decoded.startswith("data:"):
                        data = json.loads(decoded.split("data: ")[1])
                        if "tool_name" in data:
                            tool_name = data["tool_name"]
                            print(f"👉 Agent 呼叫了: {tool_name}")
                            if first_tool_called is None:
                                first_tool_called = tool_name
                                
        print("\n" + "-" * 50)
        assert first_tool_called == "mcp_event_triage", f"❌ 錯誤：第一個呼叫的工具是 {first_tool_called}，而非 mcp_event_triage"
        print("✅ 整合測試通過！Agent 成功遵守分診優先原則並透過 SSE 輸出。")
    except Exception as e:
        print(f"❌ 測試失敗: {e}")

if __name__ == "__main__":
    test_combined_sse_and_triage()
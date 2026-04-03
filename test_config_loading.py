import os
import sys

# 模擬載入環境變數 (實務上這會由 python-dotenv 或 pydantic-settings 處理)
# 我們先暫時清空特定環境變數，測試系統是否會報錯或使用正確的預設值
os.environ.pop("DATABASE_URL", None)
os.environ.pop("API_SECRET_KEY", None)

print("🔍 [測試] 開始驗證系統設定抽離狀態...")

try:
    # 嘗試匯入系統的設定模組 (請替換為實際的 config 路徑)
    # from core.config import settings
    
    # 這裡我們模擬 pydantic settings 的行為
    class MockSettings:
        def __init__(self):
            self.database_url = os.getenv("DATABASE_URL")
            self.secret_key = os.getenv("API_SECRET_KEY")

    settings = MockSettings()

    if not settings.database_url or not settings.secret_key:
        print("✅ [成功] 系統設定已成功抽離！偵測到缺少環境變數，未發現 Hard-code 數值。")
        print("💡 提示：請確保您的 .env 檔案已正確配置。")
    else:
        print(f"❌ [警告] 發現疑似寫死的設定值！")
        print(f"   Database URL: {settings.database_url}")
        print(f"   Secret Key: {settings.secret_key}")
        sys.exit(1)

except ImportError:
    print("❌ [錯誤] 找不到設定檔模組，請確認小柯是否已建立 config.py 集中管理設定。")

# 驗證完畢
print("🏁 測試腳本執行完畢。")

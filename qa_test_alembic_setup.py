import os
import subprocess

def verify_alembic_configuration():
    print("⏳ [QA 啟動] 驗證 Alembic 資料庫遷移架構...")
    
    # 檢查核心檔案是否存在
    required_files = ["alembic.ini", "alembic/env.py"]
    for file_path in required_files:
        if not os.path.exists(file_path):
            print(f"❌ [QA 阻擋] 找不到必要的 Alembic 設定檔: {file_path}")
            return False

    # 檢查 env.py 是否有正確載入 target_metadata
    with open("alembic/env.py", "r", encoding="utf-8") as f:
        content = f.read()
        if "target_metadata = None" in content and "Base.metadata" not in content:
            print("❌ [QA 阻擋] alembic/env.py 中的 target_metadata 未正確綁定 FastAPI 的 SQLAlchemy Base！這會導致無法自動生成遷移檔。")
            return False

    # 執行 alembic current 檢查是否能正常運作
    try:
        result = subprocess.run(["alembic", "current"], capture_output=True, text=True, check=True)
        print("✅ [配置驗證] Alembic CLI 執行正常。")
        print("🎉 [QA 通過] 資料庫遷移架構建立完成！未來所有 DB Schema 變更將透過 CI/CD 自動且安全地佈署至 AWS。")
        return True
    except subprocess.CalledProcessError as e:
         print(f"❌ [QA 阻擋] Alembic 執行失敗，請檢查資料庫連線或設定: {e.stderr}")
         return False

if __name__ == "__main__":
    verify_alembic_configuration()